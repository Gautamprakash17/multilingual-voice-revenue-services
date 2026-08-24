"""Citizen date input — compact, separated, and spoken variants."""

from __future__ import annotations

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.nlu.provider import LocalRuleNLUProvider
from app.services.catalogue import FieldDef
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
from app.services.validation import validate_field
from app.speech.dates import format_date_for_citizen, normalize_spoken_date
from app.speech.stt import MockSTTProvider
from app.speech.tts import MockTTSProvider
from sqlalchemy.orm import Session

DATE_FIELD = FieldDef(
    name="date_of_birth",
    type="date",
    required=True,
    prompt="DOB",
    validation={"format": "%d/%m/%Y"},
)


@pytest.fixture
def identity() -> MockIdentityProvider:
    return MockIdentityProvider(
        [Persona(id="persona-lakshmi", name="Lakshmi Devi", mobile="9876543210", otp="123456")]
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
        journey.handle_message(app_id, token, step, trace_id="dob-text")
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
        voice(step)
        if step == "Lakshmi Devi":
            voice("yes")
    confirm = voice("27121996")
    assert confirm.state == JourneyState.FIELD_CONFIRMATION.value
    assert "27 December 1996" in (confirm.message or "")
    assert "date_of_birth" not in (confirm.message or "")
    assert confirm.data.get("proposed_value") == "27/12/1996"
