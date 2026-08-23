"""Catalogue-driven service selection — voice and button share service codes."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.nlu.provider import LocalRuleNLUProvider
from app.services.catalogue import (
    get_service_catalogue,
    load_service_definition,
    resolve_services_dir,
)
from app.services.journey import JourneyService
from app.services.service_selection import (
    ServiceSelectionStatus,
    resolve_service_utterance,
)
from app.services.state_machine import JourneyState
from app.speech.stt import MockSTTProvider
from app.speech.tts import MockTTSProvider
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def _clear_catalogue_cache():
    get_service_catalogue.cache_clear()
    yield
    get_service_catalogue.cache_clear()


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
def journey(db_session: Session, identity: MockIdentityProvider, gateway: DataBoundaryGateway):
    return JourneyService(db_session, identity=identity, gateway=gateway)


@pytest.fixture
def orch(
    db_session: Session,
    identity: MockIdentityProvider,
    gateway: DataBoundaryGateway,
    journey: JourneyService,
) -> ChannelOrchestrator:
    return ChannelOrchestrator(
        db_session,
        gateway=gateway,
        journey=journey,
        stt=MockSTTProvider(),
        tts=MockTTSProvider(),
        nlu=LocalRuleNLUProvider(),
    )


def _to_service_select(journey: JourneyService) -> tuple[str, str]:
    start = journey.start(channel="web")
    app_id, token = start.application_id, start.access_token
    assert token
    for step in ["en", "9876543210", "123456", "YES"]:
        journey.handle_message(app_id, token, step, trace_id="svc-select")
    return app_id, token


@pytest.mark.parametrize(
    ("utterance", "language"),
    [
        ("income certificate", "en"),
        ("Income Certificate", "en"),
        ("Income Certificate.", "en"),
        ("apply for income certificate", "en"),
        ("I want an income certificate", "en"),
        ("INCOME_CERTIFICATE", "en"),
        ("income certificate", "hi"),
        ("आय प्रमाण पत्र", "hi"),
        ("आय प्रमाण पत्र के लिए आवेदन करना है", "hi"),
        ("मैं आय प्रमाण पत्र के लिए आवेदन करना चाहता हूँ", "hi"),
        ("income certificate", "kn"),
        ("ಆದಾಯ ಪ್ರಮಾಣ ಪತ್ರ", "kn"),
        ("ಆದಾಯ ಪ್ರಮಾಣ ಪತ್ರಕ್ಕೆ ಅರ್ಜಿ ಸಲ್ಲಿಸಬೇಕು", "kn"),
    ],
)
def test_resolve_income_certificate_utterances(utterance: str, language: str):
    result = resolve_service_utterance(utterance, language=language)
    assert result.status == ServiceSelectionStatus.MATCHED
    assert result.service_code == "INCOME_CERTIFICATE"


@pytest.mark.parametrize(
    "utterance",
    [
        "certificate",
        "unknown service please",
        "domicile",
    ],
)
def test_unknown_service_utterances(utterance: str):
    result = resolve_service_utterance(utterance, language="en")
    assert result.status == ServiceSelectionStatus.NONE


def test_exact_display_name_and_alias_and_phrase(journey: JourneyService):
    app_id, token = _to_service_select(journey)
    reply = journey.handle_message(app_id, token, "Income Certificate", trace_id="svc")
    assert reply.state == JourneyState.FORM_CAPTURE.value
    assert reply.message == "Starting Income Certificate."
    assert reply.data.get("service_code") == "INCOME_CERTIFICATE"

    app_id2, token2 = _to_service_select(journey)
    reply = journey.handle_message(
        app_id2, token2, "apply for income certificate", trace_id="svc"
    )
    assert reply.state == JourneyState.FORM_CAPTURE.value
    assert reply.data.get("service_code") == "INCOME_CERTIFICATE"


def test_yes_selects_only_catalogue_service(journey: JourneyService):
    app_id, token = _to_service_select(journey)
    reply = journey.handle_message(app_id, token, "YES", trace_id="svc-yes")
    assert reply.state == JourneyState.FORM_CAPTURE.value
    assert reply.data.get("service_code") == "INCOME_CERTIFICATE"


def test_voice_and_button_share_service_code(orch: ChannelOrchestrator):
    start = orch.start(channel="web")
    app_id, token = start.application_id, start.access_token

    def voice(transcript: str, language: str = "en"):
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

    for step in ["en", "9876543210", "123456", "yes"]:
        voice(step)

    voice_reply = voice("apply for income certificate")
    assert voice_reply.state == JourneyState.FORM_CAPTURE.value
    assert voice_reply.data.get("service_code") == "INCOME_CERTIFICATE"

    start2 = orch.start(channel="web")
    app_id2, token2 = start2.application_id, start2.access_token
    for step in ["en", "9876543210", "123456", "yes"]:
        orch.process_channel_payload(
            "web",
            {
                "application_id": app_id2,
                "access_token": token2,
                "session_ref": token2,
                "modality": "voice",
                "language": "en",
                "transcript": step,
            },
        )
    button_reply = orch.process_channel_payload(
        "web",
        {
            "application_id": app_id2,
            "access_token": token2,
            "session_ref": token2,
            "modality": "text",
            "text": "INCOME_CERTIFICATE",
            "language": "en",
        },
    )
    assert button_reply.state == JourneyState.FORM_CAPTURE.value
    assert button_reply.data.get("service_code") == "INCOME_CERTIFICATE"


def test_ambiguous_service_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    income = {
        "service_code": "INCOME_CERTIFICATE",
        "display_name": "Income Certificate",
        "selection": {
            "aliases": {"en": ["certificate"]},
        },
        "fields": [{"name": "applicant_name", "type": "string", "required": True}],
        "documents": [],
    }
    domicile = {
        "service_code": "DOMICILE_CERTIFICATE",
        "display_name": "Domicile Certificate",
        "selection": {
            "aliases": {"en": ["certificate"]},
        },
        "fields": [{"name": "applicant_name", "type": "string", "required": True}],
        "documents": [],
    }
    (tmp_path / "income.yaml").write_text(yaml.dump(income), encoding="utf-8")
    (tmp_path / "domicile.yaml").write_text(yaml.dump(domicile), encoding="utf-8")
    monkeypatch.setattr("app.services.catalogue.resolve_services_dir", lambda: tmp_path)
    get_service_catalogue.cache_clear()

    result = resolve_service_utterance("certificate", language="en")
    assert result.status == ServiceSelectionStatus.AMBIGUOUS
    assert set(result.matches) == {"DOMICILE_CERTIFICATE", "INCOME_CERTIFICATE"}


def test_new_service_from_configuration_without_python_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    income_path = resolve_services_dir() / "income_certificate.yaml"
    (tmp_path / "income_certificate.yaml").write_text(
        income_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    domicile = {
        "service_code": "DOMICILE_CERTIFICATE",
        "display_name": "Domicile Certificate",
        "selection": {
            "aliases": {
                "en": ["domicile", "domicile certificate"],
            },
            "spoken_phrases": {
                "en": [
                    "I want a domicile certificate",
                    "apply for domicile certificate",
                ],
            },
        },
        "fields": [{"name": "applicant_name", "type": "string", "required": True}],
        "documents": [],
    }
    (tmp_path / "domicile_certificate.yaml").write_text(
        yaml.dump(domicile), encoding="utf-8"
    )
    monkeypatch.setattr("app.services.catalogue.resolve_services_dir", lambda: tmp_path)
    get_service_catalogue.cache_clear()

    catalogue = get_service_catalogue()
    assert "DOMICILE_CERTIFICATE" in catalogue
    domicile_def = load_service_definition(tmp_path / "domicile_certificate.yaml")
    assert domicile_def.service_code == "DOMICILE_CERTIFICATE"

    for utterance in [
        "domicile certificate",
        "apply for domicile certificate",
        "I want a domicile certificate",
        "DOMICILE_CERTIFICATE",
    ]:
        result = resolve_service_utterance(utterance, language="en", catalogue=catalogue)
        assert result.status == ServiceSelectionStatus.MATCHED, utterance
        assert result.service_code == "DOMICILE_CERTIFICATE", utterance
