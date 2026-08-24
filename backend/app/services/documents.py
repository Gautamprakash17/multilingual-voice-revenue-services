"""Local document storage + mock OCR/verification — never cloud."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.adapters.documents import (
    get_doc_verify_provider,
    get_ocr_provider,
)
from app.boundary.classification import Classification
from app.boundary.gateway import DataBoundaryGateway, GatewayRequest
from app.core.config import get_settings
from app.models.application import DocumentRecord
from app.platform.audit import write_audit_event
from app.platform.metrics import get_metrics
from app.services.catalogue import DocumentDef


class DocumentValidationError(ValueError):
    pass


@dataclass
class StoredDocument:
    record: DocumentRecord
    storage_key: str
    verification_outcome: str | None = None


def documents_root() -> Path:
    settings = get_settings()
    root = Path(settings.document_storage_path)
    root.mkdir(parents=True, exist_ok=True)
    return root


async def store_document(
    db: Session,
    *,
    application_pk: str,
    document_def: DocumentDef,
    upload: UploadFile,
    actor_id: str | None,
    trace_id: str | None,
    form_data: dict[str, Any] | None = None,
    gateway: DataBoundaryGateway | None = None,
    document_type: str | None = None,
) -> StoredDocument:
    content = await upload.read()
    size = len(content)
    mime = (upload.content_type or "application/octet-stream").split(";")[0].strip()
    filename = upload.filename or "upload.bin"

    selected_type: str | None = None
    if document_def.accepted_types:
        if not document_type or not str(document_type).strip():
            raise DocumentValidationError(
                f"Document type is required for {document_def.code}"
            )
        match = document_def.accepted_type_by_code(str(document_type))
        if match is None:
            allowed = ", ".join(t.code for t in document_def.accepted_types)
            raise DocumentValidationError(
                f"Document type '{document_type}' is not accepted for "
                f"{document_def.code}. Allowed: {allowed}"
            )
        selected_type = match.code
    elif document_type and str(document_type).strip():
        selected_type = str(document_type).strip().upper()

    if mime not in document_def.allowed_mime_types:
        raise DocumentValidationError(
            f"MIME type '{mime}' not allowed for {document_def.code}. "
            f"Allowed: {', '.join(document_def.allowed_mime_types)}"
        )
    if size <= 0:
        raise DocumentValidationError("Empty file rejected")
    if size > document_def.max_size_bytes:
        raise DocumentValidationError(
            f"File exceeds max size of {document_def.max_size_bytes} bytes"
        )

    # Prove restricted bytes never leave local zone
    if gateway is not None:
        blocked = gateway.evaluate(
            GatewayRequest(
                payload={"keys": ["document_bytes"]},
                classification=Classification.RESTRICTED,
                destination="cloud",
                purpose="ocr",
                approved=False,
                trace_id=trace_id,
            ),
            db=db,
        )
        if blocked.allowed:
            raise RuntimeError("Boundary violation: document bytes allowed to cloud")

    checksum = hashlib.sha256(content).hexdigest()
    storage_key = f"doc_{uuid4().hex}"
    dest = documents_root() / storage_key
    dest.write_bytes(content)

    ocr = get_ocr_provider().extract(
        document_code=document_def.code,
        filename=filename,
        mime_type=mime,
        size_bytes=size,
        checksum_sha256=checksum,
    )
    verification = get_doc_verify_provider().verify(
        document_code=document_def.code,
        filename=filename,
        ocr=ocr,
        form_data=form_data or {},
    )
    get_metrics().record_doc_verification(verification.outcome.value)

    write_audit_event(
        db,
        event_type="DOCUMENT_VERIFIED",
        classification=Classification.RESTRICTED.value,
        trace_id=trace_id,
        actor_id=actor_id,
        metadata={
            "document_code": document_def.code,
            "document_type": selected_type,
            "outcome": verification.outcome.value,
            "ocr_provider": ocr.provider,
            "verify_provider": verification.provider,
            # never store extracted citizen field values
        },
    )

    type_note = f"document_type={selected_type}" if selected_type else None

    existing = (
        db.query(DocumentRecord)
        .filter(
            DocumentRecord.application_id == application_pk,
            DocumentRecord.document_code == document_def.code,
        )
        .one_or_none()
    )
    if existing:
        old_path = documents_root() / existing.storage_key
        if old_path.exists():
            old_path.unlink()
        existing.storage_key = storage_key
        existing.original_filename = filename
        existing.mime_type = mime
        existing.size_bytes = size
        existing.checksum_sha256 = checksum
        existing.classification = Classification.RESTRICTED.value
        existing.verification_status = verification.outcome.value
        existing.verification_reason = verification.reason
        existing.ocr_provider = ocr.provider
        if type_note:
            existing.notes = type_note
        record = existing
    else:
        record = DocumentRecord(
            application_id=application_pk,
            document_code=document_def.code,
            storage_key=storage_key,
            original_filename=filename,
            mime_type=mime,
            size_bytes=size,
            checksum_sha256=checksum,
            classification=Classification.RESTRICTED.value,
            verification_status=verification.outcome.value,
            verification_reason=verification.reason,
            ocr_provider=ocr.provider,
            notes=type_note,
        )
        db.add(record)

    db.flush()
    write_audit_event(
        db,
        event_type="DOCUMENT_UPLOADED",
        classification=Classification.RESTRICTED.value,
        trace_id=trace_id,
        actor_id=actor_id,
        metadata={
            "document_code": document_def.code,
            "document_type": selected_type,
            "mime_type": mime,
            "size_bytes": size,
            "checksum_sha256": checksum,
            "storage_key": storage_key,
            "verification_status": verification.outcome.value,
        },
    )

    return StoredDocument(
        record=record,
        storage_key=storage_key,
        verification_outcome=verification.outcome.value,
    )
