"""Catalogue-driven accepted document types + channel document behaviour."""

from __future__ import annotations

import io

import pytest
from app.adapters.identity import MockIdentityProvider, Persona
from app.boundary.gateway import DataBoundaryGateway
from app.channels.orchestrator import ChannelOrchestrator
from app.nlu.provider import LocalRuleNLUProvider
from app.services.catalogue import get_service, get_service_catalogue
from app.services.documents import DocumentValidationError, store_document
from app.services.i18n import document_label, document_type_label, load_translations
from app.services.journey import JourneyService
from app.services.state_machine import JourneyState
from app.speech.stt import MockSTTProvider
from app.speech.tts import MockTTSProvider
from fastapi import UploadFile
from sqlalchemy.orm import Session

from tests.auth_helpers import expand_step


@pytest.fixture(autouse=True)
def _clear_catalogue_cache():
    get_service_catalogue.cache_clear()
    load_translations.cache_clear()
    yield
    get_service_catalogue.cache_clear()
    load_translations.cache_clear()


@pytest.fixture
def identity() -> MockIdentityProvider:
    return MockIdentityProvider(
        [Persona(id="persona-lakshmi", name="Lakshmi Devi", mobile="9876543210")]
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

def test_catalogue_defines_accepted_types_not_hardcoded_only():
    service = get_service("INCOME_CERTIFICATE")
    identity = service.document_by_code("IDENTITY_PROOF")
    assert identity is not None
    codes = {t.code for t in identity.accepted_types}
    assert {"AADHAAR", "PAN", "DRIVING_LICENSE"} <= codes
    address = service.document_by_code("ADDRESS_PROOF")
    assert address is not None
    assert {t.code for t in address.accepted_types} == {"AADHAAR", "DRIVING_LICENSE"}
    income = service.document_by_code("INCOME_PROOF")
    assert income is not None
    assert {t.code for t in income.accepted_types} == {
        "SALARY_SLIP",
        "BANK_STATEMENT",
        "ITR",
    }


@pytest.mark.parametrize("language", ["en", "hi", "kn"])
def test_document_labels_never_expose_internal_codes(language: str):
    service = get_service("INCOME_CERTIFICATE")
    for doc in service.documents:
        label = document_label(doc.code, service, language)
        assert doc.code not in label
        assert "_" not in label or " " in label
        for accepted in doc.accepted_types:
            type_label = document_type_label(accepted.code, service, language)
            assert accepted.code not in type_label or type_label == accepted.label


@pytest.mark.asyncio
async def test_upload_requires_accepted_document_type(
    db_session: Session, journey: JourneyService, tmp_path, monkeypatch
):
    from app.core import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: type("S", (), {"document_storage_path": str(tmp_path)})(),
    )
    start = journey.start(trace_id="dtype")
    app_id, token = start.application_id, start.access_token
    assert token
    for step in ["en", "9876543210", "123456"]:
        journey.handle_message(app_id, token, expand_step(journey.identity, step), trace_id="dtype")
    journey.record_consent(app_id, token, granted=True, trace_id="dtype")
    journey.handle_message(app_id, token, "INCOME_CERTIFICATE", trace_id="dtype")
    for val in [
        "Lakshmi Devi",
        "12/04/1995",
        "9876543210",
        "12 Temple Street",
        "Bengaluru",
        "120000",
        "Agriculture",
    ]:
        journey.handle_message(app_id, token, val, trace_id="dtype")

    service = get_service("INCOME_CERTIFICATE")
    doc = service.document_by_code("IDENTITY_PROOF")
    assert doc
    app = journey._get_app_by_ref(app_id)
    upload = UploadFile(
        filename="identity_proof_ok.pdf",
        file=io.BytesIO(b"%PDF-1.4 ok"),
        headers={"content-type": "application/pdf"},
    )
    with pytest.raises(DocumentValidationError, match="Document type is required"):
        await store_document(
            db_session,
            application_pk=app.id,
            document_def=doc,
            upload=upload,
            actor_id=app.applicant_id,
            trace_id="dtype",
        )

    upload2 = UploadFile(
        filename="identity_proof_ok.pdf",
        file=io.BytesIO(b"%PDF-1.4 ok"),
        headers={"content-type": "application/pdf"},
    )
    with pytest.raises(DocumentValidationError, match="not accepted"):
        await store_document(
            db_session,
            application_pk=app.id,
            document_def=doc,
            upload=upload2,
            actor_id=app.applicant_id,
            trace_id="dtype",
            document_type="PASSPORT",
        )

    upload3 = UploadFile(
        filename="identity_proof_ok.pdf",
        file=io.BytesIO(b"%PDF-1.4 ok"),
        headers={"content-type": "application/pdf"},
    )
    stored = await store_document(
        db_session,
        application_pk=app.id,
        document_def=doc,
        upload=upload3,
        actor_id=app.applicant_id,
        trace_id="dtype",
        document_type="AADHAAR",
    )
    assert stored.record.notes == "document_type=AADHAAR"
    assert stored.verification_outcome == "VERIFIED"
    reply = journey.after_document_upload(app_id, token, trace_id="dtype")
    assert "IDENTITY_PROOF" not in (reply.message or "")
    assert "Identity proof" in (reply.message or "") or "uploaded successfully" in (
        reply.message or ""
    ).lower()


def test_ivr_document_capture_offers_cross_channel_continuation(
    db_session: Session, orch: ChannelOrchestrator
):
    start = orch.start(channel="ivr")
    app_id, token = start.application_id, start.access_token
    assert token

    def ivr(text: str = "", *, dtmf: str | None = None, modality: str = "voice"):
        payload = {
            "application_id": app_id,
            "access_token": token,
            "session_ref": token,
            "modality": modality,
            "language": "en",
        }
        if modality == "voice":
            payload["transcript"] = text
        else:
            payload["dtmf"] = dtmf or text
        return orch.process_channel_payload("ivr", payload)

    for step in ["en", "9876543210", "123456", "yes", "Income Certificate"]:
        ivr(expand_step(orch.journey.identity, step))
    for val in [
        "Lakshmi Devi",
        "12/04/1995",
        "9876543210",
        "12 Temple Street",
        "Bengaluru",
        "120000",
        "Agriculture",
    ]:
        reply = ivr(val)
        if reply.state == JourneyState.FIELD_CONFIRMATION.value:
            reply = ivr("yes")

    assert reply.state == JourneyState.DOCUMENT_CAPTURE.value
    assert "web" in (reply.message or "").lower() or "WhatsApp" in (reply.message or "")
    assert app_id in (reply.message or "")
    assert "IDENTITY_PROOF" not in (reply.message or "")
    assert reply.data.get("continue_on_channels") == ["web", "whatsapp"]

    nudged = ivr("upload now")
    assert nudged.state == JourneyState.DOCUMENT_CAPTURE.value
    assert app_id in (nudged.message or "")
