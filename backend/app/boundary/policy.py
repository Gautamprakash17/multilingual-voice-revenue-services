"""Boundary policy engine — declarative YAML, fail-closed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.boundary.classification import Classification, parse_classification


@dataclass(frozen=True)
class PolicyDecision:
    """Result of evaluating a single egress policy rule."""

    allowed: bool
    reason: str
    policy_ref: str
    requires_approval: bool = False


class PolicyEngine:
    """Load and evaluate boundary policies. Unknown rules → DENY."""

    def __init__(self, policy_path: str | Path) -> None:
        self.policy_path = Path(policy_path)
        self._rules: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        if not self.policy_path.exists():
            # Fail closed: empty rules → everything denied
            self._rules = {}
            return
        with self.policy_path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        self._rules = data.get("classifications", {})

    def evaluate(
        self,
        classification: Classification | str | None,
        destination: str,
        purpose: str,
        approved: bool = False,
    ) -> PolicyDecision:
        """Evaluate whether egress is permitted.

        Fail-closed rules:
        - Unknown classification → DENY
        - Missing destination rule → DENY
        - Explicit DENY → DENY
        - PUBLIC_SAFE cloud ALLOW only when approved=True
        """
        cls = parse_classification(classification)
        dest = (destination or "").strip().lower()
        purpose_key = (purpose or "").strip().lower() or "default"

        if dest not in {"local", "cloud"}:
            return PolicyDecision(
                allowed=False,
                reason=f"Unknown destination '{destination}' — fail closed",
                policy_ref="fail-closed:unknown-destination",
            )

        # Local processing is always allowed (data stays in trust zone A).
        if dest == "local":
            return PolicyDecision(
                allowed=True,
                reason="Local destination — always permitted",
                policy_ref="builtin:local-allow",
            )

        # Cloud destination
        cls_rules = self._rules.get(cls.value)
        if not cls_rules:
            return PolicyDecision(
                allowed=False,
                reason=f"No policy defined for {cls.value} — fail closed",
                policy_ref="fail-closed:missing-classification-policy",
            )

        cloud_rule = cls_rules.get("cloud")
        if cloud_rule is None:
            return PolicyDecision(
                allowed=False,
                reason=f"No cloud rule for {cls.value} — fail closed",
                policy_ref="fail-closed:missing-cloud-rule",
            )

        action = str(cloud_rule.get("action", "DENY")).upper()
        requires_approval = bool(cloud_rule.get("requires_approval", False))
        allowed_purposes = [
            str(p).lower() for p in cloud_rule.get("allowed_purposes", [])
        ]

        policy_ref = f"policies.yaml:{cls.value}.cloud"

        # Hard deny for RESTRICTED / INTERNAL (and any explicit DENY)
        if action == "DENY":
            return PolicyDecision(
                allowed=False,
                reason=f"{cls.value} → cloud is DENY by policy",
                policy_ref=policy_ref,
            )

        if action != "ALLOW":
            return PolicyDecision(
                allowed=False,
                reason=f"Unknown action '{action}' — fail closed",
                policy_ref=policy_ref,
            )

        # ALLOW path — must satisfy approval + purpose constraints
        if requires_approval and not approved:
            return PolicyDecision(
                allowed=False,
                reason="PUBLIC_SAFE cloud requires explicit approval",
                policy_ref=policy_ref,
                requires_approval=True,
            )

        if allowed_purposes and purpose_key not in allowed_purposes:
            return PolicyDecision(
                allowed=False,
                reason=f"Purpose '{purpose}' not in allowed_purposes — fail closed",
                policy_ref=policy_ref,
                requires_approval=requires_approval,
            )

        return PolicyDecision(
            allowed=True,
            reason=f"{cls.value} → cloud ALLOWED for purpose '{purpose}'",
            policy_ref=policy_ref,
            requires_approval=requires_approval,
        )
