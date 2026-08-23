"""Data Boundary Gateway — sole egress decision point.

Responsibilities:
  - receive payload + classification + destination + purpose
  - evaluate policy (fail closed)
  - never allow RESTRICTED (or INTERNAL) data to cloud
  - record every allow/deny attempt in the audit log
  - return a structured result
  - NEVER store raw restricted payload content in audit metadata
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.boundary.classification import (
    Classification,
    is_cloud_eligible,
    parse_classification,
)
from app.boundary.policy import PolicyDecision, PolicyEngine
from app.boundary.providers import (
    BaseProvider,
    LocalProvider,
    OptionalCloudProvider,
    ProviderResult,
)
from app.core.security import redact_sensitive
from app.platform.audit import write_audit_event


@dataclass
class GatewayRequest:
    """Inbound request to the boundary gateway."""

    payload: dict[str, Any]
    classification: Classification | str | None
    destination: str  # "local" | "cloud"
    purpose: str
    approved: bool = False
    actor_id: str | None = None
    trace_id: str | None = None


@dataclass
class GatewayResult:
    """Structured gateway decision + optional provider outcome."""

    allowed: bool
    decision: PolicyDecision
    classification: Classification
    destination: str
    purpose: str
    trace_id: str
    provider_result: ProviderResult | None = None
    audit_event_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DataBoundaryGateway:
    """Enforced egress control. Cloud providers are only invoked after ALLOW."""

    def __init__(
        self,
        policy_engine: PolicyEngine,
        local_provider: BaseProvider | None = None,
        cloud_provider: BaseProvider | None = None,
    ) -> None:
        self.policy_engine = policy_engine
        self.local_provider = local_provider or LocalProvider()
        self.cloud_provider = cloud_provider or OptionalCloudProvider()

    def evaluate(self, request: GatewayRequest, db: Session | None = None) -> GatewayResult:
        """Evaluate policy and optionally invoke a provider. Fail closed."""
        trace_id = request.trace_id or str(uuid4())
        classification = parse_classification(request.classification)
        destination = (request.destination or "").strip().lower()
        purpose = request.purpose or "unspecified"

        # Extra hard gate: RESTRICTED / non-cloud-eligible never reaches cloud provider
        if destination == "cloud" and not is_cloud_eligible(classification):
            decision = PolicyDecision(
                allowed=False,
                reason=f"{classification.value} is not cloud-eligible — hard deny",
                policy_ref="gateway:hard-deny-non-cloud-eligible",
            )
            return self._finalize(
                request=request,
                decision=decision,
                classification=classification,
                destination=destination,
                purpose=purpose,
                trace_id=trace_id,
                db=db,
                provider_result=None,
            )

        decision = self.policy_engine.evaluate(
            classification=classification,
            destination=destination,
            purpose=purpose,
            approved=request.approved,
        )

        provider_result: ProviderResult | None = None
        if decision.allowed:
            provider = (
                self.cloud_provider if destination == "cloud" else self.local_provider
            )
            # Pass only key names / non-sensitive echo — cloud/local stubs never
            # receive raw restricted payloads over the network.
            safe_payload = {"keys": sorted(request.payload.keys())}
            provider_result = provider.process(safe_payload, purpose)

        return self._finalize(
            request=request,
            decision=decision,
            classification=classification,
            destination=destination,
            purpose=purpose,
            trace_id=trace_id,
            db=db,
            provider_result=provider_result,
        )

    def _finalize(
        self,
        *,
        request: GatewayRequest,
        decision: PolicyDecision,
        classification: Classification,
        destination: str,
        purpose: str,
        trace_id: str,
        db: Session | None,
        provider_result: ProviderResult | None,
    ) -> GatewayResult:
        audit_event_id: str | None = None

        # Audit metadata must NEVER contain raw restricted payload content.
        safe_meta = {
            "destination": destination,
            "purpose": purpose,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "policy_ref": decision.policy_ref,
            "payload_key_count": len(request.payload) if request.payload else 0,
            "payload_keys": sorted(request.payload.keys())[:20] if request.payload else [],
            "approved": request.approved,
            "http_calls_made": (
                provider_result.http_calls_made if provider_result else 0
            ),
        }
        safe_meta = redact_sensitive(safe_meta)

        if db is not None:
            event = write_audit_event(
                db,
                event_type="boundary.decision",
                classification=classification.value,
                trace_id=trace_id,
                actor_id=request.actor_id,
                metadata=safe_meta,
            )
            audit_event_id = event.event_id

        return GatewayResult(
            allowed=decision.allowed,
            decision=decision,
            classification=classification,
            destination=destination,
            purpose=purpose,
            trace_id=trace_id,
            provider_result=provider_result,
            audit_event_id=audit_event_id,
            metadata=safe_meta,
        )
