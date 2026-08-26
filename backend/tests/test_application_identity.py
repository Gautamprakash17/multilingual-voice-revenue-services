"""One citizen journey = one persistent Application ID across Web / WhatsApp / IVR."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.api.deps import get_gateway
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.core.database import get_db
from app.main import create_app
from app.models.application import Application, ConversationSession
from app.nlu.provider import LocalRuleNLUProvider
from app.services.application_ids import normalize_application_id
from app.services.catalogue import get_service
from app.services.documents import store_document
from app.services.journey import JourneyService
from app.services.officer import OfficerService
from app.services.state_machine import JourneyState, ProcessingStatus
from app.speech.stt import MockSTTProvider
from app.speech.tts import MockTTSProvider
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.auth_helpers import expand_step

_FORM = [
    "Lakshmi Devi",
    "12/04/1995",
    "9876543210",
    "12 Temple Street",
    "Hyderabad",
    "120000",
    "Agriculture",
]


@pytest.fixture
def identity() -> MockIdentityProvider:
    return MockIdentityProvider(
        [Persona(id="persona-lakshmi", name="Lakshmi Devi", mobile="9876543210")]
    )


@pytest.fixture
def orch(
    db_session: Session,
    identity: MockIdentityProvider,
    gateway: DataBoundaryGateway,
) -> ChannelOrchestrator:
    journey = JourneyService(db_session, identity=identity, gateway=gateway)
    return ChannelOrchestrator(
        db_session,
        gateway=gateway,
        journey=journey,
        stt=MockSTTProvider(),
        tts=MockTTSProvider(),
        nlu=LocalRuleNLUProvider(),
    )


def _send(orch: ChannelOrchestrator, channel: str, app_id: str, token: str, text: str):
    return orch.process_channel_payload(
        channel,
        {"application_id": app_id, "access_token": token, "text": text},
    )


def _app_count(db: Session) -> int:
    return db.query(Application).count()


def _session_count(db: Session, app_pk: str) -> int:
    return (
        db.query(ConversationSession).filter(ConversationSession.application_id == app_pk).count()
    )


def _start_to_form(orch: ChannelOrchestrator, channel: str) -> tuple[str, str]:
    start = orch.start(channel=channel)
    token = start.access_token
    assert token
    app_id = start.application_id
    _send(orch, channel, app_id, token, "en")
    _send(orch, channel, app_id, token, "9876543210")
    _send(orch, channel, app_id, token, expand_step(orch.journey.identity, "123456"))
    orch.journey.record_consent(app_id, token, granted=True, trace_id="id")
    _send(orch, channel, app_id, token, "INCOME_CERTIFICATE")
    return app_id, token


async def _upload_docs_and_submit(
    db: Session,
    orch: ChannelOrchestrator,
    app_id: str,
    token: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    journey = orch.journey
    for val in _FORM:
        journey.handle_message(app_id, token, val, trace_id="id-form")
    service = get_service("INCOME_CERTIFICATE")
    app = journey._get_app_by_ref(app_id)
    for doc in service.documents:
        upload = UploadFile(
            filename=f"{doc.code}.pdf",
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
            trace_id="id-doc",
            form_data=dict(app.form_data or {}),
            gateway=journey.gateway,
        )
    db.expire_all()
    journey.after_document_upload(app_id, token, trace_id="id-doc")
    if journey._get_app_by_ref(app_id).current_state != JourneyState.REVIEW_CONFIRM.value:
        journey.handle_message(app_id, token, "DONE", trace_id="id")
    journey.handle_message(app_id, token, "CONFIRM", trace_id="id")
    journey.handle_message(app_id, token, "PAY", trace_id="id")
    journey.handle_message(app_id, token, "PAY", trace_id="id")
    assert journey._get_app_by_ref(app_id).processing_status == ProcessingStatus.UNDER_REVIEW.value


@pytest.mark.parametrize("channel", ["web", "whatsapp", "ivr"])
def test_channel_start_persists_one_application(
    orch: ChannelOrchestrator, db_session: Session, channel: str
):
    start = orch.start(channel=channel)
    assert start.application_id.startswith("INC-")
    assert start.access_token
    app = orch.journey._get_app_by_ref(start.application_id)
    assert app.processing_status == ProcessingStatus.DRAFT.value
    assert app.current_state == JourneyState.LANGUAGE_SELECT.value
    sessions = (
        db_session.query(ConversationSession)
        .filter(ConversationSession.application_id == app.id)
        .all()
    )
    assert len(sessions) == 1
    assert sessions[0].channel == channel
    assert _app_count(db_session) == 1


def test_repeated_channel_messages_do_not_create_applications(
    orch: ChannelOrchestrator, db_session: Session
):
    app_id, token = _start_to_form(orch, "whatsapp")
    before = _app_count(db_session)
    pk = orch.journey._get_app_by_ref(app_id).id
    sessions_before = _session_count(db_session, pk)
    _send(orch, "whatsapp", app_id, token, "Lakshmi Devi")
    _send(orch, "whatsapp", app_id, token, "12/04/1995")
    assert _app_count(db_session) == before == 1
    assert _session_count(db_session, pk) == sessions_before
    assert orch.journey._get_app_by_ref(app_id).form_data.get("applicant_name") == ("Lakshmi Devi")


def test_new_start_creates_a_new_application_id(orch: ChannelOrchestrator, db_session: Session):
    a = orch.start(channel="web")
    b = orch.start(channel="whatsapp")
    assert a.application_id != b.application_id
    assert _app_count(db_session) == 2


def test_resume_keeps_same_application_and_state(orch: ChannelOrchestrator, db_session: Session):
    app_id, token = _start_to_form(orch, "web")
    _send(orch, "web", app_id, token, "Lakshmi Devi")
    app = orch.journey._get_app_by_ref(app_id)
    pk = app.id
    captured = dict(app.form_data or {})
    state = app.current_state

    resumed = orch.resume(
        application_id=app_id, access_token=token, channel="whatsapp", trace_id="r"
    )
    assert resumed.application_id == app_id
    assert resumed.access_token != token
    assert _app_count(db_session) == 1
    after = orch.journey._get_app_by_ref(app_id)
    assert after.id == pk
    assert after.current_state == state
    assert dict(after.form_data or {}) == captured
    assert _session_count(db_session, pk) == 2

    cont = _send(orch, "whatsapp", app_id, resumed.access_token, "12/04/1995")
    assert cont.application_id == app_id
    assert _app_count(db_session) == 1
    assert orch.journey._get_app_by_ref(app_id).form_data.get("date_of_birth") == ("12/04/1995")


def test_ivr_resume_does_not_create_another_application(
    orch: ChannelOrchestrator, db_session: Session
):
    start = orch.start(channel="ivr")
    token = start.access_token
    assert token
    app_id = start.application_id
    _send(orch, "ivr", app_id, token, "en")
    resumed = orch.resume(
        application_id=app_id, access_token=token, channel="whatsapp", trace_id="ivr-r"
    )
    assert resumed.application_id == app_id
    assert _app_count(db_session) == 1
    channels = {
        s.channel
        for s in db_session.query(ConversationSession)
        .filter(ConversationSession.application_id == orch.journey._get_app_by_ref(app_id).id)
        .all()
    }
    assert channels == {"ivr", "whatsapp"}


def test_resume_rejects_missing_and_wrong_token(
    orch: ChannelOrchestrator, db_session: Session, gateway: DataBoundaryGateway
):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    db_session.commit()

    app = create_app()

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_gateway] = lambda: gateway
    client = TestClient(app)

    missing = client.post(
        "/api/v1/channels/resume",
        json={"application_id": app_id, "channel": "whatsapp"},
    )
    assert missing.status_code == 401
    assert _app_count(db_session) == 1

    denied = client.post(
        "/api/v1/channels/resume",
        json={"application_id": app_id, "channel": "whatsapp"},
        headers={"X-Session-Token": "not-the-session-token"},
    )
    assert denied.status_code == 403
    assert _app_count(db_session) == 1

    unknown = client.post(
        "/api/v1/channels/resume",
        json={"application_id": "INC-0000", "channel": "whatsapp"},
        headers={"X-Session-Token": token},
    )
    assert unknown.status_code == 404
    assert _app_count(db_session) == 1


def test_normalize_application_id_does_not_invent():
    assert normalize_application_id(" inc-4729 ") == "INC-4729"
    assert normalize_application_id("") == ""


@pytest.mark.asyncio
async def test_whatsapp_submitted_application_in_officer_queue_and_history(
    db_session: Session,
    orch: ChannelOrchestrator,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _start_to_form(orch, "whatsapp")
    await _upload_docs_and_submit(db_session, orch, app_id, token, tmp_path, monkeypatch)
    officer = OfficerService(db_session)
    queue = officer.list_queue()
    assert any(q.application_id == app_id for q in queue)
    row = next(q for q in queue if q.application_id == app_id)
    assert row.channel == "whatsapp"
    detail = officer.get_application(app_id)
    assert detail.application_id == app_id
    assert detail.processing_status == ProcessingStatus.UNDER_REVIEW.value
    assert detail.channel == "whatsapp"

    issued = officer.approve(app_id, actor_id="officer", trace_id="wa-appr")
    db_session.commit()
    assert issued.processing_status == ProcessingStatus.ISSUED.value
    assert not any(q.application_id == app_id for q in officer.list_queue())
    history = officer.list_history()
    match = next(h for h in history if h.application_id == app_id)
    assert match.last_action == "CERTIFICATE_ISSUED"


@pytest.mark.asyncio
async def test_ivr_submitted_application_in_officer_queue_detail_and_history(
    db_session: Session,
    orch: ChannelOrchestrator,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _start_to_form(orch, "ivr")
    resumed = orch.resume(
        application_id=app_id, access_token=token, channel="whatsapp", trace_id="ivr-wa"
    )
    assert resumed.access_token
    await _upload_docs_and_submit(
        db_session, orch, app_id, resumed.access_token, tmp_path, monkeypatch
    )
    officer = OfficerService(db_session)
    assert any(q.application_id == app_id for q in officer.list_queue())
    detail = officer.get_application(app_id.lower())
    assert detail.application_id == app_id
    assert detail.processing_status == ProcessingStatus.UNDER_REVIEW.value
    sessions = {
        s.channel
        for s in db_session.query(ConversationSession)
        .filter(ConversationSession.application_id == orch.journey._get_app_by_ref(app_id).id)
        .all()
    }
    assert "ivr" in sessions

    officer.approve(app_id, actor_id="officer", trace_id="ivr-appr")
    db_session.commit()
    history = {h.application_id: h for h in officer.list_history()}
    assert history[app_id].last_action == "CERTIFICATE_ISSUED"


@pytest.mark.asyncio
async def test_rejected_channel_application_appears_in_history(
    db_session: Session,
    orch: ChannelOrchestrator,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    app_id, token = _start_to_form(orch, "whatsapp")
    await _upload_docs_and_submit(db_session, orch, app_id, token, tmp_path, monkeypatch)
    officer = OfficerService(db_session)
    officer.reject(app_id, reason="Incomplete", actor_id="officer", trace_id="wa-rej")
    db_session.commit()
    history = {h.application_id: h for h in officer.list_history()}
    assert history[app_id].last_action == "OFFICER_REJECTED"
    assert history[app_id].processing_status == ProcessingStatus.REJECTED.value
    assert not any(q.application_id == app_id for q in officer.list_queue())


def test_draft_channel_application_is_in_officer_queue(
    orch: ChannelOrchestrator, db_session: Session
):
    start = orch.start(channel="ivr")
    officer = OfficerService(db_session)
    queue = officer.list_queue()
    assert any(q.application_id == start.application_id for q in queue)
    row = next(q for q in queue if q.application_id == start.application_id)
    assert row.processing_status == ProcessingStatus.DRAFT.value
    assert row.channel == "ivr"
    detail = officer.get_application(start.application_id)
    assert detail.processing_status == ProcessingStatus.DRAFT.value
    assert detail.channel == "ivr"
