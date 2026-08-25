"""Channel / multilingual / speech tests."""

from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.classification import Classification
from app.boundary.gateway import DataBoundaryGateway, GatewayRequest
from app.boundary.providers import OptionalCloudProvider
from app.channels.adapters import (
    IVRSimulatorAdapter,
    WebChannelAdapter,
    WhatsAppSimulatorAdapter,
    get_adapter,
)
from app.channels.envelope import Channel, MessageEnvelope, Modality, validate_envelope
from app.channels.orchestrator import ChannelOrchestrator
from app.core.security import redact_sensitive
from app.models.audit import AuditEvent
from app.nlu.provider import LocalRuleNLUProvider
from app.platform.logging import JsonFormatter
from app.services.catalogue import get_service
from app.services.documents import store_document
from app.services.i18n import REQUIRED_KEYS, assert_all_keys_present, load_translations, t
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
from app.speech.language import detect_language, normalize_language_choice, resolve_language
from app.speech.stt import MockSTTProvider, audio_file_suffix
from app.speech.tts import MockTTSProvider
from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from tests.auth_helpers import current_otp, expand_step


@pytest.fixture
def identity() -> MockIdentityProvider:
    return MockIdentityProvider(
        [
            Persona(
                id="persona-lakshmi",
                name="Lakshmi Devi",
                mobile="9876543210",
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


def test_envelope_validation_and_defaults():
    env = validate_envelope(
        {
            "channel": "web",
            "modality": "text",
            "content": {"text": "hello"},
        }
    )
    assert env.classification == Classification.RESTRICTED
    assert env.channel == Channel.WEB


def test_missing_classification_defaults_restricted():
    env = MessageEnvelope(
        channel=Channel.WEB,
        modality=Modality.TEXT,
        content={"text": "x"},
        classification=None,  # type: ignore[arg-type]
    )
    assert env.classification == Classification.RESTRICTED


def test_invalid_envelope_rejected():
    with pytest.raises(ValidationError):
        validate_envelope({"channel": "web", "modality": "text", "content": {}})


def test_web_adapter_creates_envelope():
    env = WebChannelAdapter().to_envelope(
        {"text": "hi", "application_id": "INC-1", "access_token": "tok"}
    )
    assert env.channel == Channel.WEB
    assert env.modality == Modality.TEXT
    assert env.classification == Classification.RESTRICTED
    assert env.application_ref == "INC-1"


def test_whatsapp_adapter_creates_envelope():
    env = WhatsAppSimulatorAdapter().to_envelope(
        {"message": {"text": "नमस्ते"}, "application_id": "INC-2"}
    )
    assert env.channel == Channel.WHATSAPP
    assert env.text_payload() == "नमस्ते"


def test_ivr_adapter_creates_envelope_dtmf_and_voice():
    dtmf = IVRSimulatorAdapter().to_envelope({"dtmf": "120000", "call_id": "c1"})
    assert dtmf.modality == Modality.DTMF
    assert dtmf.channel == Channel.IVR
    voice = IVRSimulatorAdapter().to_envelope({"transcript": "YES", "call_id": "c1"})
    assert voice.modality == Modality.VOICE


def test_english_hindi_kannada_detection():
    assert detect_language("Hello world").language == "en"
    assert detect_language("मेरा नाम लक्ष्मी है").language == "hi"
    assert detect_language("ನನ್ನ ಹೆಸರು ಲಕ್ಷ್ಮಿ").language == "kn"


def test_low_confidence_language_keeps_selected():
    guess = resolve_language("12345", "kn", min_confidence=0.7)
    assert guess.language == "kn"


def test_normalize_language_choice_natural_names():
    assert normalize_language_choice("English") == "en"
    assert normalize_language_choice("english") == "en"
    assert normalize_language_choice("Hindi") == "hi"
    assert normalize_language_choice("hindi") == "hi"
    assert normalize_language_choice("Kannada") == "kn"
    assert normalize_language_choice("English.") == "en"
    assert normalize_language_choice("Hindi.") == "hi"
    assert normalize_language_choice("Kannada.") == "kn"
    assert normalize_language_choice("  english!  ") == "en"
    assert normalize_language_choice("kannada") == "kn"
    assert normalize_language_choice("हिन्दी") == "hi"
    assert normalize_language_choice("ಕನ್ನಡ") == "kn"
    assert normalize_language_choice("I would like to go with English") == "en"
    assert normalize_language_choice("en") == "en"
    assert normalize_language_choice("French") is None


@pytest.mark.parametrize(
    ("spoken", "code"),
    [
        ("English", "en"),
        ("English.", "en"),
        ("Hindi", "hi"),
        ("Hindi.", "hi"),
        ("Kannada", "kn"),
        ("Kannada.", "kn"),
        ("I would like to go with Hindi", "hi"),
        ("I would like to go with Kannada", "kn"),
    ],
)
def test_voice_language_select_natural_names(
    orch: ChannelOrchestrator, spoken: str, code: str
):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": start.application_id,
            "access_token": token,
            "modality": "voice",
            "language": code,
            "transcript": spoken,
        },
    )
    assert reply.error != "invalid_language"
    assert reply.state == JourneyState.AUTHENTICATE.value
    assert reply.language == code
    assert reply.transcript == spoken


def test_text_language_select_still_works(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": start.application_id,
            "access_token": token,
            "modality": "text",
            "text": "hi",
            "language": "hi",
        },
    )
    assert reply.state == JourneyState.AUTHENTICATE.value
    assert reply.language == "hi"
    assert reply.error != "invalid_language"


def test_voice_spoken_mobile_authentication(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": "English.",
        },
    )
    spoken_mobile = "nine, eight, seven, six, five, four, three, two, one, zero"
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": spoken_mobile,
        },
    )
    assert reply.error != "unknown_mobile"
    assert reply.state == JourneyState.AUTHENTICATE.value
    assert "OTP" in (reply.prompt or "").upper() or "otp" in (reply.prompt or "").lower()
    assert reply.audio_b64


def test_voice_mobile_otp_full_authentication(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": "English",
        },
    )
    mobile_reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": "9 8 7 6 5 4 3 2 1 0",
        },
    )
    assert mobile_reply.error != "unknown_mobile"
    assert mobile_reply.state == JourneyState.AUTHENTICATE.value
    assert "OTP" in (mobile_reply.prompt or "").upper()
    otp_reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "text",
            "language": "en",
            "text": expand_step(orch.journey.identity, "123456"),
        },
    )
    assert otp_reply.state == JourneyState.CONSENT.value
    assert otp_reply.error is None
    assert "unknown_mobile" not in (otp_reply.message or "")


@pytest.mark.parametrize(
    "formatter",
    [
        lambda otp: " ".join(otp),
        lambda otp: " ".join(
            {
                "0": "zero",
                "1": "one",
                "2": "two",
                "3": "three",
                "4": "four",
                "5": "five",
                "6": "six",
                "7": "seven",
                "8": "eight",
                "9": "nine",
            }[d]
            for d in otp
        ),
        lambda otp: ", ".join(otp),
    ],
)
def test_voice_spoken_otp_normalization(orch: ChannelOrchestrator, formatter):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
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
            "modality": "voice",
            "language": "en",
            "transcript": "9876543210",
        },
    )
    otp = current_otp(orch.journey.identity)  # type: ignore[arg-type]
    spoken_otp = formatter(otp)
    otp_reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": spoken_otp,
        },
    )
    assert otp_reply.error != "invalid_otp"
    assert otp_reply.state == JourneyState.CONSENT.value
    assert otp_reply.transcript == spoken_otp
    assert "Authenticated" in (otp_reply.message or "")


def test_voice_wrong_otp_is_citizen_friendly(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "text",
            "text": "en",
            "language": "en",
        },
    )
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "text",
            "text": "9876543210",
            "language": "en",
        },
    )
    otp_reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": "9 9 9 9 9 9",
        },
    )
    assert otp_reply.error == "invalid_otp"
    assert otp_reply.state == JourneyState.AUTHENTICATE.value
    assert "invalid_otp" not in (otp_reply.message or "")
    assert "incorrect" in (otp_reply.message or "").lower()
    assert otp_reply.transcript == "9 9 9 9 9 9"


def test_voice_invalid_mobile_length_is_citizen_friendly(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "text",
            "text": "en",
            "language": "en",
        },
    )
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": "7, 2, 0, 4, 6, 0, 9, 1 and the whole 5",
        },
    )
    assert reply.error == "unknown_mobile"
    assert "unknown_mobile" not in (reply.message or "")
    assert reply.state == JourneyState.AUTHENTICATE.value
    assert reply.audio_b64


def test_voice_unknown_mobile_is_citizen_friendly(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "text",
            "text": "en",
            "language": "en",
        },
    )
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": "one two three four five",
        },
    )
    assert reply.error == "unknown_mobile"
    assert "unknown_mobile" not in (reply.message or "")
    assert "10-digit" in (reply.message or "").lower() or "10" in (reply.message or "")
    assert reply.audio_b64


def test_voice_dob_capture_still_works(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web", {"application_id": app_id, "access_token": token, "text": "en"}
    )
    orch.process_channel_payload(
        "web", {"application_id": app_id, "access_token": token, "text": "9876543210"}
    )
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "text": expand_step(orch.journey.identity, "123456"),
        },
    )
    orch.journey.record_consent(app_id, token, granted=True, trace_id="voice-dob")
    orch.process_channel_payload(
        "web",
        {"application_id": app_id, "access_token": token, "text": "INCOME_CERTIFICATE"},
    )
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": "Gautam Prakash",
        },
    )
    orch.process_channel_payload(
        "web",
        {"application_id": app_id, "access_token": token, "text": "YES"},
    )
    dob_reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": "02/01/2018",
        },
    )
    assert dob_reply.error != "validation_failed"
    assert dob_reply.state == JourneyState.FIELD_CONFIRMATION.value
    saved = orch.process_channel_payload(
        "web",
        {"application_id": app_id, "access_token": token, "text": "YES"},
    )
    assert saved.state == JourneyState.FORM_CAPTURE.value
    app = orch.journey._get_app_by_ref(app_id)
    assert app.form_data.get("date_of_birth") == "02/01/2018"
    assert saved.data.get("form_data", {}).get("date_of_birth") == "02/01/2018"
    assert dob_reply.transcript == "02/01/2018"


def test_translation_keys_exist_for_all_languages():
    from app.services.i18n import supported_language_codes

    missing = assert_all_keys_present()
    for lang in supported_language_codes():
        assert missing[lang] == [], f"{lang} missing {missing[lang]}"
        bundle = load_translations(lang)
        for key in REQUIRED_KEYS:
            assert key in bundle


def test_nlu_intent_and_slot_extraction():
    nlu = LocalRuleNLUProvider()
    assert nlu.parse("CONFIRM").intent == "CONFIRM"
    assert nlu.parse("CORRECT").intent == "CORRECT"
    dob = nlu.parse("I was born on 12/04/1995")
    assert dob.intent == "PROVIDE_DOB"
    assert dob.slots["date_of_birth"] == "12/04/1995"
    mobile = nlu.parse("9876543210", expected_field="mobile_number")
    assert mobile.slots["mobile_number"] == "9876543210"
    income = nlu.parse("150000", expected_field="annual_income")
    assert income.intent == "PROVIDE_INCOME"


def test_invalid_nlu_input():
    nlu = LocalRuleNLUProvider()
    result = nlu.parse("")
    assert result.intent == "UNKNOWN"
    assert result.confidence == 0.0


def test_restricted_voice_and_text_cannot_use_cloud(
    gateway: DataBoundaryGateway, cloud_provider: OptionalCloudProvider
):
    for purpose in ("stt", "tts", "nlu", "channel_ingress"):
        result = gateway.evaluate(
            GatewayRequest(
                payload={"keys": ["audio"]},
                classification=Classification.RESTRICTED,
                destination="cloud",
                purpose=purpose,
            )
        )
        assert result.allowed is False
    assert cloud_provider.call_count == 0


def test_channel_cannot_bypass_boundary(
    orch: ChannelOrchestrator, cloud_provider: OptionalCloudProvider
):
    start = orch.start(channel="web", trace_id="bypass")
    # Even voice path must deny cloud
    orch._assert_no_cloud("stt", "bypass")
    assert cloud_provider.call_count == 0
    assert start.application_id.startswith("INC-")


def test_language_persists_and_localized_response(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "text": "hi",
        },
    )
    # Auth mobile prompt should be Hindi
    status = orch.journey.get_status(app_id, token)
    assert orch.journey._get_app_by_ref(app_id).language == "hi"
    reply = orch.process_channel_payload(
        "web",
        {"application_id": app_id, "access_token": token, "text": "9876543210"},
    )
    assert orch.journey._get_app_by_ref(app_id).language == "hi"
    assert "दर्ज" in (reply.prompt or "") or "OTP" in (reply.prompt or "")
    assert status.application_id == app_id
    # OTP auth must not couple persona identity to language
    otp_reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "text": expand_step(orch.journey.identity, "123456"),
        },
    )
    assert otp_reply.state == JourneyState.CONSENT.value
    assert orch.journey._get_app_by_ref(app_id).language == "hi"
    assert orch.journey._get_app_by_ref(app_id).applicant_id == "persona-lakshmi"


def test_voice_language_selection_independent_of_persona(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "transcript": "Kannada",
        },
    )
    assert orch.journey._get_app_by_ref(app_id).language == "kn"
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "text",
            "text": "9876543210",
            "language": "kn",
        },
    )
    otp_reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "text",
            "text": expand_step(orch.journey.identity, "123456"),
            "language": "kn",
        },
    )
    assert otp_reply.state == JourneyState.CONSENT.value
    assert orch.journey._get_app_by_ref(app_id).language == "kn"


def test_cross_channel_session_resume(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web", {"application_id": app_id, "access_token": token, "text": "en"}
    )
    orch.process_channel_payload(
        "web", {"application_id": app_id, "access_token": token, "text": "9876543210"}
    )
    resumed = orch.resume(
        application_id=app_id, access_token=token, channel="whatsapp", trace_id="r1"
    )
    assert resumed.access_token
    assert resumed.access_token != token
    assert resumed.channel == "whatsapp"
    assert resumed.language == "en"
    # Continue on WhatsApp with new token
    cont = orch.process_channel_payload(
        "whatsapp",
        {
            "application_id": app_id,
            "access_token": resumed.access_token,
            "text": expand_step(orch.journey.identity, "123456"),
        },
    )
    assert cont.state == JourneyState.CONSENT.value


def test_ivr_dtmf_language_menu_and_consent(orch: ChannelOrchestrator):
    start = orch.start(channel="ivr")
    token = start.access_token
    assert token
    app_id = start.application_id
    assert "Press 1 for English" in (start.prompt or "")
    assert "Press 2 for Hindi" in (start.prompt or "")
    assert "Press 3 for Kannada" in (start.prompt or "")

    hi = orch.process_channel_payload(
        "ivr", {"application_id": app_id, "access_token": token, "dtmf": "2"}
    )
    assert hi.state == JourneyState.AUTHENTICATE.value
    assert orch.journey._get_app_by_ref(app_id).language == "hi"

    start_en = orch.start(channel="ivr")
    token_en = start_en.access_token
    assert token_en
    app_en = start_en.application_id
    bad = orch.process_channel_payload(
        "ivr", {"application_id": app_en, "access_token": token_en, "dtmf": "9"}
    )
    assert bad.error == "invalid_language"
    assert bad.state == JourneyState.LANGUAGE_SELECT.value
    ok = orch.process_channel_payload(
        "ivr", {"application_id": app_en, "access_token": token_en, "dtmf": "1"}
    )
    assert ok.state == JourneyState.AUTHENTICATE.value
    assert orch.journey._get_app_by_ref(app_en).language == "en"
    assert ok.data.get("auth_step") == "mobile"
    assert "keypad" in (ok.prompt or "").lower()
    assert "say" not in (ok.prompt or "").lower()

    mobile = orch.process_channel_payload(
        "ivr",
        {"application_id": app_en, "access_token": token_en, "dtmf": "9876543210"},
    )
    assert mobile.data.get("auth_step") == "otp"
    assert "keypad" in (mobile.prompt or "").lower()
    otp = current_otp(orch.journey.identity)  # type: ignore[arg-type]
    auth = orch.process_channel_payload(
        "ivr",
        {"application_id": app_en, "access_token": token_en, "dtmf": otp},
    )
    assert auth.state == JourneyState.CONSENT.value
    consented = orch.process_channel_payload(
        "ivr",
        {"application_id": app_en, "access_token": token_en, "dtmf": "1"},
    )
    assert consented.state == JourneyState.SERVICE_SELECT.value
    service = orch.process_channel_payload(
        "ivr",
        {"application_id": app_en, "access_token": token_en, "dtmf": "1"},
    )
    assert service.state == JourneyState.FORM_CAPTURE.value


def test_ivr_dtmf_registration_choice(orch: ChannelOrchestrator):
    start = orch.start(channel="ivr")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "ivr", {"application_id": app_id, "access_token": token, "dtmf": "1"}
    )
    offer = orch.process_channel_payload(
        "ivr",
        {"application_id": app_id, "access_token": token, "dtmf": "7012987654"},
    )
    assert offer.data.get("auth_step") == "register_offer"
    assert "Press 1 to register" in (offer.prompt or "")
    assert "Press 2 to cancel" in (offer.prompt or "")
    retry = orch.process_channel_payload(
        "ivr", {"application_id": app_id, "access_token": token, "dtmf": "9"}
    )
    assert retry.data.get("auth_step") == "register_offer"
    assert "Press 1 to register" in (retry.prompt or "")
    issued = orch.process_channel_payload(
        "ivr", {"application_id": app_id, "access_token": token, "dtmf": "1"}
    )
    assert issued.data.get("auth_step") == "otp"
    assert issued.data.get("otp_issued") is True
    assert "keypad" in (issued.prompt or "").lower()
    otp = current_otp(orch.journey.identity, "7012987654")  # type: ignore[arg-type]
    named = orch.process_channel_payload(
        "ivr",
        {"application_id": app_id, "access_token": token, "dtmf": otp},
    )
    assert named.data.get("auth_step") == "register_name"
    pending = orch.process_channel_payload(
        "ivr",
        {
            "application_id": app_id,
            "access_token": token,
            "transcript": "New Citizen",
        },
    )
    assert pending.state == JourneyState.FIELD_CONFIRMATION.value
    assert "Press 1" in (pending.prompt or "")
    assert "Press 2" in (pending.prompt or "")
    assert "Press #" not in (pending.prompt or "")
    assert "Press *" not in (pending.prompt or "")
    # Spoken conversational prefix is stripped before confirmation / storage.
    prefix_pending = orch.process_channel_payload(
        "ivr", {"application_id": app_id, "access_token": token, "dtmf": "2"}
    )
    assert prefix_pending.data.get("auth_step") == "register_name"
    prefix_confirm = orch.process_channel_payload(
        "ivr",
        {
            "application_id": app_id,
            "access_token": token,
            "transcript": "My name is New Citizen",
        },
    )
    assert prefix_confirm.state == JourneyState.FIELD_CONFIRMATION.value
    assert prefix_confirm.data.get("proposed_value") == "New Citizen"
    assert "My name is" not in (prefix_confirm.prompt or "")
    # Retry with 2
    retry = orch.process_channel_payload(
        "ivr", {"application_id": app_id, "access_token": token, "dtmf": "2"}
    )
    assert retry.state == JourneyState.AUTHENTICATE.value
    assert retry.data.get("auth_step") == "register_name"
    pending2 = orch.process_channel_payload(
        "ivr",
        {
            "application_id": app_id,
            "access_token": token,
            "transcript": "New Citizen",
        },
    )
    assert pending2.state == JourneyState.FIELD_CONFIRMATION.value
    assert "New Citizen" in (pending2.prompt or "")
    assert "Press 1" in (pending2.prompt or "")
    done = orch.process_channel_payload(
        "ivr", {"application_id": app_id, "access_token": token, "dtmf": "1"}
    )
    assert done.state == JourneyState.CONSENT.value
    assert "Press 1" in (done.prompt or "")
    assert "Press 2" in (done.prompt or "")

    # Decline registration → another mobile (DTMF 2)
    start2 = orch.start(channel="ivr")
    token2 = start2.access_token
    assert token2
    app2 = start2.application_id
    orch.process_channel_payload(
        "ivr", {"application_id": app2, "access_token": token2, "dtmf": "1"}
    )
    orch.process_channel_payload(
        "ivr",
        {"application_id": app2, "access_token": token2, "dtmf": "7012987655"},
    )
    again = orch.process_channel_payload(
        "ivr", {"application_id": app2, "access_token": token2, "dtmf": "2"}
    )
    assert again.data.get("auth_step") == "mobile"

    start = orch.start(channel="ivr")
    token = start.access_token
    assert token
    app_id = start.application_id
    # language via text on IVR
    orch.process_channel_payload(
        "ivr", {"application_id": app_id, "access_token": token, "text": "en"}
    )
    orch.process_channel_payload(
        "ivr", {"application_id": app_id, "access_token": token, "text": "9876543210"}
    )
    orch.process_channel_payload(
        "ivr",
        {
            "application_id": app_id,
            "access_token": token,
            "text": expand_step(orch.journey.identity, "123456"),
        },
    )
    orch.journey.record_consent(app_id, token, granted=True, trace_id="d")
    orch.process_channel_payload(
        "ivr",
        {"application_id": app_id, "access_token": token, "text": "INCOME_CERTIFICATE"},
    )
    # Fill until income via messages then DTMF for income
    for val in ["Lakshmi Devi", "12/04/1995", "9876543210", "12 Temple Street", "Hyderabad"]:
        orch.process_channel_payload(
            "ivr", {"application_id": app_id, "access_token": token, "text": val}
        )
    income = orch.process_channel_payload(
        "ivr",
        {"application_id": app_id, "access_token": token, "dtmf": "120000"},
    )
    assert income.error != "validation_failed"
    app = orch.journey._get_app_by_ref(app_id)
    assert app.form_data.get("annual_income") == 120000


def test_voice_flow_mock_stt(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    audio = base64.b64encode(b"POCSTT:en").decode()
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "audio_b64": audio,
        },
    )
    assert reply.state == JourneyState.AUTHENTICATE.value
    assert reply.transcript == "en"
    assert reply.audio_b64  # TTS mock audio returned


@pytest.mark.asyncio
async def test_p2_journey_auth_consent_docs_submit_still_work(
    db_session: Session,
    orch: ChannelOrchestrator,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.services.documents.get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    j = orch.journey
    j.handle_message(app_id, token, "en", trace_id="p2")
    j.handle_message(app_id, token, "9876543210", trace_id="p2")
    j.handle_message(app_id, token, expand_step(j.identity, "123456"), trace_id="p2")
    j.record_consent(app_id, token, granted=True, trace_id="p2")
    j.handle_message(app_id, token, "INCOME_CERTIFICATE", trace_id="p2")
    for val in [
        "Lakshmi Devi",
        "12/04/1995",
        "9876543210",
        "12 Temple Street",
        "Hyderabad",
        "120000",
        "Agriculture",
    ]:
        j.handle_message(app_id, token, val, trace_id="p2")
    service = get_service("INCOME_CERTIFICATE")
    app = j._get_app_by_ref(app_id)
    for doc in service.documents:
        upload = UploadFile(
            filename=f"{doc.code}.pdf",
            file=io.BytesIO(b"%PDF-1.4 x"),
            headers={"content-type": "application/pdf"},
        )
        await store_document(
            db_session,
            application_pk=app.id,
            document_def=doc,
            upload=upload,
            document_type=(doc.accepted_types[0].code if doc.accepted_types else None),
            actor_id=app.applicant_id,
            trace_id="p2",
        )
    db_session.expire_all()
    review = j.after_document_upload(app_id, token, trace_id="p2")
    assert review.state in {
        JourneyState.REVIEW_CONFIRM.value,
        JourneyState.DOCUMENT_CAPTURE.value,
    }
    if review.state != JourneyState.REVIEW_CONFIRM.value:
        review = j.handle_message(app_id, token, "DONE", trace_id="p2")
    fee = j.handle_message(app_id, token, "CONFIRM", trace_id="p2")
    assert fee.state == JourneyState.FEE_QUOTE.value
    j.handle_message(app_id, token, "PAY", trace_id="p2")
    submitted = j.handle_message(app_id, token, "PAY", trace_id="p2")
    assert submitted.state == JourneyState.SUBMITTED.value


def test_audit_event_safety_no_raw_transcript_or_audio(
    orch: ChannelOrchestrator, db_session: Session
):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    secret_phrase = "SECRET_CITIZEN_PHRASE_XYZ"
    audio = base64.b64encode(b"POCSTT:" + secret_phrase.encode()).decode()
    orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "audio_b64": audio,
        },
    )
    events = db_session.query(AuditEvent).all()
    blob = " ".join(str(e.metadata_json) for e in events)
    assert secret_phrase not in blob
    assert audio not in blob
    assert "POCSTT" not in blob
    types = {e.event_type for e in events}
    assert "VOICE_INPUT_RECEIVED" in types
    assert "STT_COMPLETED" in types
    assert "NLU_COMPLETED" in types


def test_redaction_covers_transcript_and_audio():
    clean = redact_sensitive(
        {"transcript": "hello citizen", "audio_b64": "AAAA", "path": "/ok"}
    )
    assert clean["transcript"] == "[REDACTED]"
    assert clean["audio_b64"] == "[REDACTED]"
    assert clean["path"] == "/ok"


def test_json_formatter_redacts_transcript():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="x",
        args=(),
        exc_info=None,
    )
    record.event = "voice"  # type: ignore[attr-defined]
    record.trace_id = "t"  # type: ignore[attr-defined]
    record.request_id = "r"  # type: ignore[attr-defined]
    record.extra_fields = {"transcript": "raw words", "otp": "123456"}  # type: ignore[attr-defined]
    line = formatter.format(record)
    data = json.loads(line)
    assert data["transcript"] == "[REDACTED]"
    assert "raw words" not in line


def test_get_adapter_and_kannada_journey_prompt(orch: ChannelOrchestrator):
    assert get_adapter("whatsapp").channel == Channel.WHATSAPP
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web", {"application_id": app_id, "access_token": token, "text": "kn"}
    )
    reply = orch.process_channel_payload(
        "web", {"application_id": app_id, "access_token": token, "text": "9876543210"}
    )
    assert reply.language == "kn" or orch.journey._get_app_by_ref(app_id).language == "kn"
    assert t("auth_otp", "kn")


def test_metrics_endpoint_store(orch: ChannelOrchestrator):
    from app.platform.metrics import get_metrics

    before = get_metrics().snapshot()
    orch.start(channel="whatsapp")
    after = get_metrics().snapshot()
    assert after["sessions_by_channel"].get("whatsapp", 0) >= before[
        "sessions_by_channel"
    ].get("whatsapp", 0)


def test_channel_start_includes_welcome_tts(orch: ChannelOrchestrator):
    reply = orch.start(channel="web")
    assert reply.state == JourneyState.LANGUAGE_SELECT.value
    assert reply.audio_b64
    assert reply.audio_mime == "audio/wav"
    assert "Welcome" in (reply.message or "")
    assert "language" in (reply.prompt or "").lower()


def test_english_localized_welcome_and_consent_keys():
    assert "Welcome" in t("welcome", "en") or "welcome" in t("welcome", "en").lower()
    assert "yes" in t("consent", "en").lower()
    assert t("field_annual_income", "hi")
    assert t("submitted", "kn", application_id="INC-1")


def test_mock_stt_and_tts_providers():
    stt = MockSTTProvider()
    result = stt.transcribe(b"POCSTT:CONFIRM")
    assert result.transcript == "CONFIRM"
    assert result.provider == "mock-stt"
    empty = stt.transcribe(b"\x00\x01raw-webm-bytes")
    assert empty.transcript == ""
    assert empty.confidence == 0.0
    tts = MockTTSProvider()
    audio = tts.synthesize("hello", language="en")
    assert audio.audio_b64
    assert audio.mime_type == "audio/wav"


def test_audio_file_suffix_detection():
    assert audio_file_suffix(b"RIFF\x00\x00\x00WAVE") == ".wav"
    assert audio_file_suffix(bytes([0x1A, 0x45, 0xDF, 0xA3])) == ".webm"
    assert audio_file_suffix(b"OggS\x00") == ".ogg"
    assert audio_file_suffix(b"unknown") == ".wav"


def test_voice_raw_audio_without_transcript_is_explicit_stt_failure(
    orch: ChannelOrchestrator,
):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    raw = base64.b64encode(b"not-a-pocstt-marker-webm").decode()
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "audio_b64": raw,
        },
    )
    assert reply.error == "stt_unrecognized"
    assert reply.state == JourneyState.LANGUAGE_SELECT.value
    assert reply.data.get("stt_provider") == "mock-stt"
    assert "faster-whisper" in reply.message


def test_voice_with_mic_audio_and_typed_transcript_mock_fallback(
    orch: ChannelOrchestrator,
):
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    raw = base64.b64encode(b"fake-webm-bytes").decode()
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "language": "en",
            "audio_b64": raw,
            "transcript": "en",
        },
    )
    assert reply.error != "stt_unrecognized"
    assert reply.state == JourneyState.AUTHENTICATE.value
    assert reply.transcript == "en"


def test_ivr_confirm_via_speech(orch: ChannelOrchestrator):
    start = orch.start(channel="ivr")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "ivr", {"application_id": app_id, "access_token": token, "text": "en"}
    )
    reply = orch.process_channel_payload(
        "ivr",
        {
            "application_id": app_id,
            "access_token": token,
            "modality": "voice",
            "transcript": "ESCALATE",
        },
    )
    assert reply.state == JourneyState.ESCALATED.value


def test_whatsapp_full_auth_path(orch: ChannelOrchestrator):
    start = orch.start(channel="whatsapp")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "whatsapp", {"application_id": app_id, "access_token": token, "text": "en"}
    )
    orch.process_channel_payload(
        "whatsapp",
        {"application_id": app_id, "access_token": token, "text": "9876543210"},
    )
    ok = orch.process_channel_payload(
        "whatsapp",
        {
            "application_id": app_id,
            "access_token": token,
            "text": expand_step(orch.journey.identity, "123456"),
        },
    )
    assert ok.state == JourneyState.CONSENT.value


def test_envelope_voice_requires_payload():
    with pytest.raises(ValidationError):
        validate_envelope(
            {"channel": "web", "modality": "voice", "content": {}}
        )


def test_channel_orchestrator_rejects_missing_session(orch: ChannelOrchestrator):
    with pytest.raises(ValueError):
        orch.process_envelope(
            MessageEnvelope(
                channel=Channel.WEB,
                modality=Modality.TEXT,
                content={"text": "hi"},
            )
        )


def test_nlu_escalate_and_status_intents():
    nlu = LocalRuleNLUProvider()
    assert nlu.parse("help").intent == "ESCALATE"
    assert nlu.parse("status").intent == "STATUS"
    assert nlu.parse("start").intent == "START_APPLICATION"
