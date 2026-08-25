"""ORM models for applications, sessions, documents, payments, and receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Application(Base):
    """Citizen certificate application — classification RESTRICTED."""

    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    application_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    service_code: Mapped[str] = mapped_column(
        String(64), nullable=False, default="INCOME_CERTIFICATE"
    )
    applicant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    current_state: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    processing_status: Mapped[str] = mapped_column(
        String(64), nullable=False, default="DRAFT", index=True
    )
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, default="RESTRICTED")
    form_data: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    consent_granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correcting_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_voice_field: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_voice_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    correction_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    auth_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fee_amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fee_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    payment_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payment_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    sessions: Mapped[list[ConversationSession]] = relationship(back_populates="application")
    documents: Mapped[list[DocumentRecord]] = relationship(back_populates="application")
    payments: Mapped[list[PaymentRecord]] = relationship(back_populates="application")
    receipts: Mapped[list[ReceiptRecord]] = relationship(back_populates="application")


class ConversationSession(Base):
    """Channel session bound to an application — classification RESTRICTED."""

    __tablename__ = "conversation_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="web")
    current_state: Mapped[str] = mapped_column(String(64), nullable=False)
    access_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    classification: Mapped[str] = mapped_column(String(32), nullable=False, default="RESTRICTED")

    application: Mapped[Application] = relationship(back_populates="sessions")


class DocumentRecord(Base):
    """Uploaded document metadata — classification RESTRICTED. No raw content in DB."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("application_id", "document_code", name="uq_app_document_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), nullable=False, index=True
    )
    document_code: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, default="RESTRICTED")
    verification_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ocr_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    application: Mapped[Application] = relationship(back_populates="documents")


class PaymentRecord(Base):
    """Payment attempt metadata — never stores secrets/credentials."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), nullable=False, index=True
    )
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payment_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="mock-payment")
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    application: Mapped[Application] = relationship(back_populates="payments")


class ReceiptRecord(Base):
    """Local receipt metadata after successful payment/submission."""

    __tablename__ = "receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    receipt_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("applications.id"), nullable=False, index=True
    )
    service_code: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    payment_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False, default="INTERNAL")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    application: Mapped[Application] = relationship(back_populates="receipts")
