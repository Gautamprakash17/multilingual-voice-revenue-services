"""Channel orchestrator — adapters → envelope → speech/NLU → journey → TTS.

Channels never touch the state machine directly.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.boundary.classification import Classification
from app.boundary.gateway import DataBoundaryGateway, GatewayRequest
from app.channels.adapters import get_adapter
from app.channels.envelope import MessageEnvelope, Modality, validate_envelope
from app.models.application import Application, ConversationSession
from app.nlu.provider import NLUProvider, get_nlu_provider
from app.platform.audit import write_audit_event
from app.platform.metrics import get_metrics, timed_ms
from app.services.i18n import field_prompt, t
from app.services.journey import JourneyReply, JourneyService
from app.services.state_machine import JourneyState
from app.speech.language import resolve_language
from app.speech.stt import STTProvider, decode_audio_b64, get_stt_provider
from app.speech.tts import TTSProvider, get_tts_provider


@dataclass
class ChannelReply:
    application_id: str
    state: str
    message: str
    prompt: str | None = None
    access_token: str | None = None
    language: str | None = None
    channel: str | None = None
    transcript: str | None = None
    intent: str | None = None
    audio_b64: str | None = None
    audio_mime: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    expected_format: str | None = None


class ChannelOrchestrator:
    def __init__(
        self,
        db: Session,
        *,
        gateway: DataBoundaryGateway | None = None,
        stt: STTProvider | None = None,
        tts: TTSProvider | None = None,
        nlu: NLUProvider | None = None,
        journey: JourneyService | None = None,
    ) -> None:
        self.db = db
        self.gateway = gateway
        self.stt = stt or get_stt_provider()
        self.tts = tts or get_tts_provider()
        self.nlu = nlu or get_nlu_provider()
        self.journey = journey or JourneyService(db, gateway=gateway)
        self.metrics = get_metrics()

    def _audit(self, event_type: str, *, trace_id: str | None, metadata: dict[str, Any]) -> None:
        write_audit_event(
            self.db,
            event_type=event_type,
            classification=Classification.RESTRICTED.value,
            trace_id=trace_id,
            metadata=metadata,
        )

    def _assert_no_cloud(self, purpose: str, trace_id: str | None) -> None:
        if self.gateway is None:
            return
        result = self.gateway.evaluate(
            GatewayRequest(
                payload={"keys": ["voice_or_text"]},
                classification=Classification.RESTRICTED,
                destination="cloud",
                purpose=purpose,
                approved=False,
                trace_id=trace_id,
            ),
            db=self.db,
        )
        if result.allowed:
            raise RuntimeError("Boundary violation: restricted channel payload allowed to cloud")

    def process_envelope(self, envelope: MessageEnvelope) -> ChannelReply:
        """Main entry: validated envelope → journey → localized reply (+ optional TTS)."""
        self._assert_no_cloud("channel_ingress", envelope.trace_id)
        metrics = self.metrics

        if not envelope.session_ref or not envelope.application_ref:
            raise ValueError("application_ref and session_ref are required")

        app = self.journey._get_app_by_ref(envelope.application_ref)
        session = self.journey._get_session(app, envelope.session_ref)

        # Voice → STT (local only)
        text = envelope.text_payload()
        transcript_for_client: str | None = None
        if envelope.modality == Modality.VOICE:
            self._audit(
                "VOICE_INPUT_RECEIVED",
                trace_id=envelope.trace_id,
                metadata={
                    "channel": envelope.channel.value,
                    "application_ref": app.application_id,
                    "has_audio": bool(envelope.content.get("audio_b64")),
                    "has_client_transcript": bool(envelope.content.get("transcript")),
                },
            )
            if envelope.content.get("transcript"):
                text = str(envelope.content["transcript"]).strip()
                transcript_for_client = text
                stt_ok = bool(text)
                metrics.record_stt(stt_ok)
            elif envelope.content.get("audio_b64"):
                t0 = timed_ms()
                try:
                    audio = decode_audio_b64(str(envelope.content["audio_b64"]))
                    # Prove restricted audio cannot go to cloud
                    self._assert_no_cloud("stt", envelope.trace_id)
                    stt = self.stt.transcribe(audio, language_hint=app.language)
                    text = stt.transcript
                    transcript_for_client = text
                    metrics.record_stt(True, timed_ms() - t0)
                    self._audit(
                        "STT_COMPLETED",
                        trace_id=envelope.trace_id,
                        metadata={
                            "provider": stt.provider,
                            "confidence": stt.confidence,
                            "language": stt.language,
                            "application_ref": app.application_id,
                            "transcript_chars": len(text),
                        },
                    )
                except Exception:
                    metrics.record_stt(False)
                    raise
            else:
                metrics.record_stt(False)
                raise ValueError("voice input missing audio/transcript")

        # Language resolution — do not silently switch on low confidence
        lang_guess = resolve_language(text, app.language)
        language = lang_guess.language
        if app.language is None and language:
            app.language = language

        # NLU (local)
        expected = None
        if JourneyState(app.current_state) in {
            JourneyState.FORM_CAPTURE,
            JourneyState.CORRECTION,
        }:
            expected = app.correcting_field or self.journey._next_missing_field(app)
        nlu = self.nlu.parse(text, expected_field=expected)
        metrics.record_nlu(nlu.confidence >= 0.5)
        self._audit(
            "NLU_COMPLETED",
            trace_id=envelope.trace_id,
            metadata={
                "intent": nlu.intent,
                "confidence": nlu.confidence,
                "slot_keys": sorted(nlu.slots.keys()),
                "application_ref": app.application_id,
                "channel": envelope.channel.value,
            },
        )

        # Map NLU / DTMF into journey text without logging raw content
        journey_text = self._to_journey_text(text, nlu, envelope, expected)
        reply = self.journey.handle_message(
            app.application_id,
            session.access_token,
            journey_text,
            trace_id=envelope.trace_id,
        )
        if reply.state == JourneyState.ESCALATED.value:
            metrics.record_escalation()

        # Localize prompt/message when possible
        localized = self._localize_reply(reply, app.language or language)
        audio_b64 = None
        audio_mime = None
        speak = localized.prompt or localized.message
        if speak and envelope.modality in {Modality.VOICE, Modality.DTMF}:
            self._assert_no_cloud("tts", envelope.trace_id)
            tts = self.tts.synthesize(speak, language=app.language or language or "en")
            audio_b64 = tts.audio_b64
            audio_mime = tts.mime_type
            self._audit(
                "TTS_COMPLETED",
                trace_id=envelope.trace_id,
                metadata={
                    "provider": tts.provider,
                    "text_hash": tts.text_hash,
                    "duration_ms": tts.duration_ms,
                    "application_ref": app.application_id,
                },
            )

        return ChannelReply(
            application_id=localized.application_id,
            state=localized.state,
            message=localized.message,
            prompt=localized.prompt,
            access_token=None,
            language=app.language or language,
            channel=envelope.channel.value,
            transcript=transcript_for_client,
            intent=nlu.intent,
            audio_b64=audio_b64,
            audio_mime=audio_mime,
            data=localized.data,
            error=localized.error,
            expected_format=localized.expected_format,
        )

    def process_channel_payload(self, channel: str, payload: dict[str, Any]) -> ChannelReply:
        adapter = get_adapter(channel)
        envelope = adapter.to_envelope(payload)
        # Re-validate through envelope contract
        envelope = validate_envelope(envelope.model_dump())
        try:
            return self.process_envelope(envelope)
        except Exception:
            self.metrics.record_channel_error()
            raise

    def resume(
        self,
        *,
        application_id: str,
        access_token: str,
        channel: str,
        trace_id: str | None = None,
    ) -> ChannelReply:
        """Continue an existing application on another channel (same token gate)."""
        app = self.journey._get_app_by_ref(application_id)
        # Validate ownership via existing token
        self.journey._get_session(app, access_token)
        new_token = secrets.token_urlsafe(24)
        session = ConversationSession(
            application_id=app.id,
            channel=channel,
            current_state=app.current_state,
            access_token=new_token,
            classification=Classification.RESTRICTED.value,
            last_activity_at=datetime.now(UTC),
        )
        self.db.add(session)
        self.db.flush()
        self.metrics.record_session(channel, app.language)
        self._audit(
            "CHANNEL_SESSION_RESUMED",
            trace_id=trace_id,
            metadata={
                "application_ref": app.application_id,
                "channel": channel,
                "language": app.language,
                "state": app.current_state,
            },
        )
        lang = app.language or "en"
        return ChannelReply(
            application_id=app.application_id,
            state=app.current_state,
            message=t("resume_ok", lang, channel=channel),
            prompt=self._prompt_for_state(app, lang),
            access_token=new_token,
            language=app.language,
            channel=channel,
            data={
                "fields_captured": list((app.form_data or {}).keys()),
                "consent_granted": app.consent_granted,
            },
        )

    def start(self, channel: str = "web", trace_id: str | None = None) -> ChannelReply:
        reply = self.journey.start(channel=channel, trace_id=trace_id)
        self.metrics.record_session(channel, None)
        return ChannelReply(
            application_id=reply.application_id,
            state=reply.state,
            message=t("welcome", "en"),
            prompt=t("language_select", "en"),
            access_token=reply.access_token,
            language=None,
            channel=channel,
            data=reply.data,
        )

    def _to_journey_text(
        self,
        text: str,
        nlu: Any,
        envelope: MessageEnvelope,
        expected: str | None,
    ) -> str:
        if envelope.modality == Modality.DTMF:
            return str(envelope.content.get("dtmf") or text)
        if nlu.intent == "CONFIRM":
            return "CONFIRM"
        if nlu.intent == "CORRECT":
            return "CORRECT"
        if nlu.intent == "ESCALATE":
            return "ESCALATE"
        if nlu.intent == "CONSENT":
            return "YES" if nlu.slots.get("granted") else "NO"
        if expected and expected in nlu.slots:
            return str(nlu.slots[expected])
        for key in (
            "date_of_birth",
            "mobile_number",
            "annual_income",
            "applicant_name",
            "address",
            "district",
            "income_source",
        ):
            if key in nlu.slots:
                return str(nlu.slots[key])
        return text

    def _localize_reply(self, reply: JourneyReply, language: str | None) -> JourneyReply:
        lang = language or "en"
        # Overlay known prompts
        state = reply.state
        prompt = reply.prompt
        message = reply.message
        if state == JourneyState.LANGUAGE_SELECT.value:
            prompt = t("language_select", lang)
            message = t("welcome", lang)
        elif state == JourneyState.AUTHENTICATE.value:
            if reply.prompt and "OTP" in (reply.prompt or "").upper():
                prompt = t("auth_otp", lang)
            else:
                prompt = t("auth_mobile", lang)
        elif state == JourneyState.CONSENT.value:
            prompt = t("consent", lang)
        elif state == JourneyState.SERVICE_SELECT.value:
            message = t("consent_recorded", lang)
            prompt = t("service_select", lang)
        elif state == JourneyState.FORM_CAPTURE.value:
            nxt = (reply.data or {}).get("next_field")
            if nxt:
                prompt = field_prompt(str(nxt), lang)
        elif state == JourneyState.DOCUMENT_CAPTURE.value:
            missing = (reply.data or {}).get("missing_documents") or []
            if missing:
                prompt = t("document_next", lang, code=missing[0])
            else:
                prompt = t("document_prompt", lang)
        elif state == JourneyState.REVIEW_CONFIRM.value:
            prompt = t("review_intro", lang)
            message = t("review_intro", lang)
        elif state == JourneyState.FEE_QUOTE.value:
            fee = (reply.data or {}).get("fee") or {}
            prompt = reply.prompt or "Reply PAY to continue"
            message = reply.message or f"Fee: {fee.get('display', '')}"
        elif state == JourneyState.PAYMENT.value:
            prompt = reply.prompt or "Reply PAY / FAIL / TIMEOUT"
            message = reply.message or prompt
        elif state == JourneyState.PAYMENT_FAILED.value:
            prompt = reply.prompt or "Reply RETRY"
            message = reply.message or "Payment failed. Reply RETRY."
        elif state == JourneyState.CORRECTION.value:
            prompt = t("correction_which", lang)
        elif state == JourneyState.SUBMITTED.value:
            message = t("submitted", lang, application_id=reply.application_id)
        elif state == JourneyState.ESCALATED.value:
            message = t("escalation", lang)
        if reply.error == "validation_failed":
            message = t("validation_failed", lang)
        if reply.error == "consent_declined":
            message = t("consent_declined", lang)
        return JourneyReply(
            application_id=reply.application_id,
            state=reply.state,
            message=message,
            prompt=prompt,
            access_token=reply.access_token,
            data=reply.data,
            error=reply.error,
            expected_format=reply.expected_format,
        )

    def _prompt_for_state(self, app: Application, lang: str) -> str:
        state = JourneyState(app.current_state)
        if state == JourneyState.LANGUAGE_SELECT:
            return t("language_select", lang)
        if state == JourneyState.AUTHENTICATE:
            return t("auth_mobile", lang)
        if state == JourneyState.CONSENT:
            return t("consent", lang)
        if state == JourneyState.SERVICE_SELECT:
            return t("service_select", lang)
        if state == JourneyState.FORM_CAPTURE:
            nxt = self.journey._next_missing_field(app)
            return field_prompt(nxt, lang) if nxt else t("form_complete", lang)
        if state == JourneyState.DOCUMENT_CAPTURE:
            return t("document_prompt", lang)
        if state == JourneyState.REVIEW_CONFIRM:
            return t("review_intro", lang)
        if state == JourneyState.FEE_QUOTE:
            return "Reply PAY to continue to payment"
        if state == JourneyState.PAYMENT:
            return "Reply PAY / FAIL / TIMEOUT"
        if state == JourneyState.PAYMENT_FAILED:
            return "Reply RETRY"
        if state == JourneyState.SUBMITTED:
            return t("application_id_label", lang, application_id=app.application_id)
        return t("welcome", lang)
