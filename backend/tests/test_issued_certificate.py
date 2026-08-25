"""Issued Income Certificate PDF — generation, persistence, officer/citizen access."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from app.api.deps import get_gateway
from app.boundary.gateway import DataBoundaryGateway
from app.core.config import get_settings
from app.core.database import get_db
from app.main import create_app
from app.models.application import DocumentRecord
from app.models.audit import AuditEvent
from app.services.catalogue import get_service
from app.services.certificate import (
    CertificateGenerationError,
    render_income_certificate_pdf,
)
from app.services.documents import ISSUED_CERTIFICATE_CODE, get_document, store_document
from app.services.journey import JourneyService
from app.services.officer import OfficerService
from app.services.state_machine import ProcessingStatus
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.auth_helpers import submit_current_otp


@pytest.fixture
def journey(db_session: Session, gateway: DataBoundaryGateway) -> JourneyService:
    return JourneyService(db_session, gateway=gateway)


def _auth_to_form(journey: JourneyService, *, trace: str = "cert") -> tuple[str, str]:
    start = journey.start(trace_id=trace)
    assert start.access_token
    app_id, token = start.application_id, start.access_token
    journey.handle_message(app_id, token, "en", trace_id=trace)
    journey.handle_message(app_id, token, "9876543210", trace_id=trace)
    submit_current_otp(journey, app_id, token, trace=trace)
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
        journey.handle_message(app_id, token, val, trace_id="cert-form")


async def _submit_for_review(
    db: Session,
    journey: JourneyService,
    app_id: str,
    token: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    _fill_form(journey, app_id, token)
    service = get_service("INCOME_CERTIFICATE")
    app = journey._get_app_by_ref(app_id)
    for doc in service.documents:
        upload = UploadFile(
            filename=f"{doc.code}_ok.pdf",
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
            trace_id="cert-doc",
            form_data=dict(app.form_data or {}),
            gateway=journey.gateway,
        )
    db.expire_all()
    journey.after_document_upload(app_id, token, trace_id="cert-doc")
    if journey._get_app_by_ref(app_id).current_state != "REVIEW_CONFIRM":
        journey.handle_message(app_id, token, "DONE", trace_id="cert")
    journey.handle_message(app_id, token, "CONFIRM", trace_id="cert")
    journey.handle_message(app_id, token, "PAY", trace_id="cert")
    journey.handle_message(app_id, token, "PAY", trace_id="cert")
    assert journey._get_app_by_ref(app_id).processing_status == ProcessingStatus.UNDER_REVIEW.value


def test_pdf_renderer_includes_application_data_and_disclaimer():
    class _App:
        application_id = "INC-4729"
        processing_status = "ISSUED"
        form_data = {
            "applicant_name": "Lakshmi Devi",
            "date_of_birth": "12/04/1995",
            "mobile_number": "9876543210",
            "address": "12 Temple Street",
            "district": "Hyderabad",
            "annual_income": 120000,
            "income_source": "Agriculture",
        }

    pdf = render_income_certificate_pdf(_App())  # type: ignore[arg-type]
    assert pdf.startswith(b"%PDF")
    assert b"%%EOF" in pdf
    assert b"INC-4729" in pdf
    assert b"Lakshmi Devi" in pdf
    assert b"12/04/1995" in pdf
    assert b"9876543210" in pdf
    assert b"12 Temple Street" in pdf
    assert b"Hyderabad" in pdf
    assert b"120000" in pdf
    assert b"Agriculture" in pdf
    assert b"DEMO / POC DOCUMENT" in pdf
    assert b"Not an official government certificate" in pdf
    assert b"access_token" not in pdf
    assert b"session token" not in pdf.lower()
    assert b"persona-" not in pdf


@pytest.mark.asyncio
async def test_approve_issues_one_readable_pdf(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey)
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    officer = OfficerService(db_session)
    issued = officer.approve(app_id, actor_id="officer", trace_id="cert-issue")
    db_session.commit()
    assert issued.processing_status == ProcessingStatus.ISSUED.value
    assert issued.issued_certificate
    assert issued.issued_certificate["available"] is True
    assert issued.issued_certificate["filename"] == f"income-certificate-{app_id}.pdf"
    assert "storage" not in str(issued.issued_certificate).lower()
    assert "doc_" not in str(issued.issued_certificate)

    app = journey._get_app_by_ref(app_id)
    certs = [
        d
        for d in db_session.query(DocumentRecord).filter(DocumentRecord.application_id == app.id)
        if d.document_code == ISSUED_CERTIFICATE_CODE
    ]
    assert len(certs) == 1
    pdf, filename = officer.get_issued_certificate_bytes(app_id)
    assert filename.endswith(".pdf")
    assert pdf.startswith(b"%PDF")
    assert app_id.encode() in pdf
    assert b"Lakshmi Devi" in pdf
    assert b"DEMO / POC DOCUMENT" in pdf
    assert token.encode() not in pdf

    history = officer.list_history()
    match = next(h for h in history if h.application_id == app_id)
    assert match.last_action == "CERTIFICATE_ISSUED"
    assert match.last_action_label == "Approved and issued"


@pytest.mark.asyncio
async def test_repeated_approve_does_not_duplicate_certificate(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="dup")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    officer = OfficerService(db_session)
    officer.approve(app_id, actor_id="officer", trace_id="dup-1")
    db_session.commit()
    app = journey._get_app_by_ref(app_id)
    rec = get_document(db_session, app.id, ISSUED_CERTIFICATE_CODE)
    assert rec
    key = rec.storage_key
    audits_before = (
        db_session.query(AuditEvent).filter(AuditEvent.event_type == "CERTIFICATE_ISSUED").count()
    )

    again = officer.approve(app_id, actor_id="officer", trace_id="dup-2")
    db_session.commit()
    assert again.processing_status == ProcessingStatus.ISSUED.value
    rec2 = get_document(db_session, app.id, ISSUED_CERTIFICATE_CODE)
    assert rec2
    assert rec2.storage_key == key
    certs = (
        db_session.query(DocumentRecord)
        .filter(
            DocumentRecord.application_id == app.id,
            DocumentRecord.document_code == ISSUED_CERTIFICATE_CODE,
        )
        .count()
    )
    assert certs == 1
    audits_after = (
        db_session.query(AuditEvent).filter(AuditEvent.event_type == "CERTIFICATE_ISSUED").count()
    )
    assert audits_after == audits_before


@pytest.mark.asyncio
async def test_failed_pdf_generation_does_not_issue(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="fail")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)

    def _boom(*_a, **_k):
        raise CertificateGenerationError("boom")

    monkeypatch.setattr("app.services.officer.render_income_certificate_pdf", _boom)
    officer = OfficerService(db_session)
    with pytest.raises(CertificateGenerationError):
        officer.approve(app_id, actor_id="officer", trace_id="fail")
    app = journey._get_app_by_ref(app_id)
    assert app.processing_status == ProcessingStatus.UNDER_REVIEW.value
    assert get_document(db_session, app.id, ISSUED_CERTIFICATE_CODE) is None


@pytest.mark.asyncio
async def test_officer_and_citizen_certificate_http_auth(
    db_session: Session,
    journey: JourneyService,
    gateway: DataBoundaryGateway,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="http")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    OfficerService(db_session).approve(app_id, actor_id="officer", trace_id="http")
    db_session.commit()

    other_id, other_token = _auth_to_form(journey, trace="http-b")
    db_session.commit()

    app = create_app()

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_gateway] = lambda: gateway
    client = TestClient(app)
    path = f"/api/v1/officer/{app_id}/documents/{ISSUED_CERTIFICATE_CODE}"

    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Officer-Token": "wrong"}).status_code == 401

    ok = client.get(path, headers={"X-Officer-Token": get_settings().officer_api_token})
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("application/pdf")
    assert ok.content.startswith(b"%PDF")
    assert app_id.encode() in ok.content
    assert b"storage" not in ok.content
    assert token.encode() not in ok.content

    other = client.get(
        f"/api/v1/officer/{other_id}/documents/{ISSUED_CERTIFICATE_CODE}",
        headers={"X-Officer-Token": get_settings().officer_api_token},
    )
    assert other.status_code == 404

    citizen = client.get(
        f"/api/v1/journey/{app_id}/documents/{ISSUED_CERTIFICATE_CODE}",
        headers={"X-Session-Token": token},
    )
    assert citizen.status_code == 200
    assert citizen.content.startswith(b"%PDF")

    wrong_session = client.get(
        f"/api/v1/journey/{app_id}/documents/{ISSUED_CERTIFICATE_CODE}",
        headers={"X-Session-Token": other_token},
    )
    assert wrong_session.status_code == 403

    cross = client.get(
        f"/api/v1/journey/{other_id}/documents/{ISSUED_CERTIFICATE_CODE}",
        headers={"X-Session-Token": token},
    )
    assert cross.status_code in {403, 404}


@pytest.mark.asyncio
async def test_reject_and_correction_unchanged_by_certificate(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="rej")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    officer = OfficerService(db_session)
    rej = officer.reject(app_id, reason="Incomplete", actor_id="officer", trace_id="rej")
    assert rej.processing_status == ProcessingStatus.REJECTED.value
    assert rej.issued_certificate is None
    rejected_pk = journey._get_app_by_ref(app_id).id
    assert get_document(db_session, rejected_pk, ISSUED_CERTIFICATE_CODE) is None

    app_b, token_b = _auth_to_form(journey, trace="corr")
    await _submit_for_review(db_session, journey, app_b, token_b, tmp_path, monkeypatch)
    corr = officer.request_correction(
        app_b,
        notes="Fix income",
        target_fields=["annual_income"],
        actor_id="officer",
        trace_id="corr",
    )
    assert corr.processing_status == ProcessingStatus.NEEDS_CORRECTION.value
    assert corr.issued_certificate is None
