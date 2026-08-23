"""Generic voice field confirmation for FORM_CAPTURE values."""

from __future__ import annotations

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.models.application import Application
from app.services.i18n import field_label_for_confirm, t
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
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
def journey(
    db_session: Session,
    identity: MockIdentityProvider,
    gateway: DataBoundaryGateway,
) -> JourneyService:
    return JourneyService(db_session, identity=identity, gateway=gateway)


def _auth_to_form(journey: JourneyService, *, lang: str = "en") -> tuple[str, str]:
    start = journey.start(trace_id="voice-confirm")
    token = start.access_token
    assert token
    app_id = start.application_id
    journey.handle_message(app_id, token, lang, trace_id="voice-confirm")
    journey.handle_message(app_id, token, "9876543210", trace_id="voice-confirm")
    journey.handle_message(app_id, token, "123456", trace_id="voice-confirm")
    journey.record_consent(app_id, token, granted=True, trace_id="voice-confirm")
    journey.handle_message(app_id, token, "INCOME_CERTIFICATE", trace_id="voice-confirm")
    return app_id, token


def _app(journey: JourneyService, app_id: str) -> Application:
    return journey._get_app_by_ref(app_id)


def test_voice_name_pending_then_yes_saves(db_session: Session, journey: JourneyService):
    app_id, token = _auth_to_form(journey)
    pending = journey.handle_message(
        app_id,
        token,
        "Gotham Bracass",
        trace_id="name-voice",
        input_modality="voice",
    )
    app = _app(journey, app_id)
    assert pending.state == JourneyState.FIELD_CONFIRMATION.value
    assert pending.data.get("proposed_value") == "Gotham Bracass"
    assert pending.data.get("field") == "applicant_name"
    assert "applicant_name" not in (app.form_data or {})
    assert app.pending_voice_field == "applicant_name"
    assert app.pending_voice_value == "Gotham Bracass"

    saved = journey.handle_message(app_id, token, "YES", trace_id="name-voice")
    db_session.refresh(app)
    assert saved.state == JourneyState.FORM_CAPTURE.value
    assert app.form_data["applicant_name"] == "Gotham Bracass"
    assert app.pending_voice_field is None
    assert saved.data.get("next_field") == "date_of_birth"


def test_voice_name_no_discards_and_reasks(db_session: Session, journey: JourneyService):
    app_id, token = _auth_to_form(journey)
    journey.handle_message(
        app_id,
        token,
        "Gotham Bracass",
        trace_id="name-no",
        input_modality="voice",
    )
    declined = journey.handle_message(app_id, token, "NO", trace_id="name-no")
    app = _app(journey, app_id)
    db_session.refresh(app)
    assert declined.state == JourneyState.FORM_CAPTURE.value
    assert "applicant_name" not in (app.form_data or {})
    assert app.pending_voice_field is None
    assert app.pending_voice_value is None
    assert declined.data.get("next_field") == "applicant_name"
    assert "again" in (declined.message or "").lower()


def test_live_stale_confirmation_go_to_bracass_then_leo(
    db_session: Session,
    journey: JourneyService,
    gateway: DataBoundaryGateway,
):
    """Exact live reproduction: STT 'Go to Bracass' → NO → 'Leo' must confirm Leo."""
    app_id, token = _auth_to_form(journey)
    tts = _RecordingTTS()
    orch = ChannelOrchestrator(
        db_session, gateway=gateway, journey=journey, tts=tts
    )

    def voice(transcript: str):
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

    first = voice("Go to Bracass")
    assert first.state == JourneyState.FIELD_CONFIRMATION.value
    assert first.data.get("proposed_value") == "Go to Bracass"
    assert "Go to Bracass" in (first.message or "")

    declined = voice("No, it's not correct.")
    assert declined.state == JourneyState.FORM_CAPTURE.value
    app = _app(journey, app_id)
    db_session.refresh(app)
    assert "applicant_name" not in (app.form_data or {})
    assert app.pending_voice_field is None
    assert app.pending_voice_value is None
    assert "Go to Bracass" not in (declined.message or "")

    second = voice("Leo")
    assert second.state == JourneyState.FIELD_CONFIRMATION.value
    assert second.data.get("proposed_value") == "Leo"
    assert "Leo" in (second.message or "")
    assert "Go to Bracass" not in (second.message or "")
    assert tts.spoken[-1] == t("field_confirm_heard", "en", value="Leo")
    assert "Go to Bracass" not in tts.spoken[-1]


def test_replacement_utterance_while_confirming_replaces_pending(
    db_session: Session, journey: JourneyService
):
    """Speaking a new value during confirmation must not re-emit the old pending."""
    app_id, token = _auth_to_form(journey)
    journey.handle_message(
        app_id, token, "Go to Bracass", trace_id="replace", input_modality="voice"
    )
    replaced = journey.handle_message(
        app_id, token, "Leo", trace_id="replace", input_modality="voice"
    )
    app = _app(journey, app_id)
    assert replaced.state == JourneyState.FIELD_CONFIRMATION.value
    assert replaced.data.get("proposed_value") == "Leo"
    assert "Go to Bracass" not in (replaced.message or "")
    assert app.pending_voice_value == "Leo"
    assert "applicant_name" not in (app.form_data or {})


def test_multiple_retries_only_final_yes_commits(db_session: Session, journey: JourneyService):
    app_id, token = _auth_to_form(journey)
    sequence = [
        ("Value A", "NO"),
        ("Value B", "NO"),
        ("Value C", "YES"),
    ]
    for spoken, decision in sequence:
        pending = journey.handle_message(
            app_id, token, spoken, trace_id="retries", input_modality="voice"
        )
        assert pending.state == JourneyState.FIELD_CONFIRMATION.value
        assert pending.data.get("proposed_value") == spoken
        assert pending.message == t("field_confirm_heard", "en", value=spoken)
        reply = journey.handle_message(app_id, token, decision, trace_id="retries")
        if decision == "NO":
            assert reply.state == JourneyState.FORM_CAPTURE.value
            app = _app(journey, app_id)
            assert "applicant_name" not in (app.form_data or {})
            assert app.pending_voice_field is None
            assert app.pending_voice_value is None

    app = _app(journey, app_id)
    assert app.form_data["applicant_name"] == "Value C"
    assert app.pending_voice_field is None
    assert app.pending_voice_value is None


@pytest.mark.parametrize(
    ("field_values", "retry_field", "value_a", "value_b"),
    [
        ([], "applicant_name", "Alpha Name", "Beta Name"),
        (
            [("Alpha Name", True), ("YES", False)],
            "date_of_birth",
            "01/01/1990",
            "02/02/1991",
        ),
        (
            [
                ("Alpha Name", True),
                ("YES", False),
                ("01/01/1990", True),
                ("YES", False),
            ],
            "mobile_number",
            "9876543210",
            "9123456780",
        ),
        (
            [
                ("Alpha Name", True),
                ("YES", False),
                ("01/01/1990", True),
                ("YES", False),
                ("9876543210", True),
                ("YES", False),
            ],
            "address",
            "Old Street",
            "New Street",
        ),
        (
            [
                ("Alpha Name", True),
                ("YES", False),
                ("01/01/1990", True),
                ("YES", False),
                ("9876543210", True),
                ("YES", False),
                ("Old Street", True),
                ("YES", False),
            ],
            "district",
            "Old District",
            "New District",
        ),
        (
            [
                ("Alpha Name", True),
                ("YES", False),
                ("01/01/1990", True),
                ("YES", False),
                ("9876543210", True),
                ("YES", False),
                ("Old Street", True),
                ("YES", False),
                ("Old District", True),
                ("YES", False),
            ],
            "annual_income",
            "100000",
            "250000",
        ),
        (
            [
                ("Alpha Name", True),
                ("YES", False),
                ("01/01/1990", True),
                ("YES", False),
                ("9876543210", True),
                ("YES", False),
                ("Old Street", True),
                ("YES", False),
                ("Old District", True),
                ("YES", False),
                ("100000", True),
                ("YES", False),
            ],
            "income_source",
            "Farming",
            "Salary",
        ),
    ],
)
def test_no_then_new_value_generic_for_all_fields(
    db_session: Session,
    journey: JourneyService,
    field_values: list[tuple[str, bool]],
    retry_field: str,
    value_a: str,
    value_b: str,
):
    app_id, token = _auth_to_form(journey)
    for val, voice in field_values:
        journey.handle_message(
            app_id,
            token,
            val,
            trace_id="generic-retry",
            input_modality="voice" if voice else None,
        )

    pending_a = journey.handle_message(
        app_id, token, value_a, trace_id="generic-retry", input_modality="voice"
    )
    assert pending_a.state == JourneyState.FIELD_CONFIRMATION.value
    assert pending_a.data.get("field") == retry_field
    assert pending_a.data.get("proposed_value") == value_a

    declined = journey.handle_message(app_id, token, "NO", trace_id="generic-retry")
    app = _app(journey, app_id)
    assert declined.state == JourneyState.FORM_CAPTURE.value
    assert retry_field not in (app.form_data or {})
    assert app.pending_voice_field is None
    assert app.pending_voice_value is None

    pending_b = journey.handle_message(
        app_id, token, value_b, trace_id="generic-retry", input_modality="voice"
    )
    assert pending_b.state == JourneyState.FIELD_CONFIRMATION.value
    assert pending_b.data.get("proposed_value") == value_b
    assert value_a not in (pending_b.message or "")
    assert app.pending_voice_value == value_b


def test_voice_dob_normalized_then_confirmed(db_session: Session, journey: JourneyService):
    app_id, token = _auth_to_form(journey)
    journey.handle_message(
        app_id, token, "Lakshmi Devi", trace_id="dob", input_modality="voice"
    )
    journey.handle_message(app_id, token, "YES", trace_id="dob")
    pending = journey.handle_message(
        app_id, token, "12/04/1995", trace_id="dob", input_modality="voice"
    )
    assert pending.state == JourneyState.FIELD_CONFIRMATION.value
    assert pending.data.get("proposed_value") == "12/04/1995"
    saved = journey.handle_message(app_id, token, "YES", trace_id="dob")
    app = _app(journey, app_id)
    assert app.form_data["date_of_birth"] == "12/04/1995"
    assert saved.data.get("next_field") == "mobile_number"


def test_voice_mobile_spoken_digits_confirmed(db_session: Session, journey: JourneyService):
    app_id, token = _auth_to_form(journey)
    for val, voice in [
        ("Lakshmi Devi", True),
        ("YES", False),
        ("12/04/1995", True),
        ("YES", False),
    ]:
        journey.handle_message(
            app_id,
            token,
            val,
            trace_id="mobile",
            input_modality="voice" if voice else None,
        )
    spoken = "nine eight seven six five four three two one zero"
    pending = journey.handle_message(
        app_id, token, spoken, trace_id="mobile", input_modality="voice"
    )
    assert pending.state == JourneyState.FIELD_CONFIRMATION.value
    assert pending.data.get("proposed_value") == "9876543210"
    journey.handle_message(app_id, token, "YES", trace_id="mobile")
    app = _app(journey, app_id)
    assert app.form_data["mobile_number"] == "9876543210"


def test_invalid_voice_value_skips_confirmation(db_session: Session, journey: JourneyService):
    app_id, token = _auth_to_form(journey)
    bad = journey.handle_message(
        app_id, token, "A", trace_id="bad-name", input_modality="voice"
    )
    assert bad.state == JourneyState.FORM_CAPTURE.value
    assert bad.error == "validation_failed"
    assert bad.data.get("field") == "applicant_name"
    app = _app(journey, app_id)
    assert "applicant_name" not in (app.form_data or {})
    assert app.current_state == JourneyState.FORM_CAPTURE.value
    assert app.pending_voice_field is None


def test_prior_fields_unchanged_during_confirmation(
    db_session: Session, journey: JourneyService
):
    app_id, token = _auth_to_form(journey)
    journey.handle_message(
        app_id, token, "Lakshmi Devi", trace_id="prior", input_modality="voice"
    )
    journey.handle_message(app_id, token, "YES", trace_id="prior")
    journey.handle_message(
        app_id, token, "12/04/1995", trace_id="prior", input_modality="voice"
    )
    app = _app(journey, app_id)
    assert app.form_data["applicant_name"] == "Lakshmi Devi"
    assert app.current_state == JourneyState.FIELD_CONFIRMATION.value
    assert "date_of_birth" not in app.form_data


def test_manual_text_saves_without_confirmation(db_session: Session, journey: JourneyService):
    app_id, token = _auth_to_form(journey)
    reply = journey.handle_message(app_id, token, "Lakshmi Devi", trace_id="manual")
    app = _app(journey, app_id)
    assert reply.state == JourneyState.FORM_CAPTURE.value
    assert app.current_state == JourneyState.FORM_CAPTURE.value
    assert app.form_data["applicant_name"] == "Lakshmi Devi"
    assert app.pending_voice_field is None


def test_generic_confirmation_for_address_and_district(
    db_session: Session, journey: JourneyService
):
    app_id, token = _auth_to_form(journey)
    values = [
        ("Lakshmi Devi", False),
        ("12/04/1995", False),
        ("9876543210", False),
    ]
    for val, voice in values:
        journey.handle_message(
            app_id,
            token,
            val,
            trace_id="generic",
            input_modality="voice" if voice else None,
        )
    for field_value, field_name in [
        ("12 Temple Street", "address"),
        ("Hyderabad", "district"),
    ]:
        pending = journey.handle_message(
            app_id,
            token,
            field_value,
            trace_id="generic",
            input_modality="voice",
        )
        assert pending.state == JourneyState.FIELD_CONFIRMATION.value
        assert pending.data.get("field") == field_name
        journey.handle_message(app_id, token, "YES", trace_id="generic")
    app = _app(journey, app_id)
    assert app.form_data["address"] == "12 Temple Street"
    assert app.form_data["district"] == "Hyderabad"


@pytest.mark.parametrize(
    ("spoken", "expected_token"),
    [
        ("yeah", "YES"),
        ("that's correct", "YES"),
        ("nope", "NO"),
        ("try again", "NO"),
    ],
)
def test_nlu_confirmation_variants_via_orchestrator(
    db_session: Session,
    journey: JourneyService,
    gateway: DataBoundaryGateway,
    spoken: str,
    expected_token: str,
):
    app_id, token = _auth_to_form(journey)
    journey.handle_message(
        app_id, token, "Gotham Bracass", trace_id="nlu", input_modality="voice"
    )
    orch = ChannelOrchestrator(
        db_session, gateway=gateway, journey=journey, tts=MockTTSProvider()
    )
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": "text",
            "text": spoken,
        },
    )
    app = _app(journey, app_id)
    if expected_token == "YES":
        assert app.form_data.get("applicant_name") == "Gotham Bracass"
        assert reply.state == JourneyState.FORM_CAPTURE.value
    else:
        assert "applicant_name" not in (app.form_data or {})
        assert reply.data.get("next_field") == "applicant_name"


def test_localized_confirmation_prompts_hindi_and_kannada(
    db_session: Session, journey: JourneyService
):
    for lang in ("hi", "kn"):
        app_id, token = _auth_to_form(journey, lang=lang)
        pending = journey.handle_message(
            app_id,
            token,
            "Test Name",
            trace_id=f"lang-{lang}",
            input_modality="voice",
        )
        expected = t("field_confirm_heard", lang, value="Test Name")
        assert pending.message == expected
        assert pending.prompt == expected
        label = field_label_for_confirm("applicant_name", lang)
        retry = journey.handle_message(app_id, token, "NO", trace_id=f"lang-{lang}")
        assert label in (retry.message or "")


def test_orchestrator_voice_generates_tts_for_confirmation(
    db_session: Session,
    journey: JourneyService,
    gateway: DataBoundaryGateway,
):
    app_id, token = _auth_to_form(journey)
    orch = ChannelOrchestrator(
        db_session, gateway=gateway, journey=journey, tts=MockTTSProvider()
    )
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": "voice",
            "transcript": "Gotham Bracass",
            "language": "en",
        },
    )
    assert reply.state == JourneyState.FIELD_CONFIRMATION.value
    assert reply.audio_b64
    assert "Gotham Bracass" in (reply.message or reply.prompt or "")


class _RecordingTTS(MockTTSProvider):
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def synthesize(self, text: str, *, language: str = "en"):
        self.spoken.append(text)
        return super().synthesize(text, language=language)


def _reach_mobile_confirmation(
    journey: JourneyService, app_id: str, token: str
) -> None:
    for val, voice in [
        ("Lakshmi Devi", True),
        ("YES", False),
        ("12/04/1995", True),
        ("YES", False),
    ]:
        journey.handle_message(
            app_id,
            token,
            val,
            trace_id="mobile-tts",
            input_modality="voice" if voice else None,
        )


def test_mobile_confirmation_tts_speaks_digits_ui_keeps_compact(
    db_session: Session,
    journey: JourneyService,
    gateway: DataBoundaryGateway,
):
    app_id, token = _auth_to_form(journey)
    _reach_mobile_confirmation(journey, app_id, token)
    tts = _RecordingTTS()
    orch = ChannelOrchestrator(
        db_session, gateway=gateway, journey=journey, tts=tts
    )
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": "voice",
            "transcript": "7 2 0 4 6 0 9 1 5 5",
            "language": "en",
        },
    )
    assert reply.state == JourneyState.FIELD_CONFIRMATION.value
    assert reply.data.get("proposed_value") == "7204609155"
    # Chat / API message stays compact.
    assert "7204609155" in (reply.message or "")
    assert "7 2 0 4 6 0 9 1 5 5" not in (reply.message or "")
    # Spoken TTS uses digit-separated speech.
    assert tts.spoken, "expected TTS synthesize call"
    spoken = tts.spoken[-1]
    assert "7 2 0 4 6 0 9 1 5 5" in spoken
    assert "7204609155" not in spoken
    expected = t(
        "field_confirm_heard", "en", value="7 2 0 4 6 0 9 1 5 5"
    )
    assert spoken == expected


def test_name_confirmation_tts_unchanged(
    db_session: Session,
    journey: JourneyService,
    gateway: DataBoundaryGateway,
):
    app_id, token = _auth_to_form(journey)
    tts = _RecordingTTS()
    orch = ChannelOrchestrator(
        db_session, gateway=gateway, journey=journey, tts=tts
    )
    reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": "voice",
            "transcript": "Gotham Bracass",
            "language": "en",
        },
    )
    assert reply.state == JourneyState.FIELD_CONFIRMATION.value
    assert "Gotham Bracass" in (reply.message or "")
    assert tts.spoken[-1] == t("field_confirm_heard", "en", value="Gotham Bracass")
