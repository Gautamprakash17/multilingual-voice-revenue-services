"""Citizen date input — compact, separated, and spoken variants."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.nlu.provider import LocalRuleNLUProvider
from app.services.catalogue import FieldDef, get_service
from app.services.i18n import t
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
from app.services.validation import age_in_years, validate_field
from app.speech.dates import format_date_for_citizen, normalize_spoken_date
from app.speech.stt import MockSTTProvider
from app.speech.tts import MockTTSProvider
from sqlalchemy.orm import Session

from tests.auth_helpers import expand_step

DATE_FIELD = FieldDef(
    name="date_of_birth",
    type="date",
    required=True,
    prompt="DOB",
    validation={"format": "%d/%m/%Y"},
)

MAX_AGE_FIELD = FieldDef(
    name="date_of_birth",
    type="date",
    required=True,
    prompt="DOB",
    validation={"format": "%d/%m/%Y", "max_age": 120},
)


def _dob_years_ago(years: int) -> str:
    today = datetime.now().date()
    year = today.year - years
    month, day = today.month, today.day
    if month == 2 and day == 29:
        day = 28
    return date(year, month, day).strftime("%d/%m/%Y")


@pytest.fixture
def identity() -> MockIdentityProvider:
    return MockIdentityProvider(
        [Persona(id="persona-lakshmi", name="Lakshmi Devi", mobile="9876543210")]
    )


@pytest.fixture
def journey(
    db_session: Session, identity: MockIdentityProvider, gateway: DataBoundaryGateway
) -> JourneyService:
    return JourneyService(db_session, identity=identity, gateway=gateway)


@pytest.fixture
def orch(
    db_session: Session,
    identity: MockIdentityProvider,
    gateway: DataBoundaryGateway,
) -> ChannelOrchestrator:
    js = JourneyService(db_session, identity=identity, gateway=gateway)
    return ChannelOrchestrator(
        db_session,
        gateway=gateway,
        journey=js,
        stt=MockSTTProvider(),
        tts=MockTTSProvider(),
        nlu=LocalRuleNLUProvider(),
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("27/12/1996", "27/12/1996"),
        ("27-12-1996", "27/12/1996"),
        ("27.12.1996", "27/12/1996"),
        ("27 12 1996", "27/12/1996"),
        ("27121996", "27/12/1996"),
        ("27 December 1996", "27/12/1996"),
        ("27th December 1996", "27/12/1996"),
        ("27 0 6 1 9 9 6", "27/06/1996"),
        ("27, 0 6, 1 9 9 6", "27/06/1996"),
    ],
)
def test_validate_field_accepts_natural_date_variants(raw: str, expected: str):
    result = validate_field(DATE_FIELD, raw)
    assert result.ok, result.error
    assert result.value == expected


@pytest.mark.parametrize(
    "raw",
    [
        "32131996",  # impossible calendar after normalize
        "32/13/1996",
        "99/99/9999",
        "27 12",  # incomplete
        "271296",  # 6 digits — no century invent
        "not a date",
    ],
)
def test_validate_field_rejects_invalid_dates(raw: str):
    result = validate_field(DATE_FIELD, raw)
    assert not result.ok


def test_compact_dob_normalizes():
    assert normalize_spoken_date("27121996") == "27/12/1996"


def test_format_date_for_citizen_confirmation():
    assert format_date_for_citizen("27/12/1996") == "27 December 1996"
    assert format_date_for_citizen("01/06/1990") == "1 June 1990"


def test_text_modality_accepts_compact_dob(db_session, journey):
    start = journey.start(trace_id="dob-text")
    app_id, token = start.application_id, start.access_token
    assert token
    for step in ["en", "9876543210", "123456"]:
        journey.handle_message(
            app_id, token, expand_step(journey.identity, step), trace_id="dob-text"
        )
    journey.record_consent(app_id, token, granted=True, trace_id="dob-text")
    journey.handle_message(app_id, token, "INCOME_CERTIFICATE", trace_id="dob-text")
    journey.handle_message(app_id, token, "Lakshmi Devi", trace_id="dob-text")
    reply = journey.handle_message(app_id, token, "27121996", trace_id="dob-text")
    assert reply.error is None
    app = journey._get_app_by_ref(app_id)
    assert (app.form_data or {}).get("date_of_birth") == "27/12/1996"


def test_voice_confirmation_shows_natural_date(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    app_id, token = start.application_id, start.access_token
    assert token

    def voice(text: str):
        return orch.process_channel_payload(
            "web",
            {
                "application_id": app_id,
                "access_token": token,
                "session_ref": token,
                "modality": "voice",
                "language": "en",
                "transcript": text,
            },
        )

    for step in ["en", "9876543210", "123456", "yes", "Income Certificate", "Lakshmi Devi"]:
        voice(expand_step(orch.journey.identity, step))
        if step == "Lakshmi Devi":
            voice("yes")
    confirm = voice("27121996")
    assert confirm.state == JourneyState.FIELD_CONFIRMATION.value
    assert "27 December 1996" in (confirm.message or "")
    assert "date_of_birth" not in (confirm.message or "")
    assert confirm.data.get("proposed_value") == "27/12/1996"


def test_age_in_years_counts_completed_birthdays():
    assert age_in_years(date(2000, 1, 1), date(2020, 1, 1)) == 20
    assert age_in_years(date(2000, 6, 15), date(2020, 6, 14)) == 19


def test_max_age_120_rejects_older_and_allows_120():
    too_old = validate_field(MAX_AGE_FIELD, _dob_years_ago(121))
    assert not too_old.ok
    assert too_old.code == "max_age"

    at_cap = validate_field(MAX_AGE_FIELD, _dob_years_ago(120))
    assert at_cap.ok, at_cap.error

    child = validate_field(MAX_AGE_FIELD, "02/01/2018")
    assert child.ok, child.error


def test_catalogue_income_certificate_declares_max_age_120():
    dob = get_service("INCOME_CERTIFICATE").field_by_name("date_of_birth")
    assert dob is not None
    assert int((dob.validation or {}).get("max_age") or 0) == 120


def test_journey_rejects_dob_over_max_age(journey: JourneyService):
    start = journey.start(trace_id="dob-max")
    app_id, token = start.application_id, start.access_token
    assert token
    for step in ["en", "9876543210", "123456"]:
        journey.handle_message(
            app_id, token, expand_step(journey.identity, step), trace_id="dob-max"
        )
    journey.record_consent(app_id, token, granted=True, trace_id="dob-max")
    journey.handle_message(app_id, token, "INCOME_CERTIFICATE", trace_id="dob-max")
    journey.handle_message(app_id, token, "Lakshmi Devi", trace_id="dob-max")
    reply = journey.handle_message(app_id, token, _dob_years_ago(121), trace_id="dob-max")
    assert reply.error == "validation_failed"
    assert reply.data.get("validation_code") == "max_age"
    assert (journey._get_app_by_ref(app_id).form_data or {}).get("date_of_birth") is None


def test_channel_localizes_max_age_dob_error(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    app_id, token = start.application_id, start.access_token
    assert token
    for step in ["en", "9876543210", "123456"]:
        orch.process_channel_payload(
            "web",
            {
                "application_id": app_id,
                "access_token": token,
                "text": expand_step(orch.journey.identity, step),
            },
        )
    orch.journey.record_consent(app_id, token, granted=True, trace_id="dob-max-ch")
    orch.process_channel_payload(
        "web", {"application_id": app_id, "access_token": token, "text": "INCOME_CERTIFICATE"}
    )
    orch.process_channel_payload(
        "web", {"application_id": app_id, "access_token": token, "text": "Lakshmi Devi"}
    )
    reply = orch.process_channel_payload(
        "web",
        {"application_id": app_id, "access_token": token, "text": _dob_years_ago(121)},
    )
    assert reply.error == "validation_failed"
    assert reply.data.get("validation_code") == "max_age"
    assert t("validation_date_max_age", "en", max_age=120) in (reply.message or "")
    assert "120" in (reply.message or "")
