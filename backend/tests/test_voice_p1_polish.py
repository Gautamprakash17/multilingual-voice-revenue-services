"""Voice-first P1 polish — spoken error recovery, natural confirmation, localized payment."""

from __future__ import annotations

import re

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.nlu.provider import LocalRuleNLUProvider
from app.services.i18n import assert_all_keys_present, supported_language_codes, t
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
from app.speech.stt import MockSTTProvider
from app.speech.tts import MockTTSProvider
from sqlalchemy.orm import Session

# Tokens that must never reach a citizen-facing prompt in any language.
INTERNAL_TOKENS = (
    "YES",
    "NO",
    "CONFIRM",
    "CORRECT",
    "INCOME_CERTIFICATE",
    "RETRY",
    "TIMEOUT",
    "PAY",
    "FAIL",
    "ESCALATE",
    "CANCEL",
)


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


def _voice(orch: ChannelOrchestrator, app_id: str, token: str, transcript: str, language: str):
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


def _to_form_capture(orch: ChannelOrchestrator, language: str) -> tuple[str, str]:
    """Authenticate and reach FORM_CAPTURE entirely by voice in the given language."""
    start = orch.start(channel="web")
    app_id, token = start.application_id, start.access_token
    assert token
    for utterance in [language, "9876543210", "123456", "yes", "Income Certificate"]:
        _voice(orch, app_id, token, utterance, language)
    return app_id, token


# --------------------------------------------------------------------------------------
# 1. Voice validation errors are spoken back
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
@pytest.mark.parametrize(
    ("field_value", "bad_value"),
    [
        ("Lakshmi Devi", "not a real date"),  # invalid DOB
    ],
)
def test_invalid_dob_by_voice_is_spoken(
    orch: ChannelOrchestrator, language: str, field_value: str, bad_value: str
):
    app_id, token = _to_form_capture(orch, language)
    _voice(orch, app_id, token, field_value, language)
    _voice(orch, app_id, token, "yes", language)  # commit the name

    reply = _voice(orch, app_id, token, bad_value, language)
    assert reply.error == "validation_failed"
    assert reply.audio_b64, "voice user must hear the validation re-prompt, not silence"
    assert reply.state == JourneyState.FORM_CAPTURE.value


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
def test_invalid_mobile_field_by_voice_is_spoken(orch: ChannelOrchestrator, language: str):
    app_id, token = _to_form_capture(orch, language)
    for value in ["Lakshmi Devi", "12/04/1995"]:
        _voice(orch, app_id, token, value, language)
        _voice(orch, app_id, token, "yes", language)

    reply = _voice(orch, app_id, token, "12345", language)
    assert reply.error == "validation_failed"
    assert reply.audio_b64
    # The localized "enter a valid 10-digit mobile" copy is used, not a raw code.
    assert reply.message == t("validation_mobile_invalid", language)


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
def test_invalid_numeric_income_by_voice_is_spoken(orch: ChannelOrchestrator, language: str):
    app_id, token = _to_form_capture(orch, language)
    for value in ["Lakshmi Devi", "12/04/1995", "9876543210", "12 Temple Street", "Bengaluru"]:
        _voice(orch, app_id, token, value, language)
        _voice(orch, app_id, token, "yes", language)

    reply = _voice(orch, app_id, token, "quite a lot of rupees", language)
    assert reply.error == "validation_failed"
    assert reply.audio_b64
    assert reply.message == t("validation_failed", language)


def test_unrecognised_mobile_and_otp_still_speak(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    app_id, token = start.application_id, start.access_token
    assert token
    _voice(orch, app_id, token, "en", "en")
    assert _voice(orch, app_id, token, "9999999999", "en").audio_b64
    _voice(orch, app_id, token, "9876543210", "en")
    assert _voice(orch, app_id, token, "000000", "en").audio_b64


# --------------------------------------------------------------------------------------
# 2. Natural field confirmation vocabulary
# --------------------------------------------------------------------------------------


YES_UTTERANCES = [
    "yes",
    "yeah",
    "yes please",
    "yes that's correct",
    "that's right",
    "that is correct",
    "correct",
    "okay",
    "ok",
    "haan",
    "हाँ",
    "ಸರಿ",
    "ಹೌದು",
]

NO_UTTERANCES = [
    "no",
    "nope",
    "no please",
    "no, try again",
    "try again",
    "that's wrong",
    "incorrect",
    "not correct",
    "nahi",
    "नहीं",
    "ಬೇಡ",
    "ಇಲ್ಲ",
]


@pytest.mark.parametrize("utterance", YES_UTTERANCES)
def test_field_confirmation_accepts_natural_yes(utterance: str):
    nlu = LocalRuleNLUProvider()
    result = nlu.parse(utterance, expected_field="__field_confirm__")
    assert result.intent == "CONSENT", utterance
    assert result.slots.get("granted") is True, utterance


@pytest.mark.parametrize("utterance", NO_UTTERANCES)
def test_field_confirmation_accepts_natural_no(utterance: str):
    nlu = LocalRuleNLUProvider()
    result = nlu.parse(utterance, expected_field="__field_confirm__")
    assert result.intent == "CONSENT", utterance
    assert result.slots.get("granted") is False, utterance


@pytest.mark.parametrize(
    "utterance", ["yes", "yes please", "yes that's correct", "okay", "हाँ", "ಹೌದು", "ಸರಿ"]
)
def test_consent_accepts_the_same_natural_yes(orch: ChannelOrchestrator, utterance: str):
    """A citizen should not have to learn a second yes/no vocabulary for consent."""
    start = orch.start(channel="web")
    app_id, token = start.application_id, start.access_token
    assert token
    for step in ["en", "9876543210", "123456"]:
        _voice(orch, app_id, token, step, "en")

    granted = _voice(orch, app_id, token, utterance, "en")
    assert granted.state == JourneyState.SERVICE_SELECT.value, utterance
    assert granted.error != "consent_unclear"


def test_unclear_consent_is_spoken_and_token_free(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    app_id, token = start.application_id, start.access_token
    assert token
    for step in ["en", "9876543210", "123456"]:
        _voice(orch, app_id, token, step, "en")

    unclear = _voice(orch, app_id, token, "hmm I am not sure about this", "en")
    assert unclear.error == "consent_unclear"
    assert unclear.audio_b64
    assert "YES" not in unclear.message and "NO" not in unclear.message


def test_confirmation_does_not_swallow_correction_word():
    """'ಸರಿಪಡಿಸಿ' (correct it) must not be read as the affirmative 'ಸರಿ'."""
    nlu = LocalRuleNLUProvider()
    result = nlu.parse("ಸರಿಪಡಿಸಿ", expected_field="__field_confirm__")
    assert result.slots.get("granted") is not True


@pytest.mark.parametrize("utterance", ["yes that's correct", "that's right", "okay", "ಸರಿ"])
def test_natural_yes_commits_field_end_to_end(orch: ChannelOrchestrator, utterance: str):
    app_id, token = _to_form_capture(orch, "en")
    pending = _voice(orch, app_id, token, "Lakshmi Devi", "en")
    assert pending.state == JourneyState.FIELD_CONFIRMATION.value

    committed = _voice(orch, app_id, token, utterance, "en")
    assert committed.state == JourneyState.FORM_CAPTURE.value
    assert committed.data.get("next_field") == "date_of_birth"


@pytest.mark.parametrize("utterance", ["no please", "that's wrong", "try again", "ಬೇಡ"])
def test_natural_no_reprompts_same_field(orch: ChannelOrchestrator, utterance: str):
    app_id, token = _to_form_capture(orch, "en")
    _voice(orch, app_id, token, "Lakshmi Devi", "en")

    retry = _voice(orch, app_id, token, utterance, "en")
    assert retry.state == JourneyState.FORM_CAPTURE.value
    assert retry.data.get("next_field") == "applicant_name"
    assert retry.audio_b64


# --------------------------------------------------------------------------------------
# 3 + 4. Localized payment prompts and no internal tokens
# --------------------------------------------------------------------------------------


def test_all_languages_define_every_required_key():
    assert assert_all_keys_present() == {lang: [] for lang in supported_language_codes()}


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
@pytest.mark.parametrize(
    "key",
    [
        "consent",
        "consent_unclear",
        "service_select",
        "review_intro",
        "fee_quote",
        "payment_prompt",
        "payment_failed",
        "document_prompt",
        "validation_failed",
        "field_confirm_heard",
    ],
)
def test_citizen_prompts_expose_no_internal_tokens(language: str, key: str):
    text = t(key, language, amount="50.00", currency="INR", value="x", field_label="y")
    for token in INTERNAL_TOKENS:
        assert token not in text, f"{language}/{key} leaks {token}: {text}"


def test_service_config_prompts_expose_no_internal_tokens(orch: ChannelOrchestrator):
    """The raw journey API (used by document upload) must also be token-free."""
    for key, value in orch.journey.service.prompts.items():
        for token in INTERNAL_TOKENS:
            assert not re.search(rf"\b{token}\b", str(value)), f"prompt {key} leaks {token}"


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
def test_payment_prompts_are_localized(language: str):
    for key in ("fee_quote", "payment_prompt", "payment_failed"):
        localized = t(key, language, amount="50.00", currency="INR")
        english = t(key, "en", amount="50.00", currency="INR")
        if language == "en":
            assert localized == english
        else:
            assert localized != english, f"{language}/{key} fell back to English"


# --------------------------------------------------------------------------------------
# 5. Payment by voice in every language, tester tokens preserved
# --------------------------------------------------------------------------------------


def _to_fee_quote(orch: ChannelOrchestrator, db: Session, language: str) -> tuple[str, str]:
    app_id, token = _to_form_capture(orch, language)
    for value in [
        "Lakshmi Devi",
        "12/04/1995",
        "9876543210",
        "12 Temple Street",
        "Bengaluru",
        "120000",
        "Agriculture",
    ]:
        _voice(orch, app_id, token, value, language)
        _voice(orch, app_id, token, "yes", language)

    journey = orch.journey
    app = journey._get_app_by_ref(app_id)
    app.current_state = JourneyState.REVIEW_CONFIRM.value
    db.flush()
    return app_id, token


@pytest.mark.parametrize(
    ("language", "affirmative"),
    [("en", "yes please"), ("en", "yes that's correct"), ("hi", "हाँ"), ("kn", "ಹೌದು")],
)
def test_voice_can_complete_payment_in_every_language(
    orch: ChannelOrchestrator, db_session: Session, language: str, affirmative: str
):
    app_id, token = _to_fee_quote(orch, db_session, language)

    fee = _voice(orch, app_id, token, affirmative, language)
    assert fee.state == JourneyState.FEE_QUOTE.value
    assert fee.audio_b64

    payment = _voice(orch, app_id, token, affirmative, language)
    assert payment.state == JourneyState.PAYMENT.value

    submitted = _voice(orch, app_id, token, affirmative, language)
    assert submitted.state == JourneyState.SUBMITTED.value


def test_tester_fail_and_timeout_tokens_still_work(orch: ChannelOrchestrator, db_session: Session):
    app_id, token = _to_fee_quote(orch, db_session, "en")
    _voice(orch, app_id, token, "yes", "en")  # REVIEW -> FEE_QUOTE
    _voice(orch, app_id, token, "PAY", "en")  # FEE_QUOTE -> PAYMENT

    failed = _voice(orch, app_id, token, "FAIL", "en")
    assert failed.state == JourneyState.PAYMENT_FAILED.value

    retried = _voice(orch, app_id, token, "RETRY", "en")
    assert retried.state == JourneyState.SUBMITTED.value


def test_voice_cancel_returns_from_payment(orch: ChannelOrchestrator, db_session: Session):
    app_id, token = _to_fee_quote(orch, db_session, "en")
    _voice(orch, app_id, token, "yes", "en")
    _voice(orch, app_id, token, "yes", "en")  # now in PAYMENT

    cancelled = _voice(orch, app_id, token, "cancel", "en")
    assert cancelled.state == JourneyState.FEE_QUOTE.value


def test_payment_reply_carries_localized_audio_and_no_tokens(
    orch: ChannelOrchestrator, db_session: Session
):
    app_id, token = _to_fee_quote(orch, db_session, "hi")
    fee = _voice(orch, app_id, token, "हाँ", "hi")
    assert fee.audio_b64
    assert fee.message == t("fee_quote", "hi", amount="50.00", currency="INR")
    for token_text in INTERNAL_TOKENS:
        assert token_text not in (fee.prompt or "")
