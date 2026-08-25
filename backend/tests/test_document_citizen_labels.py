"""Citizen-facing document prompts must never expose raw catalogue codes."""

from __future__ import annotations

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.nlu.provider import LocalRuleNLUProvider
from app.services.catalogue import get_service
from app.services.i18n import (
    assert_all_keys_present,
    assert_document_labels_present,
    document_label,
    document_next_prompt,
    supported_language_codes,
)
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
from app.speech.stt import MockSTTProvider
from app.speech.tts import MockTTSProvider
from sqlalchemy.orm import Session

from tests.auth_helpers import expand_step

SERVICE = get_service("INCOME_CERTIFICATE")
INTERNAL_DOC_CODES = tuple(doc.code for doc in SERVICE.documents)


@pytest.fixture
def identity() -> MockIdentityProvider:
    return MockIdentityProvider(
        [Persona(id="persona-lakshmi", name="Lakshmi Devi", mobile="9876543210")]
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


def _assert_no_raw_codes(text: str) -> None:
    for code in INTERNAL_DOC_CODES:
        assert code not in text, f"citizen text exposes internal code {code}: {text!r}"


def test_i18n_bundles_define_document_labels_for_catalogue():
    langs = supported_language_codes()
    assert assert_all_keys_present() == {lang: [] for lang in langs}
    assert assert_document_labels_present(SERVICE) == {lang: [] for lang in langs}


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
@pytest.mark.parametrize("document_code", INTERNAL_DOC_CODES)
def test_document_next_prompt_uses_friendly_name(language: str, document_code: str):
    prompt = document_next_prompt(document_code, SERVICE, language)
    _assert_no_raw_codes(prompt)
    label = document_label(document_code, SERVICE, language)
    assert label in prompt
    assert label != document_code


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
def test_document_labels_differ_by_language(language: str):
    for code in INTERNAL_DOC_CODES:
        localized = document_label(code, SERVICE, language)
        english = document_label(code, SERVICE, "en")
        if language == "en":
            assert localized == english
        else:
            assert localized != english, f"{language}/{code} fell back to English"


def _reach_document_capture(orch: ChannelOrchestrator, language: str) -> tuple[str, str]:
    start = orch.start(channel="web")
    app_id, token = start.application_id, start.access_token
    assert token
    steps = [
        language,
        "9876543210",
        "123456",
        "yes" if language == "en" else ("हाँ" if language == "hi" else "ಹೌದು"),
        "Income Certificate",
    ]
    fields = [
        "Lakshmi Devi",
        "12/04/1995",
        "9876543210",
        "12 Temple Street",
        "Bengaluru",
        "120000",
        "Agriculture",
    ]
    affirm = "yes" if language == "en" else ("हाँ" if language == "hi" else "ಹೌದು")
    for step in steps:
        orch.process_channel_payload(
            "web",
            {
                "application_id": app_id,
                "access_token": token,
                "session_ref": token,
                "modality": "voice",
                "language": language,
                "transcript": expand_step(orch.journey.identity, step),
            },
        )
    last = None
    for value in fields:
        orch.process_channel_payload(
            "web",
            {
                "application_id": app_id,
                "access_token": token,
                "session_ref": token,
                "modality": "voice",
                "language": language,
                "transcript": value,
            },
        )
        last = orch.process_channel_payload(
            "web",
            {
                "application_id": app_id,
                "access_token": token,
                "session_ref": token,
                "modality": "voice",
                "language": language,
                "transcript": affirm,
            },
        )
    assert last is not None
    assert last.state == JourneyState.DOCUMENT_CAPTURE.value
    return app_id, token, last


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
def test_document_capture_prompt_is_friendly(orch: ChannelOrchestrator, language: str):
    _, _, reply = _reach_document_capture(orch, language)
    citizen_text = f"{reply.message or ''} {reply.prompt or ''}"
    _assert_no_raw_codes(citizen_text)
    missing = reply.data.get("missing_documents") or []
    assert missing[0] == "IDENTITY_PROOF"


def test_missing_documents_data_keeps_internal_codes(orch: ChannelOrchestrator):
    _, _, reply = _reach_document_capture(orch, "en")
    assert "IDENTITY_PROOF" in reply.data.get("missing_documents", [])
