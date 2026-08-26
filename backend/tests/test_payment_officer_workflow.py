"""Payment, fee, receipt, and officer workflow tests."""



from __future__ import annotations

import io
from pathlib import Path

import pytest
from app.adapters.payment import MockPaymentProvider, PaymentOutcome
from app.api.deps import get_gateway
from app.boundary.gateway import DataBoundaryGateway
from app.boundary.providers import OptionalCloudProvider
from app.core.config import get_settings
from app.main import create_app
from app.models.application import PaymentRecord, ReceiptRecord
from app.models.audit import AuditEvent
from app.services.catalogue import get_service, get_service_catalogue
from app.services.documents import store_document
from app.services.journey import JourneyService
from app.services.officer import OfficerAuthError, OfficerService, require_officer
from app.services.state_machine import JourneyState, ProcessingStatus, can_transition
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.auth_helpers import submit_current_otp


@pytest.fixture
def journey(db_session: Session, gateway: DataBoundaryGateway) -> JourneyService:
    return JourneyService(db_session, gateway=gateway)


def _auth_to_form(journey: JourneyService, *, trace: str = "t") -> tuple[str, str]:
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


def test_mock_payment_outcomes():
    p = MockPaymentProvider()
    ok = p.charge(
        amount_paise=5000, currency="INR", application_ref="INC-1", scenario="PAY"
    )
    assert ok.outcome == PaymentOutcome.SUCCESS
    fail = p.charge(
        amount_paise=5000, currency="INR", application_ref="INC-1", scenario="FAIL"
    )
    assert fail.outcome == PaymentOutcome.FAILURE
    timed = p.charge(
        amount_paise=5000, currency="INR", application_ref="INC-1", scenario="TIMEOUT"
    )
    assert timed.outcome == PaymentOutcome.TIMEOUT


def test_fee_loaded_from_catalogue():
    get_service_catalogue.cache_clear()
    svc = get_service("INCOME_CERTIFICATE")
    assert svc.fee is not None
    assert svc.fee.amount_paise == 5000


def test_state_machine_payment_path():
    assert can_transition(JourneyState.REVIEW_CONFIRM, JourneyState.FEE_QUOTE)
    assert can_transition(JourneyState.FEE_QUOTE, JourneyState.PAYMENT)
    assert can_transition(JourneyState.PAYMENT, JourneyState.SUBMITTED)
    assert can_transition(JourneyState.PAYMENT, JourneyState.PAYMENT_FAILED)
    assert can_transition(JourneyState.PAYMENT_FAILED, JourneyState.PAYMENT)
    assert can_transition(JourneyState.SUBMITTED, JourneyState.CORRECTION)
    assert not can_transition(JourneyState.LANGUAGE_SELECT, JourneyState.FEE_QUOTE)


@pytest.mark.asyncio
async def test_payment_failure_then_success_and_receipt(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    app_id, token = _auth_to_form(journey, trace="pay")
    _fill_form(journey, app_id, token)
    await _upload_all(db_session, journey, app_id, token, tmp_path)
    app = journey._get_app_by_ref(app_id)
    if app.current_state != JourneyState.REVIEW_CONFIRM.value:
        journey.handle_message(app_id, token, "DONE", trace_id="pay")

    fee = journey.handle_message(app_id, token, "CONFIRM", trace_id="pay")
    assert fee.state == JourneyState.FEE_QUOTE.value
    assert fee.data["fee"]["amount_paise"] == 5000

    pay = journey.handle_message(app_id, token, "PAY", trace_id="pay")
    assert pay.state == JourneyState.PAYMENT.value

    failed = journey.handle_message(app_id, token, "FAIL", trace_id="pay")
    assert failed.state == JourneyState.PAYMENT_FAILED.value
    assert failed.error == "payment_failed"
    assert db_session.query(PaymentRecord).filter_by(outcome="FAILURE").count() == 1
    assert not journey._get_app_by_ref(app_id).payment_completed

    success = journey.handle_message(app_id, token, "PAY", trace_id="pay")
    assert success.state == JourneyState.SUBMITTED.value
    assert success.data.get("receipt_id")
    assert journey._get_app_by_ref(app_id).processing_status == ProcessingStatus.UNDER_REVIEW.value
    receipt = journey.get_receipt(app_id, token)
    assert "INC-" in (receipt.data.get("receipt") or "")
    assert db_session.query(ReceiptRecord).count() == 1


@pytest.mark.asyncio
async def test_fee_quote_cancel_returns_to_review_without_submit(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    app_id, token = _auth_to_form(journey, trace="cancel")
    _fill_form(journey, app_id, token)
    await _upload_all(db_session, journey, app_id, token, tmp_path)
    if journey._get_app_by_ref(app_id).current_state != JourneyState.REVIEW_CONFIRM.value:
        journey.handle_message(app_id, token, "DONE", trace_id="cancel")
    fee = journey.handle_message(app_id, token, "CONFIRM", trace_id="cancel")
    assert fee.state == JourneyState.FEE_QUOTE.value
    cancelled = journey.handle_message(app_id, token, "CANCEL", trace_id="cancel")
    assert cancelled.state == JourneyState.REVIEW_CONFIRM.value
    assert cancelled.data.get("review")
    assert journey._get_app_by_ref(app_id).processing_status != ProcessingStatus.UNDER_REVIEW.value
    assert not journey._get_app_by_ref(app_id).payment_completed


@pytest.mark.asyncio
async def test_payment_timeout_then_retry_success(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    app_id, token = _auth_to_form(journey, trace="to")
    _fill_form(journey, app_id, token)
    await _upload_all(db_session, journey, app_id, token, tmp_path)
    if journey._get_app_by_ref(app_id).current_state != JourneyState.REVIEW_CONFIRM.value:
        journey.handle_message(app_id, token, "DONE", trace_id="to")
    journey.handle_message(app_id, token, "CONFIRM", trace_id="to")
    journey.handle_message(app_id, token, "PAY", trace_id="to")
    timed = journey.handle_message(app_id, token, "TIMEOUT", trace_id="to")
    assert timed.state == JourneyState.PAYMENT_FAILED.value
    assert not journey._get_app_by_ref(app_id).payment_completed
    done = journey.handle_message(app_id, token, "PAY", trace_id="to")
    assert done.state == JourneyState.SUBMITTED.value
    assert journey._get_app_by_ref(app_id).payment_completed


@pytest.mark.asyncio
async def test_officer_rbac_and_actions(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    app_id, token = _auth_to_form(journey, trace="off")
    _fill_form(journey, app_id, token)
    await _upload_all(db_session, journey, app_id, token, tmp_path)
    if journey._get_app_by_ref(app_id).current_state != JourneyState.REVIEW_CONFIRM.value:
        journey.handle_message(app_id, token, "DONE", trace_id="off")
    journey.handle_message(app_id, token, "CONFIRM", trace_id="off")
    journey.handle_message(app_id, token, "PAY", trace_id="off")
    journey.handle_message(app_id, token, "PAY", trace_id="off")
    app = journey._get_app_by_ref(app_id)
    assert app.current_state == JourneyState.SUBMITTED.value

    with pytest.raises(OfficerAuthError):
        require_officer("wrong")
    require_officer(get_settings().officer_api_token)

    officer = OfficerService(db_session)
    queue = officer.list_queue()
    assert any(q.application_id == app_id for q in queue)

    corr = officer.request_correction(
        app_id,
        notes="Fix income",
        target_fields=["annual_income"],
        actor_id="officer",
        trace_id="off",
    )
    assert corr.processing_status == ProcessingStatus.NEEDS_CORRECTION.value
    assert journey._get_app_by_ref(app_id).current_state == JourneyState.FORM_CAPTURE.value
    assert "annual_income" not in (journey._get_app_by_ref(app_id).form_data or {})

    # Citizen sends the new value for the officer-targeted field, then resubmits.
    journey.handle_message(app_id, token, "175000", trace_id="off")
    assert journey._get_app_by_ref(app_id).current_state == JourneyState.REVIEW_CONFIRM.value
    resub = journey.handle_message(app_id, token, "CONFIRM", trace_id="off")
    assert resub.state == JourneyState.SUBMITTED.value
    assert journey._get_app_by_ref(app_id).processing_status == ProcessingStatus.UNDER_REVIEW.value

    issued = officer.approve(app_id, actor_id="officer", trace_id="off")
    assert issued.processing_status == ProcessingStatus.ISSUED.value

    events = {e.event_type for e in db_session.query(AuditEvent).all()}
    assert "OFFICER_REQUEST_CORRECTION" in events
    assert "OFFICER_APPROVED" in events
    assert "CERTIFICATE_ISSUED" in events
    assert "RECEIPT_GENERATED" in events


@pytest.mark.asyncio
async def test_officer_escalate_and_reject(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    app_id, token = _auth_to_form(journey, trace="esc")
    _fill_form(journey, app_id, token)
    await _upload_all(db_session, journey, app_id, token, tmp_path)
    if journey._get_app_by_ref(app_id).current_state != JourneyState.REVIEW_CONFIRM.value:
        journey.handle_message(app_id, token, "DONE", trace_id="esc")
    journey.handle_message(app_id, token, "CONFIRM", trace_id="esc")
    journey.handle_message(app_id, token, "PAY", trace_id="esc")
    journey.handle_message(app_id, token, "PAY", trace_id="esc")

    officer = OfficerService(db_session)
    esc = officer.escalate(app_id, reason="Complex case", actor_id="officer", trace_id="esc")
    assert esc.escalated is True
    # Reject another app
    app_id2, token2 = _auth_to_form(journey, trace="rej")
    _fill_form(journey, app_id2, token2)
    await _upload_all(db_session, journey, app_id2, token2, tmp_path)
    if journey._get_app_by_ref(app_id2).current_state != JourneyState.REVIEW_CONFIRM.value:
        journey.handle_message(app_id2, token2, "DONE", trace_id="rej")
    journey.handle_message(app_id2, token2, "CONFIRM", trace_id="rej")
    journey.handle_message(app_id2, token2, "PAY", trace_id="rej")
    journey.handle_message(app_id2, token2, "PAY", trace_id="rej")
    rej = officer.reject(app_id2, reason="Incomplete", actor_id="officer", trace_id="rej")
    assert rej.processing_status == ProcessingStatus.REJECTED.value


def test_citizen_cannot_call_officer_apis(db_session: Session, policy_path: Path):
    from app.boundary.policy import PolicyEngine
    from app.boundary.providers import LocalProvider
    from app.core.database import get_db

    app = create_app()

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_gateway] = lambda: DataBoundaryGateway(
        policy_engine=PolicyEngine(policy_path),
        local_provider=LocalProvider(),
        cloud_provider=OptionalCloudProvider(),
    )
    client = TestClient(app)
    # No officer token
    r = client.get("/api/v1/officer/queue")
    assert r.status_code == 401
    # Citizen session token must not work as officer token
    r2 = client.post(
        "/api/v1/officer/INC-FAKE/approve",
        headers={"X-Session-Token": "citizen-token", "X-Officer-Token": "wrong"},
    )
    assert r2.status_code == 401


def test_invalid_payment_transition_from_language(journey: JourneyService):
    start = journey.start(trace_id="badpay")
    app = journey._get_app_by_ref(start.application_id)
    session = journey._get_session(app, start.access_token)  # type: ignore[arg-type]
    from app.services.state_machine import InvalidTransitionError

    with pytest.raises(InvalidTransitionError):
        journey._transition(app, session, JourneyState.PAYMENT, trace_id="badpay")
