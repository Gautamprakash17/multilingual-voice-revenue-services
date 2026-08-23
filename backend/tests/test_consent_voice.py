"""Consent voice recognition — regression tests for live browser flow."""

from __future__ import annotations

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.nlu.consent import parse_consent_response
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


def _auth_to_consent(orch: ChannelOrchestrator) -> tuple[str, str]:
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": "voice",
            "language": "en",
            "transcript": "English",
        },
    )
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": "voice",
            "language": "en",
            "transcript": "9 8 7 6 5 4 3 2 1 0",
        },
    )
    otp = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": "voice",
            "language": "en",
            "transcript": "1 2 3 4 5 6",
        },
    )
    assert otp.state == JourneyState.CONSENT.value
    return app_id, token


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


@pytest.mark.parametrize(
    "phrase",
    [
        "I Agree",
        "I agree",
        "I agree.",
        "i agree",
        "YES",
        "Yes",
        "yes",
        "yeah",
        "yes, I agree",
        "Yes, I agree.",
        "I agree to provide my information for processing this certificate application",
    ],
)
def test_consent_voice_positive_phrases(orch: ChannelOrchestrator, phrase: str):
    app_id, token = _auth_to_consent(orch)
    reply = _voice(orch, app_id, token, phrase)
    assert reply.state == JourneyState.SERVICE_SELECT.value, (
        f"phrase {phrase!r} failed: state={reply.state} error={reply.error} msg={reply.message}"
    )
    assert reply.error != "consent_unclear"


def test_consent_voice_decline_still_works(orch: ChannelOrchestrator):
    app_id, token = _auth_to_consent(orch)
    reply = _voice(orch, app_id, token, "Decline")
    assert reply.error == "consent_declined"
    assert reply.state == JourneyState.CONSENT.value


def test_consent_nlu_mode_exact_browser_transcript(orch: ChannelOrchestrator):
    app_id, token = _auth_to_consent(orch)
    reply = _voice(orch, app_id, token, "I Agree")
    assert reply.transcript == "I Agree"
    assert reply.state == JourneyState.SERVICE_SELECT.value


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("I Agree", True),
        ("yes", True),
        ("YES", True),
        ("yes, I agree", True),
        ("I agree.", True),
        ("Decline", False),
        ("no", False),
        ("I don't agree", False),
        ("maybe later", None),
    ],
)
def test_parse_consent_response_variants(phrase: str, expected: bool | None):
    assert parse_consent_response(phrase) is expected


def test_consent_nlu_consent_mode():
    nlu = LocalRuleNLUProvider()
    result = nlu.parse("yes", expected_field="__consent__")
    assert result.intent == "CONSENT"
    assert result.slots.get("granted") is True

    result2 = nlu.parse("I Agree", expected_field="__consent__")
    assert result2.slots.get("granted") is True
