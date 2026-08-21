"""P3 channel / multilingual / speech tests."""

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
from app.speech.language import detect_language, resolve_language
from app.speech.stt import MockSTTProvider
from app.speech.tts import MockTTSProvider
from fastapi import UploadFile
from pydantic import ValidationError
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


def test_english_hindi_telugu_detection():
    assert detect_language("Hello world").language == "en"
    assert detect_language("मेरा नाम लक्ष्मी है").language == "hi"
    assert detect_language("నా పేరు లక్ష్మి").language == "te"


def test_low_confidence_language_keeps_selected():
    guess = resolve_language("12345", "te", min_confidence=0.7)
    assert guess.language == "te"


def test_translation_keys_exist_for_all_languages():
    missing = assert_all_keys_present()
    for lang in ("en", "hi", "te"):
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
            "text": "123456",
        },
    )
    assert cont.state == JourneyState.CONSENT.value


def test_dtmf_numeric_parsing(orch: ChannelOrchestrator):
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
        "ivr", {"application_id": app_id, "access_token": token, "text": "123456"}
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
    j.handle_message(app_id, token, "123456", trace_id="p2")
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
    submitted = j.handle_message(app_id, token, "CONFIRM", trace_id="p2")
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


def test_get_adapter_and_telugu_journey_prompt(orch: ChannelOrchestrator):
    assert get_adapter("whatsapp").channel == Channel.WHATSAPP
    start = orch.start(channel="web")
    token = start.access_token
    assert token
    app_id = start.application_id
    orch.process_channel_payload(
        "web", {"application_id": app_id, "access_token": token, "text": "te"}
    )
    reply = orch.process_channel_payload(
        "web", {"application_id": app_id, "access_token": token, "text": "9876543210"}
    )
    # Telugu OTP or mobile prompt
    assert reply.language == "te" or orch.journey._get_app_by_ref(app_id).language == "te"
    assert t("auth_otp", "te")


def test_metrics_endpoint_store(orch: ChannelOrchestrator):
    from app.platform.metrics import get_metrics

    before = get_metrics().snapshot()
    orch.start(channel="whatsapp")
    after = get_metrics().snapshot()
    assert after["sessions_by_channel"].get("whatsapp", 0) >= before[
        "sessions_by_channel"
    ].get("whatsapp", 0)


def test_english_localized_welcome_and_consent_keys():
    assert "Welcome" in t("welcome", "en") or "welcome" in t("welcome", "en").lower()
    assert "YES" in t("consent", "en")
    assert t("field_annual_income", "hi")
    assert t("submitted", "te", application_id="INC-1")


def test_mock_stt_and_tts_providers():
    stt = MockSTTProvider()
    result = stt.transcribe(b"POCSTT:CONFIRM")
    assert result.transcript == "CONFIRM"
    assert result.provider == "mock-stt"
    tts = MockTTSProvider()
    audio = tts.synthesize("hello", language="en")
    assert audio.audio_b64
    assert audio.mime_type == "audio/wav"


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
        {"application_id": app_id, "access_token": token, "text": "123456"},
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
