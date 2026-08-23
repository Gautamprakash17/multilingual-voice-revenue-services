"""Full voice journey smoke test — browser-equivalent channel flow."""

from __future__ import annotations

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.nlu.provider import LocalRuleNLUProvider
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
from app.speech.stt import MockSTTProvider
from app.speech.tts import MockTTSProvider
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


def _voice(orch: ChannelOrchestrator, app_id: str, token: str, transcript: str):
    return orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": "voice",
            "language": "en",
            "transcript": transcript,
        },
    )


def test_full_voice_journey_smoke(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    assert start.audio_b64
    token = start.access_token
    app_id = start.application_id

    lang = _voice(orch, app_id, token, "I would like to go with English")
    assert lang.state == JourneyState.AUTHENTICATE.value
    assert lang.audio_b64

    mobile = _voice(orch, app_id, token, "7 2 0 4 6 0 9 1 5 5")
    assert mobile.error == "unknown_mobile"  # persona mobile is 9876543210

    mobile_ok = _voice(orch, app_id, token, "9 8 7 6 5 4 3 2 1 0")
    assert mobile_ok.state == JourneyState.AUTHENTICATE.value
    assert "OTP" in (mobile_ok.prompt or "").upper()

    otp = _voice(orch, app_id, token, "1 2 3 4 5 6")
    assert otp.state == JourneyState.CONSENT.value
    assert otp.audio_b64

    consent = _voice(orch, app_id, token, "I Agree")
    assert consent.state == JourneyState.SERVICE_SELECT.value
    assert consent.error != "consent_unclear"
    assert consent.audio_b64

    service = _voice(orch, app_id, token, "Income Certificate")
    assert service.state == JourneyState.FORM_CAPTURE.value

    name_pending = _voice(orch, app_id, token, "Gautam Prakash")
    assert name_pending.state == JourneyState.FIELD_CONFIRMATION.value

    confirm_yes = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": "text",
            "text": "Yes",
            "language": "en",
        },
    )
    assert confirm_yes.state == JourneyState.FORM_CAPTURE.value
    assert confirm_yes.data.get("next_field") == "date_of_birth"
