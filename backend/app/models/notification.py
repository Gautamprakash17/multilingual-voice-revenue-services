"""Persisted citizen status notifications — simulated local delivery only."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CitizenNotification(Base):
    """One citizen-facing status notification (not an audit event)."""

    __tablename__ = "citizen_notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    recipient_mobile_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channels: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=list,
    )
    delivery_status: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )
