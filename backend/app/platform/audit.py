"""Append-only audit writer.

Rules:
  - insert only
  - never store raw restricted content
  - never store secrets
  - no update/delete helpers exposed
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.security import redact_sensitive
from app.models.audit import AuditEvent


def write_audit_event(
    db: Session,
    *,
    event_type: str,
    classification: str,
    trace_id: str | None = None,
    actor_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    notes: str | None = None,
) -> AuditEvent:
    """Insert a single audit event. Callers must not pass restricted payloads."""
    safe_meta = redact_sensitive(metadata or {})
    event = AuditEvent(
        event_id=str(uuid4()),
        event_type=event_type,
        actor_id=actor_id,
        trace_id=trace_id,
        classification=classification,
        metadata_json=safe_meta,
        notes=notes,
    )
    db.add(event)
    db.flush()
    return event
