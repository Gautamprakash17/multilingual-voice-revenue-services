"""Document verification workflow tests — local mock OCR/verify (POC).

Outcomes are filename-marker based; form_data is not content-matched.
"""


from __future__ import annotations

import io
from pathlib import Path

import pytest
from app.adapters.documents import (
    MockDocumentVerificationProvider,
    MockOCRProvider,
    VerificationOutcome,
)
from app.boundary.classification import Classification
from app.boundary.gateway import DataBoundaryGateway, GatewayRequest
from app.boundary.providers import OptionalCloudProvider
from app.services.catalogue import get_service
from app.services.documents import store_document
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
from fastapi import UploadFile
from sqlalchemy.orm import Session


@pytest.fixture
def journey(db_session: Session, gateway: DataBoundaryGateway) -> JourneyService:
    return JourneyService(db_session, gateway=gateway)


def _auth_to_form(journey: JourneyService, *, trace: str = "t") -> tuple[str, str]:
    start = journey.start(trace_id=trace)
    assert start.access_token
    app_id, token = start.application_id, start.access_token
    journey.handle_message(app_id, token, "en", trace_id=trace)
    journey.handle_message(app_id, token, "9876543210", trace_id=trace)
    journey.handle_message(app_id, token, "123456", trace_id=trace)
    journey.record_consent(app_id, token, granted=True, trace_id=trace)
    journey.handle_message(app_id, token, "INCOME_CERTIFICATE", trace_id=trace)
    return app_id, token


def _fill_form(journey: JourneyService, app_id: str, token: str) -> None:
    for val in [
        "Lakshmi Devi",
        "12/04/1995",
        "9876543210",
        "12 Temple Street",
        "Hyderabad",
        "120000",
        "Agriculture",
    ]:
        journey.handle_message(app_id, token, val, trace_id="form")


async def _upload_all(
    db: Session,
    journey: JourneyService,
    app_id: str,
    token: str,
    tmp_path: Path,
    *,
    filename_suffix: str = "ok.pdf",
) -> None:
    service = get_service("INCOME_CERTIFICATE")
    app = journey._get_app_by_ref(app_id)
    for doc in service.documents:
        upload = UploadFile(
            filename=f"{doc.code}_{filename_suffix}",
            file=io.BytesIO(b"%PDF-1.4 ok"),
            headers={"content-type": "application/pdf"},
        )
        await store_document(
            db,
            application_pk=app.id,
            document_def=doc,
            upload=upload,
            document_type=(doc.accepted_types[0].code if doc.accepted_types else None),
            actor_id=app.applicant_id,
            trace_id="doc",
            form_data=dict(app.form_data or {}),
            gateway=journey.gateway,
        )
    db.expire_all()
    journey.after_document_upload(app_id, token, trace_id="doc")


def test_mock_ocr_and_verification_outcomes():
    """POC semantics: filename markers only — form_data is not content-matched."""
    ocr = MockOCRProvider()
    verify = MockDocumentVerificationProvider()
    ok = ocr.extract(
        document_code="IDENTITY_PROOF",
        filename="id_ok.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        checksum_sha256="abc",
    )
    assert ok.success
    verified = verify.verify(
        document_code="IDENTITY_PROOF",
        filename="id_ok.pdf",
        ocr=ok,
        form_data={"applicant_name": "Someone Else"},
    )
    assert verified.outcome == VerificationOutcome.VERIFIED
    assert verified.reason == "Local POC verification passed."
    assert "metadata" not in verified.reason.lower()
    assert "application" not in verified.reason.lower()

    bad = ocr.extract(
        document_code="IDENTITY_PROOF",
        filename="id_mismatch.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        checksum_sha256="abc",
    )
    mismatched = verify.verify(
        document_code="IDENTITY_PROOF",
        filename="id_mismatch.pdf",
        ocr=bad,
        form_data={"applicant_name": "Lakshmi Devi"},
    )
    assert mismatched.outcome == VerificationOutcome.MISMATCH
    assert "Local POC" in mismatched.reason
    assert "application fields" not in mismatched.reason.lower()

    unread = ocr.extract(
        document_code="IDENTITY_PROOF",
        filename="id_unreadable.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        checksum_sha256="abc",
    )
    assert not unread.success
    unreadable = verify.verify(
        document_code="IDENTITY_PROOF",
        filename="id_unreadable.pdf",
        ocr=unread,
        form_data={},
    )
    assert unreadable.outcome == VerificationOutcome.UNREADABLE
    assert "Local POC" in unreadable.reason


@pytest.mark.asyncio
async def test_document_unreadable_recovery(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    app_id, token = _auth_to_form(journey, trace="unreadable")
    _fill_form(journey, app_id, token)
    service = get_service("INCOME_CERTIFICATE")
    app = journey._get_app_by_ref(app_id)
    doc = service.documents[0]
    upload = UploadFile(
        filename="IDENTITY_PROOF_unreadable.pdf",
        file=io.BytesIO(b"%PDF-1.4 bad"),
        headers={"content-type": "application/pdf"},
    )
    stored = await store_document(
        db_session,
        application_pk=app.id,
        document_def=doc,
        upload=upload,
            document_type=(doc.accepted_types[0].code if doc.accepted_types else None),
        actor_id=app.applicant_id,
        trace_id="unreadable",
        form_data=dict(app.form_data or {}),
        gateway=journey.gateway,
    )
    assert stored.verification_outcome == "UNREADABLE"
    assert stored.record.verification_reason == (
        "Local POC verification failed: document unreadable."
    )
    reply = journey.after_document_upload(app_id, token, trace_id="unreadable")
    assert reply.state == JourneyState.DOCUMENT_REJECTED.value
    assert reply.data.get("recovery") == "RETRY"
    journey.handle_message(app_id, token, "RETRY", trace_id="unreadable")
    upload2 = UploadFile(
        filename="IDENTITY_PROOF_ok.pdf",
        file=io.BytesIO(b"%PDF-1.4 good"),
        headers={"content-type": "application/pdf"},
    )
    await store_document(
        db_session,
        application_pk=app.id,
        document_def=doc,
        upload=upload2,
            document_type=(doc.accepted_types[0].code if doc.accepted_types else None),
        actor_id=app.applicant_id,
        trace_id="unreadable",
        form_data=dict(app.form_data or {}),
        gateway=journey.gateway,
    )
    db_session.expire_all()
    ok = journey.after_document_upload(app_id, token, trace_id="unreadable")
    assert ok.state in {
        JourneyState.DOCUMENT_CAPTURE.value,
        JourneyState.REVIEW_CONFIRM.value,
    }
    assert (
        journey._get_app_by_ref(app_id).documents[0].verification_status == "VERIFIED"
    )


@pytest.mark.asyncio
async def test_document_mismatch_recovery(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    app_id, token = _auth_to_form(journey)
    _fill_form(journey, app_id, token)
    service = get_service("INCOME_CERTIFICATE")
    app = journey._get_app_by_ref(app_id)
    doc = service.documents[0]
    upload = UploadFile(
        filename="IDENTITY_PROOF_mismatch.pdf",
        file=io.BytesIO(b"%PDF-1.4 bad"),
        headers={"content-type": "application/pdf"},
    )
    stored = await store_document(
        db_session,
        application_pk=app.id,
        document_def=doc,
        upload=upload,
            document_type=(doc.accepted_types[0].code if doc.accepted_types else None),
        actor_id=app.applicant_id,
        trace_id="mm",
        form_data=dict(app.form_data or {}),
        gateway=journey.gateway,
    )
    assert stored.verification_outcome == "MISMATCH"
    assert stored.record.verification_reason == (
        "Local POC verification failed: details do not match."
    )
    reply = journey.after_document_upload(app_id, token, trace_id="mm")
    assert reply.state == JourneyState.DOCUMENT_REJECTED.value
    assert reply.data.get("recovery") == "RETRY"
    # Recapture with good file
    journey.handle_message(app_id, token, "RETRY", trace_id="mm")
    upload2 = UploadFile(
        filename="IDENTITY_PROOF_ok.pdf",
        file=io.BytesIO(b"%PDF-1.4 good"),
        headers={"content-type": "application/pdf"},
    )
    await store_document(
        db_session,
        application_pk=app.id,
        document_def=doc,
        upload=upload2,
            document_type=(doc.accepted_types[0].code if doc.accepted_types else None),
        actor_id=app.applicant_id,
        trace_id="mm",
        form_data=dict(app.form_data or {}),
        gateway=journey.gateway,
    )
    db_session.expire_all()
    ok = journey.after_document_upload(app_id, token, trace_id="mm")
    assert ok.state in {
        JourneyState.DOCUMENT_CAPTURE.value,
        JourneyState.REVIEW_CONFIRM.value,
    }


@pytest.mark.asyncio
async def test_restricted_document_never_reaches_cloud(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cloud_provider: OptionalCloudProvider,
    gateway: DataBoundaryGateway,
):
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    app_id, token = _auth_to_form(journey, trace="bound")
    _fill_form(journey, app_id, token)
    service = get_service("INCOME_CERTIFICATE")
    app = journey._get_app_by_ref(app_id)
    upload = UploadFile(
        filename="IDENTITY_PROOF.pdf",
        file=io.BytesIO(b"%PDF-1.4 secret-bytes"),
        headers={"content-type": "application/pdf"},
    )
    await store_document(
        db_session,
        application_pk=app.id,
        document_def=service.documents[0],
        upload=upload,
        document_type=(
            service.documents[0].accepted_types[0].code
            if service.documents[0].accepted_types
            else None
        ),
        actor_id=app.applicant_id,
        trace_id="bound",
        form_data=dict(app.form_data or {}),
        gateway=gateway,
    )
    app = journey._get_app_by_ref(app_id)
    db_session.refresh(app)
    assert app.documents[0].verification_status == "VERIFIED"
    assert app.documents[0].verification_reason == "Local POC verification passed."
    blocked = gateway.evaluate(
        GatewayRequest(
            payload={"document_bytes": "x"},
            classification=Classification.RESTRICTED,
            destination="cloud",
            purpose="ocr",
        ),
        db=db_session,
    )
    assert blocked.allowed is False
    assert cloud_provider.call_count == 0


