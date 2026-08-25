"""Citizen application status notifications — simulated local delivery."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from app.api.deps import get_gateway
from app.boundary.gateway import DataBoundaryGateway
from app.core.database import get_db
from app.main import create_app
from app.models.notification import CitizenNotification
from app.services.catalogue import get_service
from app.services.documents import store_document
from app.services.journey import JourneyService
from app.services.notifications import (
    ISSUED,
    NEEDS_CORRECTION,
    REJECTED,
    SUBMITTED,
    UNDER_REVIEW,
    NotificationService,
)
from app.services.officer import OfficerService
from app.services.state_machine import ProcessingStatus
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.auth_helpers import submit_current_otp


@pytest.fixture
def journey(db_session: Session, gateway: DataBoundaryGateway) -> JourneyService:
    return JourneyService(db_session, gateway=gateway)


def _auth_to_form(
    journey: JourneyService, *, trace: str = "n", channel: str = "web"
) -> tuple[str, str]:
    start = journey.start(channel=channel, trace_id=trace)
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
        journey.handle_message(app_id, token, val, trace_id="n-form")


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
            trace_id="n-doc",
            form_data=dict(app.form_data or {}),
            gateway=journey.gateway,
        )
    db.expire_all()
    journey.after_document_upload(app_id, token, trace_id="n-doc")
    if journey._get_app_by_ref(app_id).current_state != "REVIEW_CONFIRM":
        journey.handle_message(app_id, token, "DONE", trace_id="n")
    journey.handle_message(app_id, token, "CONFIRM", trace_id="n")
    journey.handle_message(app_id, token, "PAY", trace_id="n")
    journey.handle_message(app_id, token, "PAY", trace_id="n")
    assert journey._get_app_by_ref(app_id).processing_status == ProcessingStatus.UNDER_REVIEW.value


def _events(db: Session, app_pk: str) -> list[str]:
    rows = (
        db.query(CitizenNotification)
        .filter(CitizenNotification.application_id == app_pk)
        .order_by(CitizenNotification.created_at.asc())
        .all()
    )
    return [r.event_type for r in rows]


def _dump_public(items: list[dict]) -> str:
    return json.dumps(items, default=str)


@pytest.mark.asyncio
async def test_submit_creates_submitted_and_under_review(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey)
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    app = journey._get_app_by_ref(app_id)
    assert _events(db_session, app.id) == [SUBMITTED, UNDER_REVIEW]
    items = NotificationService(db_session).list_for_application(app)
    assert items[0]["application_id"] == app_id
    assert "Income Certificate" in items[0]["message"]
    assert app_id in items[0]["message"]
    assert items[0]["delivery_status"] == "simulated"
    assert "sms" in items[0]["channels"]
    assert "whatsapp" in items[0]["channels"]
    assert "email" not in items[0]["channels"]
    assert items[0]["has_email"] is False
    assert items[0]["recipient_mobile_last4"] == "3210"


@pytest.mark.asyncio
async def test_needs_correction_issued_and_rejected_notifications(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="corr")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    officer = OfficerService(db_session)
    officer.request_correction(
        app_id,
        notes="Fix income",
        target_fields=["annual_income"],
        actor_id="officer",
        trace_id="corr",
    )
    app = journey._get_app_by_ref(app_id)
    assert _events(db_session, app.id)[-1] == NEEDS_CORRECTION
    corr_msg = (
        db_session.query(CitizenNotification)
        .filter(CitizenNotification.event_type == NEEDS_CORRECTION)
        .one()
        .message
    )
    assert app_id in corr_msg
    assert "Action required" in corr_msg
    assert "Fix income" not in corr_msg

    journey.handle_message(app_id, token, "annual_income", trace_id="corr")
    journey.handle_message(app_id, token, "175000", trace_id="corr")
    journey.handle_message(app_id, token, "CONFIRM", trace_id="corr")
    app = journey._get_app_by_ref(app_id)
    types = _events(db_session, app.id)
    assert types.count(SUBMITTED) == 2
    assert types.count(UNDER_REVIEW) == 2
    assert types.count(NEEDS_CORRECTION) == 1

    officer.approve(app_id, actor_id="officer", trace_id="corr")
    app = journey._get_app_by_ref(app_id)
    assert _events(db_session, app.id)[-1] == ISSUED
    issued = NotificationService(db_session).list_for_application(app)[-1]
    assert issued["certificate_available"] is True
    assert "approved and issued" in issued["message"]

    other, other_token = _auth_to_form(journey, trace="rej")
    await _submit_for_review(db_session, journey, other, other_token, tmp_path, monkeypatch)
    officer.reject(other, reason="Incomplete", actor_id="officer", trace_id="rej")
    other_app = journey._get_app_by_ref(other)
    assert _events(db_session, other_app.id)[-1] == REJECTED
    assert other in NotificationService(db_session).list_for_application(other_app)[-1]["message"]


@pytest.mark.asyncio
async def test_repeat_and_refresh_do_not_duplicate(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="dup")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    app = journey._get_app_by_ref(app_id)
    svc = NotificationService(db_session)
    svc.notify_submission(app)
    svc.notify_status(app, UNDER_REVIEW)
    svc.notify_status(app, SUBMITTED)
    assert _events(db_session, app.id) == [SUBMITTED, UNDER_REVIEW]

    officer = OfficerService(db_session)
    officer.approve(app_id, actor_id="officer", trace_id="dup")
    officer.approve(app_id, actor_id="officer", trace_id="dup-2")
    officer.get_application(app_id)
    officer.list_queue()
    assert _events(db_session, app.id).count(ISSUED) == 1


@pytest.mark.asyncio
async def test_whatsapp_and_ivr_use_same_application_id(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    wa_id, wa_token = _auth_to_form(journey, trace="wa", channel="whatsapp")
    await _submit_for_review(db_session, journey, wa_id, wa_token, tmp_path, monkeypatch)
    wa_app = journey._get_app_by_ref(wa_id)
    for item in NotificationService(db_session).list_for_application(wa_app):
        assert item["application_id"] == wa_id

    ivr_id, ivr_token = _auth_to_form(journey, trace="ivr", channel="ivr")
    await _submit_for_review(db_session, journey, ivr_id, ivr_token, tmp_path, monkeypatch)
    ivr_app = journey._get_app_by_ref(ivr_id)
    for item in NotificationService(db_session).list_for_application(ivr_app):
        assert item["application_id"] == ivr_id
    assert wa_id != ivr_id


@pytest.mark.asyncio
async def test_notification_survives_new_session_and_has_no_secrets(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="persist")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    OfficerService(db_session).approve(app_id, actor_id="officer", trace_id="persist")
    db_session.commit()
    app = journey._get_app_by_ref(app_id)
    pk = app.id
    db_session.expire_all()
    rows = (
        db_session.query(CitizenNotification)
        .filter(CitizenNotification.application_id == pk)
        .all()
    )
    assert {r.event_type for r in rows} >= {SUBMITTED, UNDER_REVIEW, ISSUED}
    public = NotificationService(db_session).list_for_application(app)
    blob = _dump_public(public) + "".join(r.message for r in rows)
    assert token not in blob
    assert "X-Session-Token" not in blob
    assert "access_token" not in blob
    assert "storage_key" not in blob
    assert "/data/documents" not in blob
    assert "doc_" not in blob
    assert app.id not in blob


@pytest.mark.asyncio
async def test_missing_email_does_not_invent_destination(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="email")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    app = journey._get_app_by_ref(app_id)
    row = (
        db_session.query(CitizenNotification)
        .filter(CitizenNotification.application_id == app.id)
        .first()
    )
    assert row is not None
    assert row.recipient_email is None
    assert "email" not in (row.channels or [])


@pytest.mark.asyncio
async def test_email_used_only_when_present(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="em2")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    app = journey._get_app_by_ref(app_id)
    data = dict(app.form_data or {})
    data["email"] = "citizen@example.test"
    app.form_data = data
    db_session.query(CitizenNotification).filter(
        CitizenNotification.application_id == app.id
    ).delete()
    db_session.flush()
    NotificationService(db_session).notify_submission(app)
    row = (
        db_session.query(CitizenNotification)
        .filter(CitizenNotification.application_id == app.id)
        .first()
    )
    assert row is not None
    assert row.recipient_email == "citizen@example.test"
    assert "email" in (row.channels or [])


@pytest.mark.asyncio
async def test_inbox_http_requires_session_and_certificate_stays_authorized(
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
    inbox = f"/api/v1/demo/notifications?application_id={app_id}"
    assert client.get(inbox).status_code == 401
    assert client.get(inbox, headers={"X-Session-Token": other_token}).status_code == 403
    ok = client.get(inbox, headers={"X-Session-Token": token})
    assert ok.status_code == 200
    body = ok.json()
    assert body["simulated"] is True
    types = [n["event_type"] for n in body["notifications"]]
    assert SUBMITTED in types
    assert UNDER_REVIEW in types
    assert ISSUED in types
    dumped = json.dumps(body)
    assert token not in dumped
    assert "storage_key" not in dumped

    cert = client.get(
        f"/api/v1/journey/{app_id}/documents/ISSUED_CERTIFICATE",
        headers={"X-Session-Token": token},
    )
    assert cert.status_code == 200
    assert cert.content.startswith(b"%PDF")
    denied = client.get(
        f"/api/v1/journey/{app_id}/documents/ISSUED_CERTIFICATE",
        headers={"X-Session-Token": other_token},
    )
    assert denied.status_code == 403
    assert (
        client.get(f"/api/v1/journey/{app_id}/documents/ISSUED_CERTIFICATE").status_code == 401
    )


@pytest.mark.asyncio
async def test_officer_actions_still_work(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _auth_to_form(journey, trace="off")
    await _submit_for_review(db_session, journey, app_id, token, tmp_path, monkeypatch)
    officer = OfficerService(db_session)
    assert officer.list_queue()
    corr = officer.request_correction(
        app_id,
        notes="Fix income",
        target_fields=["annual_income"],
        actor_id="officer",
        trace_id="off",
    )
    assert corr.processing_status == ProcessingStatus.NEEDS_CORRECTION.value
    journey.handle_message(app_id, token, "annual_income", trace_id="off")
    journey.handle_message(app_id, token, "175000", trace_id="off")
    journey.handle_message(app_id, token, "CONFIRM", trace_id="off")
    issued = officer.approve(app_id, actor_id="officer", trace_id="off")
    assert issued.processing_status == ProcessingStatus.ISSUED.value

    other, other_token = _auth_to_form(journey, trace="off-r")
    await _submit_for_review(db_session, journey, other, other_token, tmp_path, monkeypatch)
    rej = officer.reject(other, reason="Incomplete", actor_id="officer", trace_id="off-r")
    assert rej.processing_status == ProcessingStatus.REJECTED.value
