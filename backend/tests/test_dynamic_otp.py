"""Dynamic OTP, existing/new citizen login, and mock SMS inbox tests."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from app.adapters.identity import MockIdentityProvider, Persona, get_identity_provider
from app.adapters.otp import generate_otp_code, hash_otp
from app.core.database import get_db
from app.core.security import redact_sensitive
from app.main import create_app
from app.models.identity import SyntheticCitizen
from app.platform.logging import JsonFormatter
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
from app.speech.digits import normalize_spoken_otp
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.auth_helpers import (
    HI_DIGIT_WORDS,
    KN_DIGIT_WORDS,
    complete_auth,
    current_otp,
    spaced_otp,
    words_otp,
)


@pytest.fixture
def identity() -> MockIdentityProvider:
    return MockIdentityProvider(
        [Persona(id="persona-lakshmi", name="Lakshmi Devi", mobile="9876543210")]
    )


@pytest.fixture
def journey(db_session: Session, identity: MockIdentityProvider, gateway) -> JourneyService:
    return JourneyService(db_session, identity=identity, gateway=gateway)


def test_existing_synthetic_citizen_can_authenticate(
    journey: JourneyService, identity: MockIdentityProvider
):
    start = journey.start(trace_id="exist")
    token = start.access_token
    assert token
    reply = complete_auth(journey, start.application_id, token)
    assert reply.state == JourneyState.CONSENT.value
    assert reply.error is None
    app = journey._get_app_by_ref(start.application_id)
    assert app.applicant_id == "persona-lakshmi"


def test_unknown_valid_mobile_enters_registration_flow(journey: JourneyService):
    start = journey.start(trace_id="reg-offer")
    token = start.access_token
    assert token
    journey.handle_message(start.application_id, token, "en", trace_id="reg-offer")
    reply = journey.handle_message(
        start.application_id, token, "7012345678", trace_id="reg-offer"
    )
    assert reply.state == JourneyState.AUTHENTICATE.value
    assert reply.data.get("auth_step") == "register_offer"
    assert reply.data.get("citizen_kind") == "new"
    assert reply.data.get("otp_issued") is not True
    assert "register" in (reply.message or "").lower() or "account" in (reply.message or "").lower()


def test_new_citizen_registration_succeeds(
    journey: JourneyService, identity: MockIdentityProvider
):
    start = journey.start(trace_id="reg")
    token = start.access_token
    assert token
    app_id = start.application_id
    journey.handle_message(app_id, token, "en", trace_id="reg")
    journey.handle_message(app_id, token, "7012345678", trace_id="reg")
    offer = journey.handle_message(app_id, token, "REGISTER", trace_id="reg")
    assert offer.data.get("otp_issued") is True
    otp = current_otp(identity, "7012345678")
    named = journey.handle_message(app_id, token, otp, trace_id="reg")
    assert named.data.get("auth_step") == "register_name"
    done = journey.handle_message(app_id, token, "Kiran Rao", trace_id="reg")
    assert done.state == JourneyState.CONSENT.value
    assert "Registration successful" in (done.message or "")
    persona = identity.find_by_mobile("7012345678")
    assert persona is not None
    assert persona.name == "Kiran Rao"


def test_newly_registered_citizen_authenticates_again_as_existing(
    journey: JourneyService, identity: MockIdentityProvider, db_session: Session
):
    start = journey.start(trace_id="reg1")
    token = start.access_token
    assert token
    app_id = start.application_id
    journey.handle_message(app_id, token, "en", trace_id="reg1")
    journey.handle_message(app_id, token, "7012345678", trace_id="reg1")
    journey.handle_message(app_id, token, "YES", trace_id="reg1")
    journey.handle_message(app_id, token, current_otp(identity, "7012345678"), trace_id="reg1")
    journey.handle_message(app_id, token, "Kiran Rao", trace_id="reg1")
    assert db_session.query(SyntheticCitizen).filter_by(mobile="7012345678").one()

    start2 = journey.start(trace_id="reg2")
    token2 = start2.access_token
    assert token2
    journey.handle_message(start2.application_id, token2, "en", trace_id="reg2")
    otp_prompt = journey.handle_message(
        start2.application_id, token2, "7012345678", trace_id="reg2"
    )
    assert otp_prompt.data.get("citizen_kind") == "existing"
    assert otp_prompt.data.get("auth_step") == "otp"
    ok = journey.handle_message(
        start2.application_id,
        token2,
        current_otp(identity, "7012345678"),
        trace_id="reg2",
    )
    assert ok.state == JourneyState.CONSENT.value
    assert "Authenticated" in (ok.message or "")


def test_otp_is_exactly_six_digits_and_may_have_leading_zero():
    codes = {generate_otp_code() for _ in range(40)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    identity = MockIdentityProvider(
        [Persona(id="p", name="A", mobile="9876543210")],
        generate_otp=lambda: "041927",
    )
    identity.request_otp("9876543210")
    sms = identity.get_demo_sms("9876543210")
    assert sms is not None
    assert sms.code == "041927"
    assert identity.verify_otp("9876543210", "041927").success is True


def test_otp_challenges_are_independent():
    identity = MockIdentityProvider(
        [
            Persona(id="a", name="A", mobile="9876543210"),
            Persona(id="b", name="B", mobile="9123456780"),
        ]
    )
    identity.request_otp("9876543210")
    identity.request_otp("9123456780")
    first = current_otp(identity, "9876543210")
    second = current_otp(identity, "9123456780")
    assert identity.verify_otp("9876543210", second).success is False
    assert identity.verify_otp("9876543210", first).success is True
    assert identity.verify_otp("9123456780", second).success is True


def test_new_otp_invalidates_old_otp():
    identity = MockIdentityProvider(
        [Persona(id="p", name="A", mobile="9876543210")]
    )
    identity.request_otp("9876543210")
    old = current_otp(identity, "9876543210")
    identity.request_otp("9876543210")
    new = current_otp(identity, "9876543210")
    assert identity.verify_otp("9876543210", old).success is False
    assert identity.verify_otp("9876543210", new).success is True


def test_correct_otp_authenticates_wrong_otp_rejected(
    journey: JourneyService, identity: MockIdentityProvider
):
    start = journey.start(trace_id="otp")
    token = start.access_token
    assert token
    app_id = start.application_id
    journey.handle_message(app_id, token, "en", trace_id="otp")
    issued = journey.handle_message(app_id, token, "9876543210", trace_id="otp")
    assert issued.data.get("otp_issued") is True
    otp = current_otp(identity)
    assert otp not in (issued.message or "")
    assert otp not in (issued.prompt or "")
    fail = journey.handle_message(
        app_id, token, "000000" if otp != "000000" else "111111", trace_id="otp"
    )
    assert fail.error == "invalid_otp"
    assert fail.state == JourneyState.AUTHENTICATE.value
    assert "incorrect" in (fail.message or "").lower()
    ok = journey.handle_message(app_id, token, otp, trace_id="otp")
    assert ok.state == JourneyState.CONSENT.value


def test_expired_otp_is_rejected():
    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    identity = MockIdentityProvider(
        [Persona(id="p", name="A", mobile="9876543210")],
        otp_ttl_seconds=300,
        now=lambda: clock["now"],
    )
    identity.request_otp("9876543210")
    otp = current_otp(identity)
    clock["now"] = clock["now"] + timedelta(minutes=6)
    result = identity.verify_otp("9876543210", otp)
    assert result.success is False
    assert result.reason == "otp_expired"


def test_max_failed_attempts_invalidate_otp():
    identity = MockIdentityProvider(
        [Persona(id="p", name="A", mobile="9876543210")],
        otp_max_attempts=3,
    )
    identity.request_otp("9876543210")
    otp = current_otp(identity)
    wrong = "000000" if otp != "000000" else "111111"
    assert identity.verify_otp("9876543210", wrong).reason == "invalid_otp"
    assert identity.verify_otp("9876543210", wrong).reason == "invalid_otp"
    locked = identity.verify_otp("9876543210", wrong)
    assert locked.reason == "otp_max_attempts"
    assert identity.verify_otp("9876543210", otp).success is False


def test_otp_not_in_normal_api_response(
    identity: MockIdentityProvider, db_session: Session, gateway
):
    journey = JourneyService(db_session, identity=identity, gateway=gateway)
    start = journey.start(trace_id="api")
    token = start.access_token
    assert token
    journey.handle_message(start.application_id, token, "en", trace_id="api")
    reply = journey.handle_message(start.application_id, token, "9876543210", trace_id="api")
    otp = current_otp(identity)
    blob = f"{reply.message}|{reply.prompt}|{reply.data}|{reply.error}"
    assert otp not in blob


def test_otp_not_written_to_normal_logs(identity: MockIdentityProvider):
    identity.request_otp("9876543210")
    otp = current_otp(identity)
    payload = redact_sensitive({"otp": otp, "mobile_last4": "3210"})
    assert payload["otp"] == "[REDACTED]"
    assert otp not in str(payload)
    logger = logging.getLogger("otp-log-test")
    logger.addHandler(logging.NullHandler())
    logger.info("auth requested", extra={"extra_fields": {"mobile_last4": "3210"}})


def test_voice_digit_normalization_and_indic_otp(
    journey: JourneyService, identity: MockIdentityProvider
):
    start = journey.start(trace_id="voice-otp")
    token = start.access_token
    assert token
    app_id = start.application_id
    journey.handle_message(app_id, token, "en", trace_id="voice-otp")
    journey.handle_message(app_id, token, "9876543210", trace_id="voice-otp")
    otp = current_otp(identity)
    assert normalize_spoken_otp(spaced_otp(otp)) == otp
    ok = journey.handle_message(app_id, token, spaced_otp(otp), trace_id="voice-otp")
    assert ok.state == JourneyState.CONSENT.value

    start_hi = journey.start(trace_id="hi-otp")
    token_hi = start_hi.access_token
    assert token_hi
    journey.handle_message(start_hi.application_id, token_hi, "hi", trace_id="hi-otp")
    journey.handle_message(start_hi.application_id, token_hi, "9876543210", trace_id="hi-otp")
    otp_hi = current_otp(identity)
    spoken_hi = words_otp(otp_hi, HI_DIGIT_WORDS)
    assert normalize_spoken_otp(spoken_hi) == otp_hi
    hi_ok = journey.handle_message(
        start_hi.application_id, token_hi, spoken_hi, trace_id="hi-otp"
    )
    assert hi_ok.state == JourneyState.CONSENT.value

    start_kn = journey.start(trace_id="kn-otp")
    token_kn = start_kn.access_token
    assert token_kn
    journey.handle_message(start_kn.application_id, token_kn, "kn", trace_id="kn-otp")
    journey.handle_message(start_kn.application_id, token_kn, "9876543210", trace_id="kn-otp")
    otp_kn = current_otp(identity)
    spoken_kn = words_otp(otp_kn, KN_DIGIT_WORDS)
    assert normalize_spoken_otp(spoken_kn) == otp_kn
    kn_ok = journey.handle_message(
        start_kn.application_id, token_kn, spoken_kn, trace_id="kn-otp"
    )
    assert kn_ok.state == JourneyState.CONSENT.value


def test_consent_flow_unchanged_after_dynamic_otp(journey: JourneyService):
    start = journey.start(trace_id="consent")
    token = start.access_token
    assert token
    complete_auth(journey, start.application_id, token)
    declined = journey.record_consent(
        start.application_id, token, granted=False, trace_id="consent"
    )
    assert declined.error == "consent_declined"
    assert declined.state == JourneyState.CONSENT.value
    granted = journey.record_consent(
        start.application_id, token, granted=True, trace_id="consent"
    )
    assert granted.state == JourneyState.SERVICE_SELECT.value


def test_seeded_personas_still_work_without_yaml_otp():
    get_identity_provider.cache_clear()
    provider = get_identity_provider()
    for mobile, name in (
        ("9876543210", "Lakshmi Devi"),
        ("9123456780", "Ramesh Kumar"),
        ("9988776655", "Anita Sharma"),
        ("7204609155", "Gautam Prakash"),
    ):
        persona = provider.find_by_mobile(mobile)
        assert persona is not None
        assert persona.name == name
        provider.request_otp(mobile)
        otp = current_otp(provider, mobile)  # type: ignore[arg-type]
        assert provider.verify_otp(mobile, otp).success is True
    get_identity_provider.cache_clear()


def test_demo_sms_endpoint_returns_code_only_on_inbox(db_session: Session, gateway):
    get_identity_provider.cache_clear()
    provider = get_identity_provider()
    journey = JourneyService(db_session, identity=provider, gateway=gateway)
    start = journey.start(trace_id="demo-api")
    token = start.access_token
    assert token
    app_id = start.application_id
    from app.api.deps import get_gateway

    app = create_app()

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_gateway] = lambda: gateway
    client = TestClient(app)
    headers = {"X-Session-Token": token}
    hidden = client.get(f"/api/v1/demo/sms?application_id={app_id}", headers=headers)
    assert hidden.status_code == 200
    assert hidden.json()["active"] is False

    journey.handle_message(app_id, token, "en", trace_id="demo-api")
    issued = journey.handle_message(app_id, token, "9876543210", trace_id="demo-api")
    otp = current_otp(provider, "9876543210")  # type: ignore[arg-type]
    assert otp not in (issued.message or "")
    db_session.commit()

    inbox = client.get(f"/api/v1/demo/sms?application_id={app_id}", headers=headers)
    assert inbox.status_code == 200
    sms = inbox.json()
    assert sms["active"] is True
    assert sms["code"] == otp
    assert sms["label"] == "Synthetic demo OTP"
    get_identity_provider.cache_clear()


def test_otp_hash_is_not_plaintext():
    digest = hash_otp("583214", "salt")
    assert digest != "583214"
    assert "583214" not in digest


def test_json_formatter_redacts_otp():
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "auth", (), None
    )
    record.extra_fields = {"otp": "041927", "path": "/api/v1/health"}
    line = JsonFormatter().format(record)
    assert "041927" not in line
    assert "[REDACTED]" in line
