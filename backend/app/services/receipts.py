"""Local receipt generation — plain text POC format (no heavy PDF stack)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.boundary.classification import Classification
from app.models.application import Application, ReceiptRecord
from app.platform.audit import write_audit_event


def generate_receipt(
    db: Session,
    app: Application,
    *,
    trace_id: str | None = None,
) -> ReceiptRecord:
    receipt_id = f"RCP-{uuid4().hex[:8].upper()}"
    amount = app.fee_amount_paise or 0
    currency = app.fee_currency or "INR"
    rupees = amount / 100
    issued_at = datetime.now(UTC).isoformat()
    body = "\n".join(
        [
            "REVENUE DEPARTMENT — APPLICATION RECEIPT",
            f"Receipt ID: {receipt_id}",
            f"Application ID: {app.application_id}",
            f"Service: {app.service_code}",
            f"Fee: {rupees:.2f} {currency}",
            f"Payment reference: {app.payment_ref or 'N/A'}",
            f"Status: {app.processing_status}",
            f"Issued at (UTC): {issued_at}",
            "This is a synthetic POC receipt. No secrets or storage paths included.",
        ]
    )
    record = ReceiptRecord(
        receipt_id=receipt_id,
        application_id=app.id,
        service_code=app.service_code,
        amount_paise=amount,
        currency=currency,
        payment_ref=app.payment_ref,
        status=app.processing_status,
        body_text=body,
        classification=Classification.INTERNAL.value,
    )
    db.add(record)
    db.flush()
    write_audit_event(
        db,
        event_type="RECEIPT_GENERATED",
        classification=Classification.INTERNAL.value,
        trace_id=trace_id,
        actor_id=app.applicant_id,
        metadata={
            "receipt_id": receipt_id,
            "application_ref": app.application_id,
            "amount_paise": amount,
            "payment_ref": app.payment_ref,
        },
    )
    return record


def latest_receipt(db: Session, application_pk: str) -> ReceiptRecord | None:
    return (
        db.query(ReceiptRecord)
        .filter(ReceiptRecord.application_id == application_pk)
        .order_by(ReceiptRecord.created_at.desc())
        .first()
    )
