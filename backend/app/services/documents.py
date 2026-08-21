"""Local document storage — metadata only in DB; files on local disk."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.boundary.classification import Classification
from app.core.config import get_settings
from app.models.application import DocumentRecord
from app.platform.audit import write_audit_event
from app.services.catalogue import DocumentDef


class DocumentValidationError(ValueError):
    pass


@dataclass
class StoredDocument:
    record: DocumentRecord
    storage_key: str


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
) -> StoredDocument:
    content = await upload.read()
    size = len(content)
    mime = (upload.content_type or "application/octet-stream").split(";")[0].strip()
    filename = upload.filename or "upload.bin"

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

    checksum = hashlib.sha256(content).hexdigest()
    storage_key = f"doc_{uuid4().hex}"
    dest = documents_root() / storage_key
    dest.write_bytes(content)

    # Upsert by application + document_code
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
            "mime_type": mime,
            "size_bytes": size,
            "checksum_sha256": checksum,
            "storage_key": storage_key,
            # never include original path or file bytes
        },
    )
    return StoredDocument(record=record, storage_key=storage_key)
