"""Channel orchestrator — adapters → envelope → speech/NLU → journey → TTS.

Channels never touch the state machine directly.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.boundary.classification import Classification
from app.boundary.gateway import DataBoundaryGateway, GatewayRequest
from app.channels.adapters import get_adapter
from app.channels.envelope import Channel, MessageEnvelope, Modality, validate_envelope
from app.models.application import Application, ConversationSession
from app.nlu.consent import parse_consent_response
from app.nlu.provider import NLUProvider, get_nlu_provider
from app.platform.audit import write_audit_event
from app.platform.metrics import get_metrics, timed_ms
from app.services.i18n import (
    document_label,
    document_next_prompt,
    document_reupload_prompt,
    field_label_for_confirm,
    field_prompt,
    join_prompt_parts,
    language_select_ivr_prompt,
    language_select_prompt,
    numbered_field_list,
    service_select_ivr_prompt,
    t,
)
from app.services.journey import JourneyReply, JourneyService
from app.services.languages import get_language_catalog
from app.services.state_machine import JourneyState, ProcessingStatus
from app.speech.digits import (
    DIGIT_SPEECH_CONFIRM_FIELDS,
    speech_value_for_confirmation,
)
from app.speech.language import resolve_language, resolve_language_choice
from app.speech.stt import STTProvider, decode_audio_b64, get_stt_provider
from app.speech.tts import TTSProvider, get_tts_provider

_PAYMENT_STATES = frozenset(
    {
        JourneyState.FEE_QUOTE.value,
        JourneyState.PAYMENT.value,
        JourneyState.PAYMENT_FAILED.value,
    }
)

# Errors a citizen can recover from by speaking again — the re-prompt must be spoken,
# otherwise a voice-only caller is left with silence.
_SPEAK_ON_ERROR = frozenset(
    {
        "unknown_mobile",
        "invalid_otp",
        "otp_expired",
        "otp_max_attempts",
        "validation_failed",
        "invalid_language",
        "language_ambiguous",
        "consent_unclear",
        "unknown_service",
        "service_select_ambiguous",
        "reply_CONFIRM_or_CORRECT",
        "reply_PAY_or_CORRECT",
        "payment_failed",
        "payment_timeout",
        "no_speech",
        "registration_name_required",
    }
)


def _fee_display(reply: JourneyReply) -> tuple[str, str]:
    fee = (reply.data or {}).get("fee") or {}
    amount_paise = fee.get("amount_paise") or 0
    currency = fee.get("currency") or "INR"
    return f"{amount_paise / 100:.2f}", str(currency)


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
            stt_result = None
            catalog = get_language_catalog()
            language_hint = catalog.stt_code(envelope.language or app.language) or (
                envelope.language or app.language
            )
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
                    stt_result = self.stt.transcribe(audio, language_hint=language_hint)
                    text = (stt_result.transcript or "").strip()
                    transcript_for_client = text or None
                    if text:
                        metrics.record_stt(True, timed_ms() - t0)
                    else:
                        metrics.record_stt(False, timed_ms() - t0)
                    self._audit(
                        "STT_COMPLETED",
                        trace_id=envelope.trace_id,
                        metadata={
                            "provider": stt_result.provider,
                            "confidence": stt_result.confidence,
                            "language": stt_result.language or language_hint,
                            "application_ref": app.application_id,
                            "transcript_chars": len(text),
                            "recognized": bool(text),
                            "audio_bytes": len(audio),
                        },
                    )
                except Exception:
                    metrics.record_stt(False)
                    raise
            else:
                metrics.record_stt(False)
                raise ValueError("voice input missing audio/transcript")

            if not (text or "").strip():
                lang = envelope.language or app.language or "en"
                provider = stt_result.provider if stt_result else self.stt.name
                if provider == "mock-stt":
                    message = (
                        "Your voice was recorded locally, but live speech recognition needs "
                        "the local STT model (faster-whisper). Type your reply and press Send, "
                        "or type your words first and press Speak for the mock fallback."
                    )
                else:
                    message = (
                        "I couldn't understand the recording. Please speak clearly in your "
                        "selected language and try again."
                    )
                prompt = self._prompt_for_state(app, lang)
                stt_data: dict[str, Any] = {
                    "stt_mode": "unrecognized",
                    "stt_provider": provider,
                    "language_hint": language_hint,
                    "recovery": "retry_or_type",
                }
                if getattr(app, "auth_step", None):
                    stt_data["auth_step"] = app.auth_step
                if JourneyState(app.current_state) == JourneyState.FORM_CAPTURE:
                    nxt = self.journey._next_missing_field(app)
                    if nxt:
                        stt_data["next_field"] = nxt
                        field_def = self.journey.service.field_by_name(nxt)
                        if envelope.channel == Channel.IVR and field_def:
                            ivr_prompt = self._ivr_numeric_field_prompt(
                                field_def, lang
                            )
                            if ivr_prompt:
                                prompt = ivr_prompt
                return ChannelReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=message,
                    prompt=prompt,
                    language=lang,
                    channel=envelope.channel.value,
                    transcript=None,
                    error="stt_unrecognized",
                    data=stt_data,
                )

        # Language resolution — do not silently switch on low confidence
        lang_guess = resolve_language(text, app.language)
        language = lang_guess.language
        if (
            app.language is None
            and language
            and JourneyState(app.current_state) != JourneyState.LANGUAGE_SELECT
        ):
            app.language = language

        # NLU (local)
        expected = None
        current_state = JourneyState(app.current_state)
        if current_state == JourneyState.FIELD_CONFIRMATION:
            expected = "__field_confirm__"
        elif current_state == JourneyState.CONSENT:
            expected = "__consent__"
        elif current_state in {
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
        journey_text = self._to_journey_text(text, nlu, envelope, expected, app)
        if JourneyState(app.current_state) == JourneyState.LANGUAGE_SELECT:
            choice = resolve_language_choice(journey_text)
            if choice.code:
                journey_text = choice.code
        reply = self.journey.handle_message(
            app.application_id,
            session.access_token,
            journey_text,
            trace_id=envelope.trace_id,
            input_modality=envelope.modality.value,
        )
        if reply.state == JourneyState.ESCALATED.value:
            metrics.record_escalation()

        # Localize prompt/message when possible
        localized = self._localize_reply(reply, app.language or language)
        if envelope.channel == Channel.IVR:
            if localized.state == JourneyState.LANGUAGE_SELECT.value:
                localized = replace(localized, prompt=language_select_ivr_prompt())
            elif localized.state == JourneyState.AUTHENTICATE.value:
                localized = self._ivr_authenticate_prompts(
                    localized, app.language or language
                )
            elif localized.state == JourneyState.FIELD_CONFIRMATION.value:
                localized = self._ivr_field_confirmation_prompts(
                    localized, app.language or language
                )
            elif localized.state in {
                JourneyState.FORM_CAPTURE.value,
                JourneyState.CORRECTION.value,
            }:
                localized = self._ivr_form_field_prompts(
                    localized, app.language or language
                )
            else:
                localized = self._ivr_menu_prompts(localized, app.language or language)
        audio_b64 = None
        audio_mime = None
        speak = localized.prompt or localized.message
        tts_on_error = localized.error in _SPEAK_ON_ERROR
        if tts_on_error and localized.message and localized.message != speak:
            # Say what went wrong before repeating the question.
            speak = f"{localized.message} {speak}".strip()
        # TTS-only: speak mobile/OTP confirmations digit-by-digit; UI keeps compact digits.
        speak = self._speak_text_for_tts(localized, speak, app.language or language)
        if speak and (not localized.error or tts_on_error):
            self._assert_no_cloud("tts", envelope.trace_id)
            catalog = get_language_catalog()
            tts_lang = catalog.tts_code(app.language or language or catalog.default_code)
            tts = self.tts.synthesize(
                speak, language=tts_lang or catalog.default_code
            )
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
        nxt = app.correcting_field or self.journey._next_missing_field(app)
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
                "auth_step": app.auth_step,
                "otp_issued": app.auth_step == "otp",
                "processing_status": app.processing_status,
                "correction_notes": app.correction_notes,
                "correcting_field": app.correcting_field,
                "next_field": nxt,
                "correction_fields": self.journey._correction_choice_fields(app)
                if app.processing_status == ProcessingStatus.NEEDS_CORRECTION.value
                or app.current_state == JourneyState.CORRECTION.value
                else [],
            },
        )

    def start(self, channel: str = "web", trace_id: str | None = None) -> ChannelReply:
        reply = self.journey.start(channel=channel, trace_id=trace_id)
        self.metrics.record_session(channel, None)
        welcome = t("welcome", "en")
        prompt = (
            language_select_ivr_prompt()
            if channel == Channel.IVR.value
            else language_select_prompt("en")
        )
        speak = f"{welcome} {prompt}".strip()
        audio_b64 = None
        audio_mime = None
        if speak:
            self._assert_no_cloud("tts", trace_id)
            tts = self.tts.synthesize(speak, language="en")
            audio_b64 = tts.audio_b64
            audio_mime = tts.mime_type
            self._audit(
                "TTS_COMPLETED",
                trace_id=trace_id,
                metadata={
                    "provider": tts.provider,
                    "text_hash": tts.text_hash,
                    "duration_ms": tts.duration_ms,
                    "phase": "welcome",
                },
            )
        return ChannelReply(
            application_id=reply.application_id,
            state=reply.state,
            message=welcome,
            prompt=prompt,
            access_token=reply.access_token,
            language=None,
            channel=channel,
            data=reply.data,
            audio_b64=audio_b64,
            audio_mime=audio_mime,
        )

    def _speak_text_for_tts(
        self,
        reply: JourneyReply,
        speak: str | None,
        language: str | None,
    ) -> str | None:
        """Adjust confirmation speech for digit/date fields without changing UI copy."""
        if not speak or reply.state != JourneyState.FIELD_CONFIRMATION.value:
            return speak
        field = (reply.data or {}).get("field")
        value = (reply.data or {}).get("proposed_value")
        if value is None or value == "":
            return speak
        spoken_value = speech_value_for_confirmation(
            str(field) if field else None, str(value)
        )
        display = (reply.data or {}).get("proposed_display") or value
        if spoken_value and display and str(display) in speak:
            return speak.replace(str(display), spoken_value, 1)
        if field in DIGIT_SPEECH_CONFIRM_FIELDS:
            lang = language or "en"
            return t("field_confirm_heard", lang, value=spoken_value)
        return speak

    def _ivr_authenticate_prompts(
        self, reply: JourneyReply, language: str | None
    ) -> JourneyReply:
        """IVR keypad wording — does not change journey tokens or web/WhatsApp copy."""
        lang = language or "en"
        data = dict(reply.data or {})
        step = data.get("auth_step") or "mobile"
        if "auth_step" not in data:
            data["auth_step"] = step
            data.setdefault("otp_issued", False)
        prompt = reply.prompt
        message = reply.message
        if step == "otp":
            prompt = t("auth_otp_ivr", lang)
            if not reply.error:
                message = prompt
        elif step == "register_offer":
            # DTMF menu — always include Press 1 / Press 2 (web/WhatsApp keep auth_register_offer).
            prompt = t("auth_register_offer_ivr", lang)
            message = t("auth_register_offer_ivr", lang)
        elif step in {"mobile", ""}:
            prompt = t("auth_mobile_ivr", lang)
            if reply.error == "unknown_mobile":
                message = t("auth_mobile_unrecognized_ivr", lang)
            elif not reply.error:
                message = prompt
        return replace(reply, prompt=prompt, message=message, data=data)

    def _ivr_field_confirmation_prompts(
        self, reply: JourneyReply, language: str | None
    ) -> JourneyReply:
        """IVR 1/2 confirmation wording — web/WhatsApp keep field_confirm_heard."""
        lang = language or "en"
        value = (reply.data or {}).get("proposed_display") or (reply.data or {}).get(
            "proposed_value"
        )
        if not value:
            return reply
        text = t("field_confirm_heard_ivr", lang, value=value)
        return replace(reply, prompt=text, message=text)

    def _ivr_numeric_field_prompt(self, field_def: Any, lang: str) -> str | None:
        """IVR keypad+voice wording for catalogue digit fields."""
        if field_def.type == "date":
            return t("field_date_of_birth_ivr", lang)
        if field_def.type == "mobile":
            return t("field_mobile_number_ivr", lang)
        if field_def.type == "number":
            return t("field_annual_income_ivr", lang)
        return None

    def _ivr_form_field_prompts(
        self, reply: JourneyReply, language: str | None
    ) -> JourneyReply:
        """IVR digit capture: keypad and spoken values. Other fields unchanged."""
        lang = language or "en"
        nxt = (reply.data or {}).get("next_field") or (reply.data or {}).get("field")
        if not nxt:
            return reply
        field_def = self.journey.service.field_by_name(str(nxt))
        text = self._ivr_numeric_field_prompt(field_def, lang) if field_def else None
        if not text:
            return reply
        return replace(reply, prompt=text)

    def _ivr_menu_prompts(
        self, reply: JourneyReply, language: str | None
    ) -> JourneyReply:
        """IVR Press-1/Press-2 wording for consent, service, review, and payment."""
        lang = language or "en"
        state = reply.state
        if state == JourneyState.CONSENT.value:
            if reply.error == "consent_unclear":
                text = t("consent_unclear_ivr", lang)
            else:
                text = t("consent_ivr", lang)
            return replace(reply, prompt=text, message=text)
        if state == JourneyState.SERVICE_SELECT.value:
            menu = service_select_ivr_prompt(lang)
            message = t("consent_recorded", lang)
            if reply.error in {"unknown_service", "service_select_ambiguous"}:
                message = reply.message or menu
            return replace(reply, prompt=menu, message=message if not reply.error else menu)
        if state == JourneyState.REVIEW_CONFIRM.value:
            text = t("review_intro_ivr", lang)
            return replace(reply, prompt=text, message=text)
        if state == JourneyState.FEE_QUOTE.value:
            amount, currency = _fee_display(reply)
            text = t("fee_quote_ivr", lang, amount=amount, currency=currency)
            return replace(reply, prompt=text, message=text)
        if state == JourneyState.PAYMENT.value:
            amount, currency = _fee_display(reply)
            text = t("payment_prompt_ivr", lang, amount=amount, currency=currency)
            return replace(reply, prompt=text, message=text)
        if state == JourneyState.PAYMENT_FAILED.value:
            text = t("payment_failed_ivr", lang)
            return replace(reply, prompt=text, message=text)
        return reply

    def _map_ivr_dtmf(self, dtmf: str, app: Application) -> str:
        """Map telephone keypad digits to existing journey tokens (DTMF only)."""
        raw = (dtmf or "").strip()
        state = JourneyState(app.current_state)
        if state == JourneyState.LANGUAGE_SELECT:
            catalog = get_language_catalog()
            if raw.isdigit():
                idx = int(raw)
                if 1 <= idx <= len(catalog.languages):
                    return catalog.languages[idx - 1].code
            return raw
        if state in {JourneyState.CONSENT}:
            if raw == "1":
                return "YES"
            if raw == "2":
                return "NO"
            return raw
        if state == JourneyState.FIELD_CONFIRMATION:
            # IVR telephone confirmation — 1 confirm, 2 change/retry.
            if raw == "1":
                return "YES"
            if raw == "2":
                return "NO"
            return raw
        if state == JourneyState.AUTHENTICATE and (app.auth_step or "") == "register_offer":
            if raw == "1":
                return "REGISTER"
            if raw == "2":
                return "ANOTHER"
            return raw
        if state == JourneyState.SERVICE_SELECT:
            from app.services.catalogue import get_service_catalogue

            codes = sorted(get_service_catalogue())
            if raw == "1" and len(codes) == 1:
                return "YES"
            if raw.isdigit():
                idx = int(raw)
                if 1 <= idx <= len(codes):
                    return codes[idx - 1]
            return raw
        if state == JourneyState.REVIEW_CONFIRM:
            if raw == "1":
                return "CONFIRM"
            if raw == "2":
                return "CORRECT"
            return raw
        if state in _PAYMENT_STATES:
            if raw == "1":
                return "PAY"
            if raw == "2":
                return "CORRECT"
            return raw
        return raw

    def _to_journey_text(
        self,
        text: str,
        nlu: Any,
        envelope: MessageEnvelope,
        expected: str | None,
        app: Application,
    ) -> str:
        current_state = app.current_state
        if envelope.modality == Modality.DTMF:
            return self._map_ivr_dtmf(str(envelope.content.get("dtmf") or text), app)
        if current_state == JourneyState.FIELD_CONFIRMATION.value:
            if nlu.intent == "CONSENT":
                return "YES" if nlu.slots.get("granted") else "NO"
            return text
        if current_state == JourneyState.CONSENT.value:
            if nlu.intent == "CONSENT":
                return "YES" if nlu.slots.get("granted") else "NO"
            decision = parse_consent_response(text)
            if decision is True:
                return "YES"
            if decision is False:
                return "NO"
            return text
        # Localized affirmatives ("हाँ", "ಹೌದು") must drive the same journey commands as
        # the English tester tokens, which still pass through untouched below.
        affirmative = (
            nlu.intent == "CONFIRM"
            or (nlu.intent == "CONSENT" and bool(nlu.slots.get("granted")))
            # Reuse the shared yes/no parser so "yes please" works everywhere, not
            # only where the NLU has an exact-match intent.
            or parse_consent_response(text) is True
        )
        if current_state == JourneyState.SERVICE_SELECT.value and affirmative:
            return "YES"
        if current_state == JourneyState.REVIEW_CONFIRM.value:
            if nlu.intent == "CORRECT":
                return "CORRECT"
            if affirmative:
                return "CONFIRM"
            return text
        if current_state in _PAYMENT_STATES:
            if nlu.intent == "CANCEL":
                return "CANCEL"
            if nlu.intent == "CORRECT":
                return "CORRECT"
            if affirmative:
                return "PAY"
            return text
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
        language_list = get_language_catalog().format_language_list()
        # Overlay known prompts
        state = reply.state
        prompt = reply.prompt
        message = reply.message
        if state == JourneyState.LANGUAGE_SELECT.value:
            prompt = language_select_prompt(lang)
            message = t("welcome", lang)
        elif state == JourneyState.AUTHENTICATE.value:
            auth_step = (reply.data or {}).get("auth_step")
            if auth_step == "otp" or (reply.prompt and "OTP" in (reply.prompt or "").upper()):
                prompt = t("auth_otp", lang)
                if reply.error == "invalid_otp":
                    message = t("auth_otp_incorrect", lang)
                elif reply.error == "otp_expired":
                    message = t("auth_otp_expired", lang)
                elif reply.error == "otp_max_attempts":
                    message = t("auth_otp_max_attempts", lang)
                elif not reply.error:
                    message = t("auth_otp_sent", lang)
            elif auth_step == "register_offer":
                prompt = t("auth_register_offer", lang)
                message = t("auth_register_offer", lang)
            elif auth_step == "register_name":
                prompt = t("auth_register_name", lang)
                message = t("auth_register_name", lang)
            else:
                prompt = t("auth_mobile", lang)
        elif state == JourneyState.CONSENT.value:
            prompt = t("consent", lang)
        elif state == JourneyState.SERVICE_SELECT.value:
            message = t("consent_recorded", lang)
            prompt = t("service_select", lang)
        elif state == JourneyState.FORM_CAPTURE.value:
            nxt = (reply.data or {}).get("next_field")
            if not nxt and reply.error == "validation_failed":
                nxt = (reply.data or {}).get("field")
            if nxt:
                prompt = field_prompt(str(nxt), lang)
        elif state == JourneyState.FIELD_CONFIRMATION.value:
            field = (reply.data or {}).get("field")
            value = (reply.data or {}).get("proposed_display") or (
                reply.data or {}
            ).get("proposed_value", "")
            if not value and field:
                raw = (reply.data or {}).get("proposed_value", "")
                field_def = self.journey.service.field_by_name(str(field))
                if field_def and field_def.type == "date" and raw:
                    from app.speech.dates import format_date_for_citizen

                    value = format_date_for_citizen(str(raw))
                else:
                    value = raw
            if value:
                message = t("field_confirm_heard", lang, value=value)
                prompt = message
            elif field:
                prompt = field_prompt(str(field), lang)
        elif state == JourneyState.DOCUMENT_CAPTURE.value:
            missing = (reply.data or {}).get("missing_documents") or []
            service = self.journey.service
            if (reply.data or {}).get("continue_on_channels"):
                message = t(
                    "document_ivr_continue",
                    lang,
                    application_id=reply.application_id,
                )
                prompt = message
            elif missing:
                prompt = document_next_prompt(missing[0], service, lang)
            else:
                prompt = t("document_prompt", lang)
            if reply.error is None and reply.message:
                # Prefer journey success copy (already localized) when present.
                lower = reply.message.lower()
                if "stored" in lower and "uploaded successfully" not in lower:
                    message = t("document_stored", lang)
        elif state == JourneyState.DOCUMENT_REJECTED.value:
            service = self.journey.service
            doc_code = (reply.data or {}).get("document_code")
            missing = (reply.data or {}).get("missing_documents") or []
            if reply.error == "document_verification_failed" and doc_code:
                name = document_label(doc_code, service, lang)
                message = t("document_verification_failed", lang, document_name=name)
                prompt = document_reupload_prompt(doc_code, service, lang)
            elif missing:
                prompt = document_next_prompt(missing[0], service, lang)
            else:
                message = t("document_rejected", lang)
                prompt = t("document_prompt", lang)
        elif state == JourneyState.REVIEW_CONFIRM.value:
            prompt = t("review_intro", lang)
            message = t("review_intro", lang)
        elif state == JourneyState.FEE_QUOTE.value:
            amount, currency = _fee_display(reply)
            message = t("fee_quote", lang, amount=amount, currency=currency)
            prompt = message
        elif state == JourneyState.PAYMENT.value:
            amount, currency = _fee_display(reply)
            message = t("payment_prompt", lang, amount=amount, currency=currency)
            prompt = message
        elif state == JourneyState.PAYMENT_FAILED.value:
            message = t("payment_failed", lang)
            prompt = message
        elif state == JourneyState.CORRECTION.value:
            field_list = (reply.data or {}).get("field_list")
            nxt = (reply.data or {}).get("next_field")
            notes = (reply.data or {}).get("correction_notes")
            if reply.error == "unknown_field":
                listed = field_list or numbered_field_list(
                    list((reply.data or {}).get("correction_fields") or []), lang
                )
                message = t("correction_unknown", lang, field_list=listed)
                prompt = message
            elif nxt:
                label = field_label_for_confirm(str(nxt), lang)
                message = join_prompt_parts(
                    t("correction_updating", lang, field=label),
                    t("correction_needed_notes", lang, notes=notes) if notes else "",
                )
                prompt = field_prompt(str(nxt), lang)
            else:
                listed = field_list or ""
                prompt = t("correction_which", lang, field_list=listed)
                message = prompt
        elif state == JourneyState.SUBMITTED.value:
            message = t("submitted", lang, application_id=reply.application_id)
        elif state == JourneyState.ESCALATED.value:
            message = t("escalation", lang)
        if reply.error == "validation_failed":
            field = (reply.data or {}).get("field")
            code = (reply.data or {}).get("validation_code")
            if field == "mobile_number":
                message = t("validation_mobile_invalid", lang)
            elif field == "date_of_birth" and code == "max_age":
                message = t(
                    "validation_date_max_age",
                    lang,
                    max_age=(reply.data or {}).get("max_age") or 120,
                )
            else:
                message = t("validation_failed", lang)
        if reply.error == "consent_declined":
            message = t("consent_declined", lang)
        if reply.error == "unknown_mobile":
            message = t("auth_mobile_unrecognized", lang)
            prompt = t("auth_mobile", lang)
        if reply.error == "invalid_otp":
            message = t("auth_otp_incorrect", lang)
            prompt = t("auth_otp", lang)
        if reply.error == "invalid_language":
            message = t("language_unsupported", lang, language_list=language_list)
            prompt = language_select_prompt(lang)
        if reply.error == "language_ambiguous":
            message = t("language_ambiguous", lang, language_list=language_list)
            prompt = language_select_prompt(lang)
        if reply.error == "unknown_service":
            message = t("service_select_unknown", lang)
            prompt = t("service_select", lang)
        if reply.error == "service_select_ambiguous":
            message = t("service_select_ambiguous", lang)
            prompt = t("service_select", lang)
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
            return language_select_prompt(lang)
        if state == JourneyState.AUTHENTICATE:
            step = app.auth_step or ("otp" if app.pending_mobile else "mobile")
            if step == "otp":
                return t("auth_otp", lang)
            if step == "register_offer":
                return t("auth_register_offer", lang)
            if step == "register_name":
                return t("auth_register_name", lang)
            return t("auth_mobile", lang)
        if state == JourneyState.CONSENT:
            return t("consent", lang)
        if state == JourneyState.SERVICE_SELECT:
            return t("service_select", lang)
        if state == JourneyState.FORM_CAPTURE:
            nxt = self.journey._next_missing_field(app)
            ask = field_prompt(nxt, lang) if nxt else t("form_complete", lang)
            if app.processing_status == ProcessingStatus.NEEDS_CORRECTION.value:
                return self.journey.citizen_correction_prompt(app, lang)
            return ask
        if state == JourneyState.FIELD_CONFIRMATION:
            if app.pending_voice_value:
                display = app.pending_voice_value
                field_def = self.journey.service.field_by_name(app.pending_voice_field or "")
                if field_def and field_def.type == "date":
                    from app.speech.dates import format_date_for_citizen

                    display = format_date_for_citizen(app.pending_voice_value)
                return t("field_confirm_heard", lang, value=display)
            field = app.pending_voice_field
            return field_prompt(field, lang) if field else t("form_complete", lang)
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
        if state == JourneyState.CORRECTION:
            return self.journey.citizen_correction_prompt(app, lang)
        return t("welcome", lang)
