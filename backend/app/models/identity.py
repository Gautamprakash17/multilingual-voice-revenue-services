"""Locally registered synthetic citizens — demo identities only."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SyntheticCitizen(Base):
    """POC-only synthetic account created during new-citizen registration."""

    __tablename__ = "synthetic_citizens"
    __table_args__ = (UniqueConstraint("mobile", name="uq_synthetic_citizen_mobile"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    persona_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    mobile: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
