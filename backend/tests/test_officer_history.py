"""Officer history — completed actions from audit trail, not the active queue."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from app.api.deps import get_gateway
from app.boundary.gateway import DataBoundaryGateway
from app.core.config import get_settings
from app.core.database import get_db
from app.main import create_app
from app.services.catalogue import get_service
from app.services.documents import store_document
from app.services.journey import JourneyService
from app.services.officer import OfficerService
from app.services.state_machine import JourneyState, ProcessingStatus
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def journey(db_session: Session, gateway: DataBoundaryGateway) -> JourneyService:
    return JourneyService(db_session, gateway=gateway)


def _auth_to_form(journey: JourneyService, *, trace: str = "hist") -> tuple[str, str]:
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
        journey.handle_message(app_id, token, val, trace_id="hist-form")


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
            actor_id=app.applicant_id,
            trace_id="hist-doc",
            form_data=dict(app.form_data or {}),
            gateway=journey.gateway,
        )
    db.expire_all()
    journey.after_document_upload(app_id, token, trace_id="hist-doc")
    if journey._get_app_by_ref(app_id).current_state != JourneyState.REVIEW_CONFIRM.value:
        journey.handle_message(app_id, token, "DONE", trace_id="hist")
    journey.handle_message(app_id, token, "CONFIRM", trace_id="hist")
    journey.handle_message(app_id, token, "PAY", trace_id="hist")
    journey.handle_message(app_id, token, "PAY", trace_id="hist")
    assert (
        journey._get_app_by_ref(app_id).processing_status
        == ProcessingStatus.UNDER_REVIEW.value
    )


@pytest.mark.asyncio
async def test_approve_leaves_queue_and_appears_in_history(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey)
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)

    officer = OfficerService(db_session)
    assert any(q.application_id == app_id for q in officer.list_queue())

    issued = officer.approve(app_id, actor_id="officer", trace_id="hist-approve")
    assert issued.processing_status == ProcessingStatus.ISSUED.value
    db_session.commit()

    assert not any(q.application_id == app_id for q in officer.list_queue())

    history = officer.list_history()
    match = next((h for h in history if h.application_id == app_id), None)
    assert match is not None
    assert match.processing_status == ProcessingStatus.ISSUED.value
    assert match.last_action == "CERTIFICATE_ISSUED"
    assert match.last_action_label == "Approved and issued"
    assert match.service_display_name == "Income Certificate"
    assert match.action_at

    # Fresh service instance = new request/session semantics
    again = OfficerService(db_session).list_history()
    assert any(h.application_id == app_id for h in again)
    detail = OfficerService(db_session).get_application(app_id)
    assert detail.processing_status == ProcessingStatus.ISSUED.value


@pytest.mark.asyncio
async def test_rejected_and_escalated_appear_in_history(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_a, token_a = _auth_to_form(journey, trace="rej")
    await _submit_for_review(db_session, journey, app_a, token_a, tmp_path, monkeypatch)
    app_b, token_b = _auth_to_form(journey, trace="esc")
    await _submit_for_review(db_session, journey, app_b, token_b, tmp_path, monkeypatch)

    officer = OfficerService(db_session)
    officer.reject(app_a, reason="Incomplete", actor_id="officer", trace_id="rej")
    officer.escalate(app_b, reason="Needs senior", actor_id="officer", trace_id="esc")
    db_session.commit()

    history = {h.application_id: h for h in officer.list_history()}
    assert history[app_a].last_action == "OFFICER_REJECTED"
    assert history[app_a].processing_status == ProcessingStatus.REJECTED.value
    assert history[app_b].last_action == "OFFICER_ESCALATED"


@pytest.mark.asyncio
async def test_officer_history_http_auth_and_persistence(
    db_session: Session,
    journey: JourneyService,
    gateway: DataBoundaryGateway,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="api-hist")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    OfficerService(db_session).approve(app_id, actor_id="officer", trace_id="api-hist")
    db_session.commit()

    app = create_app()

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_gateway] = lambda: gateway
    client = TestClient(app)

    assert client.get("/api/v1/officer/history").status_code == 401

    headers = {"X-Officer-Token": get_settings().officer_api_token}
    hist = client.get("/api/v1/officer/history", headers=headers)
    assert hist.status_code == 200
    rows = hist.json()
    assert any(r["application_id"] == app_id for r in rows)
    row = next(r for r in rows if r["application_id"] == app_id)
    assert row["last_action_label"] == "Approved and issued"
    assert row["processing_status"] == "ISSUED"

    # Second request still returns the row
    hist2 = client.get("/api/v1/officer/history", headers=headers)
    assert any(r["application_id"] == app_id for r in hist2.json())

    detail = client.get(f"/api/v1/officer/{app_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["processing_status"] == "ISSUED"

    queue = client.get("/api/v1/officer/queue", headers=headers)
    assert queue.status_code == 200
    assert not any(r["application_id"] == app_id for r in queue.json())
