"""Journey integration tests — Income Certificate."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from app.adapters.identity import MockIdentityProvider, Persona, get_identity_provider
from app.boundary.classification import Classification
from app.boundary.gateway import DataBoundaryGateway, GatewayRequest
from app.boundary.providers import OptionalCloudProvider
from app.models.audit import AuditEvent
from app.services.application_ids import generate_application_id
from app.services.catalogue import get_service
from app.services.documents import DocumentValidationError, store_document
from app.services.journey import JourneyService
from app.services.state_machine import InvalidTransitionError, JourneyState
from app.services.validation import validate_field
from fastapi import UploadFile
from sqlalchemy.orm import Session


@pytest.fixture
def identity() -> MockIdentityProvider:
    return MockIdentityProvider(
        [
            Persona(
                id="persona-lakshmi",
                name="Lakshmi Devi",
                mobile="9876543210",
                otp="123456",
            )
        ]
    )


@pytest.fixture
def journey(
    db_session: Session,
    identity: MockIdentityProvider,
    gateway: DataBoundaryGateway,
) -> JourneyService:
    return JourneyService(db_session, identity=identity, gateway=gateway)


def _auth_to_form(journey: JourneyService, trace: str = "t-1"):
    start = journey.start(trace_id=trace)
    token = start.access_token
    assert token
    app_id = start.application_id
    journey.handle_message(app_id, token, "en", trace_id=trace)
    journey.handle_message(app_id, token, "9876543210", trace_id=trace)
    journey.handle_message(app_id, token, "123456", trace_id=trace)
    journey.record_consent(app_id, token, granted=True, trace_id=trace)
    journey.handle_message(app_id, token, "INCOME_CERTIFICATE", trace_id=trace)
    return app_id, token


def _fill_form(journey: JourneyService, app_id: str, token: str, *, income: str = "120000"):
    values = [
        "Lakshmi Devi",
        "12/04/1995",
        "9876543210",
        "12 Temple Street",
        "Hyderabad",
        income,
        "Agriculture",
    ]
    replies = []
    for value in values:
        replies.append(journey.handle_message(app_id, token, value, trace_id="form"))
    return replies


async def _upload_all(
    db: Session, journey: JourneyService, app_id: str, token: str, tmp_path: Path
):
    service = get_service("INCOME_CERTIFICATE")
    app = journey._get_app_by_ref(app_id)
    for doc in service.documents:
        content = b"%PDF-1.4 synthetic " + doc.code.encode()
        upload = UploadFile(
            filename=f"{doc.code.lower()}.pdf",
            file=io.BytesIO(content),
            headers={"content-type": "application/pdf"},
        )
        # Patch documents root via settings would be better; write via store_document
        await store_document(
            db,
            application_pk=app.id,
            document_def=doc,
            upload=upload,
            actor_id=app.applicant_id,
            trace_id="doc",
        )
        db.refresh(app)
    return journey.after_document_upload(app_id, token, trace_id="doc")


def test_application_creation_and_unique_ids(db_session: Session, journey: JourneyService):
    a = journey.start(trace_id="create-1")
    b = journey.start(trace_id="create-2")
    assert a.application_id.startswith("INC-")
    assert b.application_id.startswith("INC-")
    assert a.application_id != b.application_id
    assert a.access_token != b.access_token
    ids = {generate_application_id(db_session) for _ in range(5)}
    assert len(ids) == 5


def test_mock_otp_success_and_failure(journey: JourneyService):
    start = journey.start(trace_id="auth")
    app_id, token = start.application_id, start.access_token
    assert token
    journey.handle_message(app_id, token, "en", trace_id="auth")
    journey.handle_message(app_id, token, "9876543210", trace_id="auth")
    fail = journey.handle_message(app_id, token, "000000", trace_id="auth")
    assert fail.error == "invalid_otp"
    ok = journey.handle_message(app_id, token, "123456", trace_id="auth")
    assert ok.state == JourneyState.CONSENT.value


def test_consent_required_before_data_capture(journey: JourneyService):
    start = journey.start(trace_id="consent")
    app_id, token = start.application_id, start.access_token
    assert token
    journey.handle_message(app_id, token, "en", trace_id="consent")
    journey.handle_message(app_id, token, "9876543210", trace_id="consent")
    journey.handle_message(app_id, token, "123456", trace_id="consent")
    # Decline consent
    declined = journey.record_consent(app_id, token, granted=False, trace_id="consent")
    assert declined.error == "consent_declined"
    assert declined.state == JourneyState.CONSENT.value


def test_language_select_accepts_natural_spoken_names(journey: JourneyService):
    for spoken, code in [("English", "en"), ("Hindi", "hi"), ("Kannada", "kn")]:
        start = journey.start(trace_id="lang-voice")
        token = start.access_token
        assert token
        reply = journey.handle_message(start.application_id, token, spoken, trace_id="lang-voice")
        assert reply.error != "invalid_language"
        assert reply.state == JourneyState.AUTHENTICATE.value
        app = journey._get_app_by_ref(start.application_id)
        assert app.language == code


def test_invalid_and_valid_form_values(journey: JourneyService):
    app_id, token = _auth_to_form(journey)
    # applicant_name min_length 2 — single character must fail
    bad = journey.handle_message(app_id, token, "X", trace_id="val")
    assert bad.error == "validation_failed"
    good = journey.handle_message(app_id, token, "Lakshmi Devi", trace_id="val")
    assert good.error is None
    assert good.data.get("next_field") == "date_of_birth"
    # Empty / whitespace DOB must not be saved
    empty_dob = journey.handle_message(app_id, token, "   ", trace_id="val")
    assert empty_dob.error == "validation_failed"
    assert "required" in (empty_dob.message or "").lower()
    assert journey._get_app_by_ref(app_id).form_data.get("date_of_birth") is None
    bad_date = journey.handle_message(app_id, token, "99/99/9999", trace_id="val")
    assert bad_date.error == "validation_failed"
    journey.handle_message(app_id, token, "12/04/1995", trace_id="val")
    assert journey._get_app_by_ref(app_id).form_data.get("date_of_birth") == "12/04/1995"


def test_empty_required_fields_rejected_from_catalogue(journey: JourneyService):
    """Backend remains source of truth for required catalog fields."""
    app_id, token = _auth_to_form(journey)
    service = get_service("INCOME_CERTIFICATE")
    for field in service.fields:
        if not field.required:
            continue
        # Reach this field
        while True:
            app = journey._get_app_by_ref(app_id)
            missing = [
                name
                for name in service.required_field_names()
                if name not in (app.form_data or {})
            ]
            if not missing or missing[0] == field.name:
                break
            # Fill prior fields with minimal valid values
            prior = service.field_by_name(missing[0])
            assert prior is not None
            sample = {
                "string": "Sample value",
                "date": "12/04/1995",
                "mobile": "9876543210",
                "number": "120000",
            }.get(prior.type, "Sample")
            journey.handle_message(app_id, token, sample, trace_id="req-empty")
        empty = journey.handle_message(app_id, token, "", trace_id="req-empty")
        assert empty.error == "validation_failed", field.name
        assert field.name not in (journey._get_app_by_ref(app_id).form_data or {})
        # Valid value so the next required field can be tested
        sample = {
            "string": "Sample value ok",
            "date": "12/04/1995",
            "mobile": "9876543210",
            "number": "120000",
        }.get(field.type, "Sample value ok")
        ok = journey.handle_message(app_id, token, sample, trace_id="req-empty")
        assert ok.error != "validation_failed", field.name


def test_all_required_fields_captured_moves_to_documents(journey: JourneyService):
    app_id, token = _auth_to_form(journey)
    replies = _fill_form(journey, app_id, token)
    assert replies[-1].state == JourneyState.DOCUMENT_CAPTURE.value
    assert "IDENTITY_PROOF" in replies[-1].data.get("missing_documents", [])


def test_validation_helpers_from_catalogue():
    service = get_service("INCOME_CERTIFICATE")
    income = service.field_by_name("annual_income")
    assert income is not None
    assert validate_field(income, "-1").ok is False
    assert validate_field(income, "0").ok is True
    assert validate_field(income, "250000").value == 250000

    mobile = service.field_by_name("mobile_number")
    assert mobile is not None
    assert validate_field(mobile, "9876543210").value == "9876543210"
    assert validate_field(mobile, "07204609155").value == "7204609155"
    assert validate_field(mobile, "09876543210").value == "9876543210"
    bad = validate_field(mobile, "01234567890")
    assert bad.ok is False
    assert "10-digit" in (bad.error or "").lower()
    unknown_ok = validate_field(mobile, "9123456789")
    assert unknown_ok.ok is True
    assert unknown_ok.value == "9123456789"


def test_form_capture_leading_zero_mobile_and_no_field_regression(journey: JourneyService):
    app_id, token = _auth_to_form(journey)
    journey.handle_message(app_id, token, "Gautam Prakash", trace_id="m")
    journey.handle_message(app_id, token, "12/08/2000", trace_id="m")
    bad = journey.handle_message(app_id, token, "12345", trace_id="m")
    assert bad.error == "validation_failed"
    assert bad.data.get("field") == "mobile_number"
    assert journey._get_app_by_ref(app_id).form_data.get("applicant_name") == "Gautam Prakash"
    assert "mobile_number" not in (journey._get_app_by_ref(app_id).form_data or {})

    ok = journey.handle_message(app_id, token, "07204609155", trace_id="m")
    assert ok.error != "validation_failed"
    assert journey._get_app_by_ref(app_id).form_data.get("mobile_number") == "7204609155"
    assert ok.data.get("next_field") == "address"
    assert journey._get_app_by_ref(app_id).form_data.get("applicant_name") == "Gautam Prakash"


@pytest.mark.asyncio
async def test_document_mime_rejection_checksum_and_classification(
    db_session: Session, journey: JourneyService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DOCUMENT_STORAGE_PATH", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )

    app_id, token = _auth_to_form(journey)
    _fill_form(journey, app_id, token)
    service = get_service("INCOME_CERTIFICATE")
    doc = service.document_by_code("IDENTITY_PROOF")
    assert doc
    app = journey._get_app_by_ref(app_id)

    bad = UploadFile(
        filename="evil.exe",
        file=io.BytesIO(b"MZ"),
        headers={"content-type": "application/x-msdownload"},
    )
    with pytest.raises(DocumentValidationError):
        await store_document(
            db_session,
            application_pk=app.id,
            document_def=doc,
            upload=bad,
            actor_id=app.applicant_id,
            trace_id="mime",
        )

    content = b"%PDF-1.4 hello"
    good = UploadFile(
        filename="id.pdf",
        file=io.BytesIO(content),
        headers={"content-type": "application/pdf"},
    )
    stored = await store_document(
        db_session,
        application_pk=app.id,
        document_def=doc,
        upload=good,
        actor_id=app.applicant_id,
        trace_id="ok",
    )
    assert stored.record.classification == Classification.RESTRICTED.value
    assert len(stored.record.checksum_sha256) == 64
    assert stored.storage_key.startswith("doc_")
    assert "/" not in stored.storage_key  # no raw filesystem path exposed as key


@pytest.mark.asyncio
async def test_correction_review_submission_and_audit(
    db_session: Session,
    journey: JourneyService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cloud_provider: OptionalCloudProvider,
):
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    app_id, token = _auth_to_form(journey, trace="full")
    _fill_form(journey, app_id, token, income="100000")
    await _upload_all(db_session, journey, app_id, token, tmp_path)
    review = journey.handle_message(app_id, token, "DONE", trace_id="full")
    # may already be in REVIEW after uploads
    if review.state != JourneyState.REVIEW_CONFIRM.value:
        # after_document_upload already moved to review
        status = journey.get_status(app_id, token)
        assert status.state in {
            JourneyState.REVIEW_CONFIRM.value,
            JourneyState.DOCUMENT_CAPTURE.value,
        }
        if status.state == JourneyState.DOCUMENT_CAPTURE.value:
            review = journey.handle_message(app_id, token, "DONE", trace_id="full")
    # Ensure review
    app = journey._get_app_by_ref(app_id)
    if app.current_state != JourneyState.REVIEW_CONFIRM.value:
        # force via after upload path
        reply = journey.after_document_upload(app_id, token, trace_id="full")
        assert reply.state == JourneyState.REVIEW_CONFIRM.value

    corr = journey.handle_message(app_id, token, "CORRECT", trace_id="full")
    assert corr.state == JourneyState.CORRECTION.value
    journey.handle_message(app_id, token, "annual_income", trace_id="full")
    journey.handle_message(app_id, token, "150000", trace_id="full")
    app = journey._get_app_by_ref(app_id)
    assert app.form_data["annual_income"] == 150000
    assert app.current_state == JourneyState.REVIEW_CONFIRM.value

    submitted = journey.handle_message(app_id, token, "CONFIRM", trace_id="full")
    assert submitted.state == JourneyState.FEE_QUOTE.value
    pay_start = journey.handle_message(app_id, token, "PAY", trace_id="full")
    assert pay_start.state == JourneyState.PAYMENT.value
    submitted = journey.handle_message(app_id, token, "PAY", trace_id="full")
    assert submitted.state == JourneyState.SUBMITTED.value
    assert submitted.application_id.startswith("INC-")
    assert submitted.data.get("receipt_id")

    events = db_session.query(AuditEvent).all()
    types = {e.event_type for e in events}
    for required in {
        "JOURNEY_STARTED",
        "LANGUAGE_SELECTED",
        "AUTH_REQUESTED",
        "AUTH_SUCCESS",
        "CONSENT_GRANTED",
        "SERVICE_SELECTED",
        "FIELD_CAPTURED",
        "DOCUMENT_UPLOADED",
        "CORRECTION_REQUESTED",
        "PAYMENT_ATTEMPT",
        "APPLICATION_SUBMITTED",
        "RECEIPT_GENERATED",
    }:
        assert required in types, f"missing {required}"

    # Audit must not contain restricted payload values / OTP
    blob = " ".join(str(e.metadata_json) for e in events)
    assert "123456" not in blob
    assert "Temple Street" not in blob
    assert "Lakshmi Devi" not in blob
    assert cloud_provider.call_count == 0


def test_applicant_cannot_access_another_application(journey: JourneyService):
    a = journey.start(trace_id="iso")
    b = journey.start(trace_id="iso")
    assert a.access_token and b.access_token
    try:
        journey.get_status(a.application_id, b.access_token)
        raise AssertionError("expected PermissionError")
    except PermissionError:
        pass


def test_no_cloud_provider_called_for_restricted_journey(
    journey: JourneyService, cloud_provider: OptionalCloudProvider, gateway: DataBoundaryGateway
):
    start = journey.start(trace_id="cloud")
    assert start.application_id
    # Direct gateway check
    result = gateway.evaluate(
        GatewayRequest(
            payload={"citizen": "x"},
            classification=Classification.RESTRICTED,
            destination="cloud",
            purpose="stt",
        )
    )
    assert result.allowed is False
    assert cloud_provider.call_count == 0


def test_seeded_identity_provider_loads():
    provider = get_identity_provider()
    persona = provider.find_by_mobile("9876543210")
    assert persona is not None
    assert persona.name == "Lakshmi Devi"
    assert not hasattr(persona, "language")
    assert provider.verify_otp("9876543210", "123456").success is True


def test_session_language_independent_of_persona(journey: JourneyService):
    """Language is selected for the application; auth must not overwrite it."""
    start = journey.start(trace_id="lang-indep")
    token = start.access_token
    assert token
    app_id = start.application_id
    journey.handle_message(app_id, token, "en", trace_id="lang-indep")
    journey.handle_message(app_id, token, "9876543210", trace_id="lang-indep")
    reply = journey.handle_message(app_id, token, "123456", trace_id="lang-indep")
    assert reply.state == JourneyState.CONSENT.value
    assert journey._get_app_by_ref(app_id).language == "en"
    assert journey._get_app_by_ref(app_id).applicant_id == "persona-lakshmi"


def test_invalid_transition_during_journey_raises(journey: JourneyService):
    start = journey.start(trace_id="bad")
    app = journey._get_app_by_ref(start.application_id)
    session = journey._get_session(app, start.access_token)  # type: ignore[arg-type]
    try:
        journey._transition(app, session, JourneyState.SUBMITTED, trace_id="bad")
        raise AssertionError("expected InvalidTransitionError")
    except InvalidTransitionError:
        pass
