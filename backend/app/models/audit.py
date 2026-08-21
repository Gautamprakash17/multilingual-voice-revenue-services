"""Append-only audit event model.

No update/delete API is exposed. Restricted payload content must never
be stored in metadata — callers must pre-sanitize.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditEvent(Base):
    """Immutable audit trail row."""

    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # JSONB on Postgres; JSON fallback for SQLite test runs
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
