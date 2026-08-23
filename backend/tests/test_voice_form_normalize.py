"""Voice form-field normalization — type-driven, catalogue-generic."""

from __future__ import annotations

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.nlu.provider import LocalRuleNLUProvider
from app.services.catalogue import FieldDef
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
from app.speech.dates import (
    normalize_spoken_date,
    normalize_spoken_number_field,
    normalize_spoken_text_field,
)
from app.speech.stt import MockSTTProvider
from app.speech.tts import MockTTSProvider
from sqlalchemy.orm import Session


@pytest.fixture
def identity() -> MockIdentityProvider:
    return MockIdentityProvider(
        [Persona(id="persona-lakshmi", name="Lakshmi Devi", mobile="9876543210", otp="123456")]
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


def _voice(
    orch: ChannelOrchestrator,
    app_id: str,
    token: str,
    transcript: str,
    language: str = "en",
):
    return orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": "voice",
            "language": language,
            "transcript": transcript,
        },
    )


def _to_field(orch: ChannelOrchestrator, field_index: int = 0) -> tuple[str, str]:
    """Reach FORM_CAPTURE with optional fields already confirmed (0 = name)."""
    start = orch.start(channel="web")
    app_id, token = start.application_id, start.access_token
    assert token
    for step in ["en", "9876543210", "123456", "yes", "Income Certificate"]:
        _voice(orch, app_id, token, step)
    values = [
        "Lakshmi Devi",
        "12/04/1995",
        "9876543210",
        "12 Temple Street",
        "Bengaluru",
        "120000",
        "Agriculture",
    ]
    for value in values[:field_index]:
        _voice(orch, app_id, token, value)
        _voice(orch, app_id, token, "yes")
    return app_id, token


# ---------------------------------------------------------------------------
# Unit: date normalizer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("27 06 1996", "27/06/1996"),
        ("27, 06, 1996", "27/06/1996"),
        ("27, 0 6, 1 9 9 6", "27/06/1996"),
        ("27, 0 6, 1 9 9 6.", "27/06/1996"),
        ("27 / 06 / 1996", "27/06/1996"),
        ("27 slash 06 slash 1996", "27/06/1996"),
        ("27 June 1996", "27/06/1996"),
        ("27th June 1996", "27/06/1996"),
        ("27 jun 1996", "27/06/1996"),
        ("१ २ ० ४ १ ९ ९ ५", "12/04/1995"),
        ("೨ ೭ ೦ ೬ ೧ ೯ ೯ ೬", "27/06/1996"),
    ],
)
def test_normalize_spoken_date_examples(spoken: str, expected: str | None):
    assert normalize_spoken_date(spoken) == expected


@pytest.mark.parametrize(
    "spoken",
    [
        "27 06",  # incomplete
        "27 06 96",  # only 6 digits — do not invent century
        "I live in Bengaluru",
        "Gotham Bracass",
        "please continue",
    ],
)
def test_normalize_spoken_date_rejects_non_dates(spoken: str):
    assert normalize_spoken_date(spoken) is None


def test_impossible_calendar_date_still_normalizes_for_validation():
    assert normalize_spoken_date("32 13 1996") == "32/13/1996"


def test_normalize_spoken_date_future_left_to_validation():
    # Normalizer yields the string; validate_field rejects future dates.
    from datetime import date

    future = date.today().replace(year=date.today().year + 1)
    spoken = future.strftime("%d %m %Y")
    assert normalize_spoken_date(spoken) == future.strftime("%d/%m/%Y")


# ---------------------------------------------------------------------------
# Unit: number + text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("1200000", "1200000"),
        ("1 2 0 0 0 0 0", "1200000"),
        ("12,00,000", "12,00,000"),  # typed/literal form — validate_field strips commas
        ("1,200,000", "1,200,000"),
        ("one two zero zero zero", "12000"),
    ],
)
def test_normalize_spoken_number_field(spoken: str, expected: str):
    assert normalize_spoken_number_field(spoken) == expected


@pytest.mark.parametrize(
    "spoken",
    [
        "I work in agriculture",
        "Gotham Bracass",
        "please help me",
    ],
)
def test_number_normalizer_does_not_swallow_sentences(spoken: str):
    assert normalize_spoken_number_field(spoken) is None


def test_text_field_strips_trailing_stt_period():
    assert normalize_spoken_text_field("Gotham Bracass.") == "Gotham Bracass"
    assert normalize_spoken_text_field("  12 Temple   Street  ") == "12 Temple Street"


# ---------------------------------------------------------------------------
# Journey type routing
# ---------------------------------------------------------------------------


def test_normalize_voice_field_input_is_type_driven(orch: ChannelOrchestrator):
    journey = orch.journey
    date_field = FieldDef(
        name="date_of_birth",
        type="date",
        required=True,
        prompt="dob",
        validation={"format": "%d/%m/%Y"},
    )
    number_field = FieldDef(
        name="annual_income",
        type="number",
        required=True,
        prompt="income",
        validation={"min": 0},
    )
    string_field = FieldDef(
        name="applicant_name",
        type="string",
        required=True,
        prompt="name",
        validation={"min_length": 2},
    )
    assert (
        journey._normalize_voice_field_input(date_field, "27, 0 6, 1 9 9 6.")
        == "27/06/1996"
    )
    assert journey._normalize_voice_field_input(number_field, "1 2 0 0 0 0") == "120000"
    assert (
        journey._normalize_voice_field_input(string_field, "Gotham Bracass.")
        == "Gotham Bracass"
    )


# ---------------------------------------------------------------------------
# End-to-end voice confirmation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spoken",
    [
        "27 06 1996",
        "27, 06, 1996",
        "27, 0 6, 1 9 9 6",
        "27, 0 6, 1 9 9 6.",
        "27 / 06 / 1996",
        "27 June 1996",
    ],
)
def test_voice_dob_normalizes_then_confirms(orch: ChannelOrchestrator, spoken: str):
    app_id, token = _to_field(orch, field_index=1)  # past name → DOB
    pending = _voice(orch, app_id, token, spoken)
    assert pending.state == JourneyState.FIELD_CONFIRMATION.value
    assert pending.data.get("proposed_value") == "27/06/1996"
    assert "27/06/1996" in (pending.message or "")

    saved = _voice(orch, app_id, token, "yes")
    assert saved.state == JourneyState.FORM_CAPTURE.value
    app = orch.journey._get_app_by_ref(app_id)
    assert (app.form_data or {}).get("date_of_birth") == "27/06/1996"


def test_voice_dob_invalid_stays_in_form_capture(orch: ChannelOrchestrator):
    app_id, token = _to_field(orch, field_index=1)
    bad = _voice(orch, app_id, token, "not a real date")
    assert bad.error == "validation_failed"
    assert bad.state == JourneyState.FORM_CAPTURE.value


def test_voice_dob_future_rejected(orch: ChannelOrchestrator):
    from datetime import date

    future = date.today().replace(year=date.today().year + 2)
    app_id, token = _to_field(orch, field_index=1)
    bad = _voice(orch, app_id, token, future.strftime("%d %m %Y"))
    assert bad.error == "validation_failed"
    assert bad.state == JourneyState.FORM_CAPTURE.value


def test_voice_dob_no_reprompts(orch: ChannelOrchestrator):
    app_id, token = _to_field(orch, field_index=1)
    pending = _voice(orch, app_id, token, "27, 0 6, 1 9 9 6")
    assert pending.state == JourneyState.FIELD_CONFIRMATION.value
    retry = _voice(orch, app_id, token, "no")
    assert retry.state == JourneyState.FORM_CAPTURE.value
    assert retry.data.get("next_field") == "date_of_birth"
    app = orch.journey._get_app_by_ref(app_id)
    assert "date_of_birth" not in (app.form_data or {})


@pytest.mark.parametrize(
    "spoken",
    ["120000", "1 2 0 0 0 0", "1,20,000"],
)
def test_voice_income_normalizes_then_confirms(orch: ChannelOrchestrator, spoken: str):
    app_id, token = _to_field(orch, field_index=5)  # up to district done → income
    pending = _voice(orch, app_id, token, spoken)
    assert pending.state == JourneyState.FIELD_CONFIRMATION.value
    assert str(pending.data.get("proposed_value")) == "120000"
    saved = _voice(orch, app_id, token, "yes that's correct")
    assert saved.state == JourneyState.FORM_CAPTURE.value
    app = orch.journey._get_app_by_ref(app_id)
    assert str((app.form_data or {}).get("annual_income")) == "120000"


def test_voice_name_confirmation_preserves_transcript(orch: ChannelOrchestrator):
    app_id, token = _to_field(orch, field_index=0)
    pending = _voice(orch, app_id, token, "Gotham Bracass.")
    assert pending.state == JourneyState.FIELD_CONFIRMATION.value
    assert pending.data.get("proposed_value") == "Gotham Bracass"
    declined = _voice(orch, app_id, token, "no")
    assert declined.state == JourneyState.FORM_CAPTURE.value
    pending2 = _voice(orch, app_id, token, "Lakshmi Devi")
    _voice(orch, app_id, token, "yes")
    app = orch.journey._get_app_by_ref(app_id)
    assert (app.form_data or {}).get("applicant_name") == "Lakshmi Devi"
    assert pending2.state == JourneyState.FIELD_CONFIRMATION.value


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
def test_voice_dob_works_in_each_language(orch: ChannelOrchestrator, language: str):
    start = orch.start(channel="web")
    app_id, token = start.application_id, start.access_token
    assert token
    affirm = {"en": "yes", "hi": "हाँ", "kn": "ಹೌದು"}[language]
    for step in [language, "9876543210", "123456", affirm, "Income Certificate"]:
        _voice(orch, app_id, token, step, language)
    _voice(orch, app_id, token, "Lakshmi Devi", language)
    _voice(orch, app_id, token, affirm, language)
    pending = _voice(orch, app_id, token, "27, 0 6, 1 9 9 6", language)
    assert pending.state == JourneyState.FIELD_CONFIRMATION.value
    assert pending.data.get("proposed_value") == "27/06/1996"
