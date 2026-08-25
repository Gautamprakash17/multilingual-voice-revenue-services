"""Journey orchestration — Income Certificate web text flow."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.adapters.identity import IdentityProvider, Persona, get_identity_provider
from app.adapters.payment import PaymentOutcome, get_payment_provider
from app.boundary.classification import Classification
from app.boundary.gateway import DataBoundaryGateway, GatewayRequest
from app.models.application import Application, ConversationSession, PaymentRecord
from app.models.identity import SyntheticCitizen
from app.nlu.consent import (
    parse_consent_response,
    parse_field_confirmation_response,
    parse_registration_choice,
)
from app.platform.audit import write_audit_event
from app.platform.metrics import get_metrics
from app.services.application_ids import generate_application_id, normalize_application_id
from app.services.catalogue import FieldDef, ServiceDefinition, get_service
from app.services.documents import ISSUED_CERTIFICATE_CODE
from app.services.i18n import (
    document_label,
    document_missing_list,
    document_next_prompt,
    document_reupload_prompt,
    field_label_for_confirm,
    language_select_prompt,
)
from app.services.i18n import field_prompt as i18n_field_prompt
from app.services.i18n import t as i18n_t
from app.services.languages import get_language_catalog
from app.services.notifications import NotificationService
from app.services.receipts import generate_receipt, latest_receipt
from app.services.service_selection import (
    ServiceSelectionStatus,
    normalize_service_code,
    resolve_service_affirmative,
    resolve_service_utterance,
)
from app.services.state_machine import (
    InvalidTransitionError,
    JourneyState,
    ProcessingStatus,
    assert_transition,
    initial_state,
)
from app.services.validation import validate_field
from app.speech.dates import (
    normalize_spoken_date,
    normalize_spoken_number_field,
    normalize_spoken_text_field,
)
from app.speech.digits import normalize_spoken_otp
from app.speech.language import resolve_language_choice
from app.speech.mobile import (
    extract_spoken_mobile,
    is_valid_indian_mobile,
    normalize_indian_mobile_digits,
)
from app.speech.names import is_person_name_field, normalize_spoken_person_name

SERVICE_CODE = "INCOME_CERTIFICATE"
MAX_AUTH_ATTEMPTS = 3


@dataclass
class JourneyReply:
    application_id: str
    state: str
    message: str
    prompt: str | None = None
    access_token: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    expected_format: str | None = None


class JourneyService:
    def __init__(
        self,
        db: Session,
        identity: IdentityProvider | None = None,
        gateway: DataBoundaryGateway | None = None,
    ) -> None:
        self.db = db
        self.identity = identity or get_identity_provider()
        self.gateway = gateway
        self.service: ServiceDefinition = get_service(SERVICE_CODE)
        self._hydrate_synthetic_citizens()

    # ---- helpers ----

    def _audit(
        self,
        event_type: str,
        *,
        trace_id: str | None,
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        write_audit_event(
            self.db,
            event_type=event_type,
            classification=Classification.RESTRICTED.value,
            trace_id=trace_id,
            actor_id=actor_id,
            metadata=metadata or {},
        )

    def _transition(
        self,
        app: Application,
        session: ConversationSession,
        target: JourneyState,
        *,
        trace_id: str | None,
        event_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        assert_transition(app.current_state, target)
        previous = app.current_state
        app.current_state = target.value
        session.current_state = target.value
        session.last_activity_at = datetime.now(UTC)
        app.updated_at = datetime.now(UTC)
        self._audit(
            event_type or "STATE_TRANSITION",
            trace_id=trace_id,
            actor_id=app.applicant_id,
            metadata={
                "from_state": previous,
                "to_state": target.value,
                "application_ref": app.application_id,
                **(metadata or {}),
            },
        )

    def _get_app_by_ref(self, application_id: str) -> Application:
        ref = normalize_application_id(application_id)
        app = (
            self.db.query(Application)
            .filter(Application.application_id == ref)
            .one_or_none()
        )
        if not app:
            raise LookupError("Application not found")
        return app

    def _get_session(self, app: Application, access_token: str) -> ConversationSession:
        session = (
            self.db.query(ConversationSession)
            .filter(
                ConversationSession.application_id == app.id,
                ConversationSession.access_token == access_token,
            )
            .one_or_none()
        )
        if not session:
            raise PermissionError("Invalid session token for this application")
        return session

    def _next_missing_field(self, app: Application) -> str | None:
        for name in self.service.required_field_names():
            if name not in (app.form_data or {}):
                return name
            if app.correcting_field and name == app.correcting_field:
                return name
        if app.correcting_field and app.correcting_field in (app.form_data or {}):
            # After correcting one field, clear flag
            return None
        return None

    def _missing_documents(self, app: Application) -> list[str]:
        verified = {
            d.document_code
            for d in app.documents
            if d.verification_status == "VERIFIED"
        }
        return [c for c in self.service.required_document_codes() if c not in verified]

    def _field_prompt(self, field_name: str, app: Application | None = None) -> str:
        lang = self._lang(app) if app else "en"
        return i18n_field_prompt(field_name, lang)

    def _lang(self, app: Application) -> str:
        return app.language or "en"

    def _hydrate_synthetic_citizens(self) -> None:
        merge = getattr(self.identity, "merge_personas", None)
        if not callable(merge):
            return
        rows = self.db.query(SyntheticCitizen).all()
        if not rows:
            return
        merge(
            [Persona(id=row.persona_id, name=row.name, mobile=row.mobile) for row in rows]
        )

    def _persist_synthetic_citizen(self, persona: Persona) -> None:
        existing = (
            self.db.query(SyntheticCitizen)
            .filter(SyntheticCitizen.mobile == persona.mobile)
            .one_or_none()
        )
        if existing:
            return
        self.db.add(
            SyntheticCitizen(
                id=str(uuid4()),
                persona_id=persona.id,
                name=persona.name,
                mobile=persona.mobile,
            )
        )

    def _citizen_kind(self, mobile: str | None) -> str | None:
        if not mobile:
            return None
        return "existing" if self.identity.find_by_mobile(mobile) else "new"

    def _auth_data(
        self,
        app: Application,
        *,
        otp_issued: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "auth_step": app.auth_step or "mobile",
            "otp_issued": otp_issued,
            "citizen_kind": self._citizen_kind(app.pending_mobile),
        }
        if extra:
            data.update(extra)
        return data

    def _assert_local_only(self, trace_id: str | None) -> None:
        """Prove no cloud provider is invoked for restricted journey data."""
        if self.gateway is None:
            return
        result = self.gateway.evaluate(
            GatewayRequest(
                payload={"keys": ["application"]},
                classification=Classification.RESTRICTED,
                destination="cloud",
                purpose="journey",
                approved=False,
                trace_id=trace_id,
            ),
            db=self.db,
        )
        if result.allowed:
            raise RuntimeError("Boundary violation: RESTRICTED journey data allowed to cloud")

    # ---- public API ----

    def start(self, *, channel: str = "web", trace_id: str | None = None) -> JourneyReply:
        self._assert_local_only(trace_id)
        app_ref = generate_application_id(self.db)
        token = secrets.token_urlsafe(24)
        state = initial_state()
        fee = self.service.fee
        app = Application(
            application_id=app_ref,
            service_code=SERVICE_CODE,
            current_state=state.value,
            processing_status=ProcessingStatus.DRAFT.value,
            classification=Classification.RESTRICTED.value,
            form_data={},
            fee_amount_paise=fee.amount_paise if fee else 0,
            fee_currency=fee.currency if fee else "INR",
        )
        session = ConversationSession(
            application=app,
            channel=channel,
            current_state=state.value,
            access_token=token,
            classification=Classification.RESTRICTED.value,
        )
        self.db.add(app)
        self.db.add(session)
        self.db.flush()
        self._audit(
            "JOURNEY_STARTED",
            trace_id=trace_id,
            metadata={
                "application_ref": app_ref,
                "channel": channel,
                "state": state.value,
            },
        )
        prompt = language_select_prompt(get_language_catalog().default_code)
        return JourneyReply(
            application_id=app_ref,
            state=state.value,
            message=i18n_t("welcome", "en"),
            prompt=prompt,
            access_token=token,
            data={"supported_languages": self.service.languages},
        )

    def get_status(self, application_id: str, access_token: str) -> JourneyReply:
        app = self._get_app_by_ref(application_id)
        session = self._get_session(app, access_token)
        return self._status_reply(app, session)

    def record_consent(
        self,
        application_id: str,
        access_token: str,
        *,
        granted: bool,
        trace_id: str | None = None,
    ) -> JourneyReply:
        app = self._get_app_by_ref(application_id)
        session = self._get_session(app, access_token)
        if JourneyState(app.current_state) != JourneyState.CONSENT:
            raise InvalidTransitionError(
                JourneyState(app.current_state), JourneyState.SERVICE_SELECT
            )
        if not granted:
            self._audit(
                "CONSENT_DECLINED",
                trace_id=trace_id,
                actor_id=app.applicant_id,
                metadata={"application_ref": app.application_id},
            )
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Consent is required to continue. Application cannot proceed.",
                error="consent_declined",
            )
        app.consent_granted = True
        app.consent_at = datetime.now(UTC)
        self._transition(
            app,
            session,
            JourneyState.SERVICE_SELECT,
            trace_id=trace_id,
            event_type="CONSENT_GRANTED",
            metadata={"application_ref": app.application_id},
        )
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message="Consent recorded.",
            prompt=self.service.prompts.get(
                "service_select",
                "Available service: Income Certificate. Say Income Certificate to continue.",
            ),
        )

    def handle_message(
        self,
        application_id: str,
        access_token: str,
        text: str,
        *,
        trace_id: str | None = None,
        input_modality: str | None = None,
    ) -> JourneyReply:
        self._assert_local_only(trace_id)
        app = self._get_app_by_ref(application_id)
        session = self._get_session(app, access_token)
        raw = (text or "").strip()
        state = JourneyState(app.current_state)

        if raw.upper() in {"ESCALATE", "HELP", "AGENT"}:
            if state != JourneyState.SUBMITTED:
                self._transition(
                    app,
                    session,
                    JourneyState.ESCALATED,
                    trace_id=trace_id,
                    event_type="ESCALATION_REQUESTED",
                    metadata={"application_ref": app.application_id},
                )
                app.escalated = True
                get_metrics().record_escalation()
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=self.service.prompts.get(
                    "escalate", "Escalated to an officer."
                ),
            )

        handlers = {
            JourneyState.LANGUAGE_SELECT: self._on_language,
            JourneyState.AUTHENTICATE: self._on_authenticate,
            JourneyState.AUTH_FAILED: self._on_auth_failed,
            JourneyState.CONSENT: self._on_consent_message,
            JourneyState.SERVICE_SELECT: self._on_service_select,
            JourneyState.FORM_CAPTURE: self._on_form_capture,
            JourneyState.FIELD_CONFIRMATION: self._on_field_confirmation,
            JourneyState.CORRECTION: self._on_correction,
            JourneyState.DOCUMENT_CAPTURE: self._on_document_message,
            JourneyState.DOCUMENT_REJECTED: self._on_document_rejected_message,
            JourneyState.REVIEW_CONFIRM: self._on_review,
            JourneyState.FEE_QUOTE: self._on_fee_quote,
            JourneyState.PAYMENT: self._on_payment,
            JourneyState.PAYMENT_FAILED: self._on_payment_failed,
            JourneyState.SUBMITTED: self._on_submitted,
            JourneyState.ESCALATED: self._on_escalated,
        }
        handler = handlers.get(state)
        if not handler:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="No action available in this state.",
                error="unsupported_state",
            )
        if state == JourneyState.FORM_CAPTURE:
            return handler(
                app,
                session,
                raw,
                trace_id=trace_id,
                input_modality=input_modality,
            )
        if state == JourneyState.FIELD_CONFIRMATION:
            return handler(
                app,
                session,
                raw,
                trace_id=trace_id,
                input_modality=input_modality,
            )
        if state == JourneyState.AUTHENTICATE:
            return handler(
                app,
                session,
                raw,
                trace_id=trace_id,
                input_modality=input_modality,
            )
        return handler(app, session, raw, trace_id=trace_id)

    def _normalize_voice_field_input(self, field: FieldDef, text: str) -> str:
        """Speech normalization before validation / confirmation.

        Driven by catalogue ``field.type``. Person-name fields additionally
        strip conversational prefixes (``my name is …``) — other string fields
        only get light STT cleanup.
        """
        if field.type == "mobile":
            extracted = extract_spoken_mobile(text)
            if extracted:
                return extracted
            return text
        if field.type == "date":
            normalized = normalize_spoken_date(text)
            if normalized:
                return normalized
            return text
        if field.type == "number":
            normalized = normalize_spoken_number_field(text)
            if normalized:
                return normalized
            return text
        if field.type == "string":
            if is_person_name_field(field.name):
                extracted = normalize_spoken_person_name(text)
                # Empty → fail validation rather than storing the raw sentence.
                return extracted if extracted is not None else ""
            return normalize_spoken_text_field(text)
        return text

    def _field_confirmation_reply(
        self,
        app: Application,
        *,
        field_name: str,
        proposed_value: str,
    ) -> JourneyReply:
        lang = self._lang(app)
        display_value = proposed_value
        field = self.service.field_by_name(field_name)
        if field and field.type == "date":
            from app.speech.dates import format_date_for_citizen

            display_value = format_date_for_citizen(proposed_value)
        message = i18n_t("field_confirm_heard", lang, value=display_value)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=message,
            prompt=message,
            data={
                "field_confirmation": True,
                "field": field_name,
                "proposed_value": proposed_value,
                "proposed_display": display_value,
                "next_field": field_name,
                "form_data": dict(app.form_data or {}),
            },
        )

    def _begin_voice_field_confirmation(
        self,
        app: Application,
        session: ConversationSession,
        field_name: str,
        value: str,
        *,
        trace_id: str | None,
    ) -> JourneyReply:
        # Always replace any prior pending confirmation with the current input.
        app.pending_voice_field = field_name
        app.pending_voice_value = value
        self.db.flush()
        self._transition(
            app,
            session,
            JourneyState.FIELD_CONFIRMATION,
            trace_id=trace_id,
            event_type="FIELD_CONFIRM_PENDING",
            metadata={
                "field": field_name,
                "application_ref": app.application_id,
            },
        )
        return self._field_confirmation_reply(
            app, field_name=field_name, proposed_value=value
        )

    def _commit_validated_field(
        self,
        app: Application,
        session: ConversationSession,
        field_name: str,
        value: Any,
        *,
        trace_id: str | None,
    ) -> JourneyReply:
        was_correcting = app.correcting_field
        data = dict(app.form_data or {})
        data[field_name] = value
        app.form_data = data
        app.correcting_field = None
        app.pending_voice_field = None
        app.pending_voice_value = None
        self._audit(
            "FIELD_CAPTURED",
            trace_id=trace_id,
            actor_id=app.applicant_id,
            metadata={
                "field": field_name,
                "application_ref": app.application_id,
            },
        )

        if was_correcting:
            self._transition(app, session, JourneyState.DOCUMENT_CAPTURE, trace_id=trace_id)
            if not self._missing_documents(app):
                self._transition(
                    app,
                    session,
                    JourneyState.REVIEW_CONFIRM,
                    trace_id=trace_id,
                    event_type="REVIEW_STARTED",
                )
                return self._review_reply(app)
            return self._document_capture_entry_reply(app, session)

        nxt = self._next_missing_field(app)
        if nxt:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=f"Recorded {field_name}.",
                prompt=self._field_prompt(nxt, app),
                data={
                    "next_field": nxt,
                    "form_data": dict(app.form_data or {}),
                },
            )

        self._transition(app, session, JourneyState.DOCUMENT_CAPTURE, trace_id=trace_id)
        return self._document_capture_entry_reply(app, session)

    # ---- state handlers ----

    def _on_language(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        catalog = get_language_catalog()
        choice = resolve_language_choice(text)
        if choice.ambiguous:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t(
                    "language_ambiguous",
                    catalog.default_code,
                    language_list=catalog.format_language_list(),
                ),
                prompt=language_select_prompt(catalog.default_code),
                error="language_ambiguous",
            )
        lang = choice.code or text.lower().strip()
        if lang not in self.service.languages or not catalog.is_supported(lang):
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t(
                    "language_unsupported",
                    catalog.default_code,
                    language_list=catalog.format_language_list(),
                ),
                prompt=language_select_prompt(catalog.default_code),
                error="invalid_language",
                expected_format=", ".join(self.service.languages),
            )
        app.language = lang
        self._transition(
            app,
            session,
            JourneyState.AUTHENTICATE,
            trace_id=trace_id,
            event_type="LANGUAGE_SELECTED",
            metadata={"language": lang, "application_ref": app.application_id},
        )
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message="Language saved.",
            prompt=i18n_t("auth_mobile", lang),
            data={"language": lang},
        )

    def _extract_auth_mobile(self, text: str) -> str | None:
        mobile = extract_spoken_mobile(text)
        if mobile:
            return mobile
        compact = normalize_indian_mobile_digits(text)
        if is_valid_indian_mobile(compact):
            return compact
        return None

    def _issue_otp_reply(
        self,
        app: Application,
        *,
        lang: str,
        trace_id: str | None,
        message_key: str = "auth_otp_sent",
        error: str | None = None,
    ) -> JourneyReply:
        self.identity.request_otp(app.pending_mobile or "")
        app.auth_step = "otp"
        self._audit(
            "AUTH_REQUESTED",
            trace_id=trace_id,
            metadata={
                "application_ref": app.application_id,
                "mobile_last4": (app.pending_mobile or "")[-4:] or "****",
            },
        )
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=i18n_t(message_key, lang),
            prompt=i18n_t("auth_otp", lang),
            error=error,
            data=self._auth_data(app, otp_issued=True),
        )

    def _complete_authenticated(
        self,
        app: Application,
        session: ConversationSession,
        persona: Persona,
        *,
        lang: str,
        trace_id: str | None,
        message: str,
    ) -> JourneyReply:
        app.applicant_id = persona.id
        app.pending_mobile = None
        app.auth_step = None
        app.auth_attempts = 0
        clear_sms = getattr(self.identity, "clear_demo_sms", None)
        if callable(clear_sms) and persona.mobile:
            clear_sms(persona.mobile)
        self._audit(
            "AUTH_SUCCESS",
            trace_id=trace_id,
            actor_id=persona.id,
            metadata={"application_ref": app.application_id, "persona_id": persona.id},
        )
        self._transition(app, session, JourneyState.CONSENT, trace_id=trace_id)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=message,
            prompt=self.service.prompts.get("consent"),
            data={"auth_step": "complete", "otp_issued": False},
        )

    def _on_authenticate(
        self,
        app: Application,
        session: ConversationSession,
        text: str,
        *,
        trace_id: str | None,
        input_modality: str | None = None,
    ) -> JourneyReply:
        lang = app.language or "en"
        step = app.auth_step or ("otp" if app.pending_mobile else "mobile")

        if step == "register_offer":
            entered = self._extract_auth_mobile(text)
            if entered:
                app.pending_mobile = entered
                app.auth_attempts = 0
                if self.identity.find_by_mobile(entered):
                    return self._issue_otp_reply(app, lang=lang, trace_id=trace_id)
                app.auth_step = "register_offer"
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=i18n_t("auth_register_offer", lang),
                    prompt=i18n_t("auth_register_offer", lang),
                    data=self._auth_data(app),
                )
            choice = parse_registration_choice(text)
            if choice == "another":
                app.pending_mobile = None
                app.auth_step = "mobile"
                app.auth_attempts = 0
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=i18n_t("auth_mobile", lang),
                    prompt=i18n_t("auth_mobile", lang),
                    data=self._auth_data(app),
                )
            if choice != "register":
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=i18n_t("auth_register_offer", lang),
                    prompt=i18n_t("auth_register_offer", lang),
                    data=self._auth_data(app),
                )
            return self._issue_otp_reply(app, lang=lang, trace_id=trace_id)

        if step == "register_name":
            raw_name = (text or "").strip()
            if not raw_name:
                prompt = i18n_t("auth_register_name", lang)
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=i18n_t("speech_no_response", lang, prompt=prompt),
                    prompt=prompt,
                    error="no_speech",
                    data=self._auth_data(app),
                )
            if input_modality == "voice":
                extracted = normalize_spoken_person_name(raw_name)
                if extracted is None:
                    return JourneyReply(
                        application_id=app.application_id,
                        state=app.current_state,
                        message=i18n_t("auth_register_name", lang),
                        prompt=i18n_t("auth_register_name", lang),
                        error="registration_name_required",
                        data=self._auth_data(app),
                    )
                name = extracted
            else:
                name = raw_name
            if len(name) < 2 or name.isdigit() or normalize_spoken_otp(name):
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=i18n_t("auth_register_name", lang),
                    prompt=i18n_t("auth_register_name", lang),
                    error="registration_name_required",
                    data=self._auth_data(app),
                )
            # Voice/IVR: confirm via existing FIELD_CONFIRMATION before creating the citizen.
            if input_modality == "voice":
                return self._begin_voice_field_confirmation(
                    app,
                    session,
                    "register_name",
                    name,
                    trace_id=trace_id,
                )
            persona = self.identity.register_citizen(
                name=name, mobile=app.pending_mobile or ""
            )
            self._persist_synthetic_citizen(persona)
            return self._complete_authenticated(
                app,
                session,
                persona,
                lang=lang,
                trace_id=trace_id,
                message=i18n_t("auth_register_success", lang),
            )

        if step != "otp":
            mobile = self._extract_auth_mobile(text)
            if not mobile:
                app.auth_attempts += 1
                self._audit(
                    "AUTH_FAILED",
                    trace_id=trace_id,
                    metadata={
                        "application_ref": app.application_id,
                        "reason": "unrecognized_mobile",
                        "attempts": app.auth_attempts,
                    },
                )
                if app.auth_attempts >= MAX_AUTH_ATTEMPTS:
                    self._transition(
                        app, session, JourneyState.AUTH_FAILED, trace_id=trace_id
                    )
                    return JourneyReply(
                        application_id=app.application_id,
                        state=app.current_state,
                        message="Authentication failed too many times.",
                        prompt="Please try again, or say help to reach an officer.",
                        error="auth_failed",
                    )
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=i18n_t("auth_mobile_unrecognized", lang),
                    prompt=i18n_t("auth_mobile", lang),
                    error="unknown_mobile",
                    data=self._auth_data(app),
                )
            app.pending_mobile = mobile
            app.auth_attempts = 0
            if self.identity.find_by_mobile(mobile):
                return self._issue_otp_reply(app, lang=lang, trace_id=trace_id)
            app.auth_step = "register_offer"
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t("auth_register_offer", lang),
                prompt=i18n_t("auth_register_offer", lang),
                data=self._auth_data(app),
            )

        otp = normalize_spoken_otp(text)
        if otp is None:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t("auth_otp_incorrect", lang),
                prompt=i18n_t("auth_otp", lang),
                error="invalid_otp",
                data=self._auth_data(app, otp_issued=True),
            )

        result = self.identity.verify_otp(app.pending_mobile or "", otp)
        if result.reason == "otp_expired":
            return self._issue_otp_reply(
                app,
                lang=lang,
                trace_id=trace_id,
                message_key="auth_otp_expired",
                error="otp_expired",
            )
        if result.reason == "otp_max_attempts":
            return self._issue_otp_reply(
                app,
                lang=lang,
                trace_id=trace_id,
                message_key="auth_otp_max_attempts",
                error="otp_max_attempts",
            )
        if not result.success:
            self._audit(
                "AUTH_FAILED",
                trace_id=trace_id,
                metadata={
                    "application_ref": app.application_id,
                    "reason": result.reason or "invalid_otp",
                },
            )
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t("auth_otp_incorrect", lang),
                prompt=i18n_t("auth_otp", lang),
                error="invalid_otp",
                data=self._auth_data(app, otp_issued=True),
            )

        if result.persona:
            return self._complete_authenticated(
                app,
                session,
                result.persona,
                lang=lang,
                trace_id=trace_id,
                message=i18n_t("auth_success", lang),
            )

        app.auth_step = "register_name"
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=i18n_t("auth_register_name", lang),
            prompt=i18n_t("auth_register_name", lang),
            data=self._auth_data(app),
        )

    def _on_auth_failed(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        cmd = text.upper().strip()
        if cmd == "RETRY":
            app.auth_attempts = 0
            app.pending_mobile = None
            app.auth_step = "mobile"
            self._transition(app, session, JourneyState.AUTHENTICATE, trace_id=trace_id)
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Try authentication again.",
                prompt=i18n_t("auth_mobile", app.language or "en"),
                data=self._auth_data(app),
            )
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message="Authentication blocked.",
            prompt="Please try again, or say help to reach an officer.",
        )

    def _on_consent_message(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        decision = parse_consent_response(text)
        if decision is True:
            granted, declined = True, False
        elif decision is False:
            granted, declined = False, True
        else:
            answer = text.strip().upper()
            granted = answer in {"YES", "Y", "I AGREE", "AGREE"}
            declined = answer in {"NO", "N", "DECLINE"}
        if not granted and not declined:
            lang = self._lang(app)
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t("consent_unclear", lang),
                prompt=i18n_t("consent", lang),
                error="consent_unclear",
            )
        return self.record_consent(
            app.application_id, session.access_token, granted=granted, trace_id=trace_id
        )

    def _on_service_select(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        if not app.consent_granted:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Consent is required before selecting a service.",
                error="consent_required",
            )
        lang = app.language or "en"
        raw = (text or "").strip()
        token = normalize_service_code(raw)
        if token == "YES":
            selection = resolve_service_affirmative()
        else:
            selection = resolve_service_utterance(raw, language=lang)
        if selection.status == ServiceSelectionStatus.AMBIGUOUS:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t("service_select_ambiguous", lang),
                prompt=i18n_t("service_select", lang),
                error="service_select_ambiguous",
                data={"matching_services": list(selection.matches)},
            )
        if selection.status != ServiceSelectionStatus.MATCHED or not selection.service_code:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t("service_select_unknown", lang),
                prompt=i18n_t("service_select", lang),
                error="unknown_service",
            )
        service = get_service(selection.service_code)
        app.service_code = service.service_code
        self._transition(
            app,
            session,
            JourneyState.FORM_CAPTURE,
            trace_id=trace_id,
            event_type="SERVICE_SELECTED",
            metadata={
                "service_code": service.service_code,
                "application_ref": app.application_id,
            },
        )
        first = service.required_field_names()[0]
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=f"Starting {service.display_name}.",
            prompt=self._field_prompt(first, app),
            data={
                "next_field": first,
                "form_data": dict(app.form_data or {}),
                "service_code": service.service_code,
                "service_display_name": service.display_name,
            },
        )

    def _on_form_capture(
        self,
        app: Application,
        session: ConversationSession,
        text: str,
        *,
        trace_id: str | None,
        input_modality: str | None = None,
    ) -> JourneyReply:
        if not app.consent_granted:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Consent required before capturing data.",
                error="consent_required",
            )
        field_name = app.correcting_field or self._next_missing_field(app)
        lang = self._lang(app)
        if input_modality == "voice" and not (text or "").strip() and field_name:
            prompt = self._field_prompt(field_name, app)
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t("speech_no_response", lang, prompt=prompt),
                prompt=prompt,
                error="no_speech",
                data={"field": field_name, "next_field": field_name},
            )
        if text.upper() == "CORRECT":
            self._transition(
                app,
                session,
                JourneyState.CORRECTION,
                trace_id=trace_id,
                event_type="CORRECTION_REQUESTED",
            )
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Which field do you want to correct?",
                prompt=", ".join(self.service.required_field_names()),
            )

        field_name = app.correcting_field or self._next_missing_field(app)
        if not field_name:
            if not self._missing_documents(app):
                self._transition(
                    app,
                    session,
                    JourneyState.REVIEW_CONFIRM,
                    trace_id=trace_id,
                    event_type="REVIEW_STARTED",
                )
                return self._review_reply(app)
            # All fields present — move to documents
            self._transition(app, session, JourneyState.DOCUMENT_CAPTURE, trace_id=trace_id)
            return self._document_capture_entry_reply(app, session)

        field = self.service.field_by_name(field_name)
        assert field is not None
        capture_text = text
        if input_modality == "voice":
            capture_text = self._normalize_voice_field_input(field, text)
        result = validate_field(field, capture_text)
        if not result.ok:
            self._audit(
                "VALIDATION_FAILED",
                trace_id=trace_id,
                actor_id=app.applicant_id,
                metadata={
                    "field": field_name,
                    "application_ref": app.application_id,
                    "error": result.error,
                },
            )
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=result.error or "Invalid value",
                prompt=self._field_prompt(field_name, app),
                error="validation_failed",
                expected_format=result.expected_format,
                data={"field": field_name},
            )

        if input_modality == "voice":
            return self._begin_voice_field_confirmation(
                app,
                session,
                field_name,
                str(result.value),
                trace_id=trace_id,
            )

        return self._commit_validated_field(
            app,
            session,
            field_name,
            result.value,
            trace_id=trace_id,
        )

    def _clear_pending_voice_confirmation(self, app: Application) -> None:
        """Drop pending confirmation so a retry cannot reuse a rejected value."""
        app.pending_voice_field = None
        app.pending_voice_value = None
        # Session uses autoflush=False — flush so later reads in this request see clears.
        self.db.flush()

    def _on_field_confirmation(
        self,
        app: Application,
        session: ConversationSession,
        text: str,
        *,
        trace_id: str | None,
        input_modality: str | None = None,
    ) -> JourneyReply:
        field_name = app.pending_voice_field
        proposed = app.pending_voice_value
        lang = self._lang(app)
        if not field_name or proposed is None:
            self._clear_pending_voice_confirmation(app)
            self._transition(
                app,
                session,
                JourneyState.FORM_CAPTURE,
                trace_id=trace_id,
                event_type="FIELD_CONFIRM_RESET",
            )
            nxt = self._next_missing_field(app) or field_name
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t("error_generic", lang),
                prompt=self._field_prompt(nxt, app) if nxt else i18n_t("form_complete", lang),
                data={"next_field": nxt, "form_data": dict(app.form_data or {})},
            )

        decision = parse_field_confirmation_response(text)
        if decision is True:
            value = proposed
            self._clear_pending_voice_confirmation(app)
            if field_name == "register_name":
                persona = self.identity.register_citizen(
                    name=str(value), mobile=app.pending_mobile or ""
                )
                self._persist_synthetic_citizen(persona)
                return self._complete_authenticated(
                    app,
                    session,
                    persona,
                    lang=lang,
                    trace_id=trace_id,
                    message=i18n_t("auth_register_success", lang),
                )
            self._transition(
                app,
                session,
                JourneyState.FORM_CAPTURE,
                trace_id=trace_id,
                event_type="FIELD_CONFIRM_ACCEPTED",
                metadata={"field": field_name, "application_ref": app.application_id},
            )
            return self._commit_validated_field(
                app,
                session,
                field_name,
                value,
                trace_id=trace_id,
            )

        if decision is False:
            self._clear_pending_voice_confirmation(app)
            if field_name == "register_name":
                app.auth_step = "register_name"
                self._transition(
                    app,
                    session,
                    JourneyState.AUTHENTICATE,
                    trace_id=trace_id,
                    event_type="FIELD_CONFIRM_DECLINED",
                    metadata={"field": field_name, "application_ref": app.application_id},
                )
                label = field_label_for_confirm(field_name, lang)
                retry = i18n_t("field_confirm_retry", lang, field_label=label)
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=retry,
                    prompt=i18n_t("auth_register_name", lang),
                    data=self._auth_data(app),
                )
            self._transition(
                app,
                session,
                JourneyState.FORM_CAPTURE,
                trace_id=trace_id,
                event_type="FIELD_CONFIRM_DECLINED",
                metadata={"field": field_name, "application_ref": app.application_id},
            )
            label = field_label_for_confirm(field_name, lang)
            retry = i18n_t("field_confirm_retry", lang, field_label=label)
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=retry,
                prompt=self._field_prompt(field_name, app),
                data={
                    "next_field": field_name,
                    "field": field_name,
                    "form_data": dict(app.form_data or {}),
                },
            )

        # Not yes/no — treat as a new attempt for the same field. Never re-prompt
        # the rejected pending value (that caused stale "I heard: …" after retry).
        self._clear_pending_voice_confirmation(app)
        if field_name == "register_name":
            app.auth_step = "register_name"
            self._transition(
                app,
                session,
                JourneyState.AUTHENTICATE,
                trace_id=trace_id,
                event_type="FIELD_CONFIRM_REPLACED",
                metadata={"field": field_name, "application_ref": app.application_id},
            )
            return self._on_authenticate(
                app,
                session,
                text,
                trace_id=trace_id,
                input_modality=input_modality or "voice",
            )
        self._transition(
            app,
            session,
            JourneyState.FORM_CAPTURE,
            trace_id=trace_id,
            event_type="FIELD_CONFIRM_REPLACED",
            metadata={"field": field_name, "application_ref": app.application_id},
        )
        modality = input_modality or "voice"
        return self._on_form_capture(
            app,
            session,
            text,
            trace_id=trace_id,
            input_modality=modality,
        )

    def _on_correction(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        field_name = text.strip().lower()
        if field_name not in self.service.required_field_names():
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Unknown field.",
                prompt=", ".join(self.service.required_field_names()),
                error="unknown_field",
            )
        app.correcting_field = field_name
        # Clear so it will be re-captured
        data = dict(app.form_data or {})
        data.pop(field_name, None)
        app.form_data = data
        self._transition(app, session, JourneyState.FORM_CAPTURE, trace_id=trace_id)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=f"Correcting {field_name}.",
            prompt=self._field_prompt(field_name, app),
            data={
                "next_field": field_name,
                "form_data": dict(app.form_data or {}),
            },
        )

    def _document_capture_entry_reply(
        self, app: Application, session: ConversationSession
    ) -> JourneyReply:
        """Prompt for the next document, or IVR cross-channel continuation."""
        missing = self._missing_documents(app)
        lang = self._lang(app)
        base_data = {
            "missing_documents": missing,
            "form_data": dict(app.form_data or {}),
        }
        if (session.channel or "").lower() == "ivr":
            message = i18n_t(
                "document_ivr_continue",
                lang,
                application_id=app.application_id,
            )
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=message,
                prompt=message,
                data={
                    **base_data,
                    "continue_on_channels": ["web", "whatsapp"],
                    "application_id": app.application_id,
                },
            )
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=i18n_t("form_complete", lang),
            prompt=(
                document_next_prompt(missing[0], self.service, lang)
                if missing
                else i18n_t("document_all_uploaded", lang)
            ),
            data=base_data,
        )

    def _on_document_message(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        cmd = text.strip().upper()
        missing = self._missing_documents(app)
        if cmd in {"DONE", "CONTINUE", "NEXT"} and not missing:
            self._transition(
                app,
                session,
                JourneyState.REVIEW_CONFIRM,
                trace_id=trace_id,
                event_type="REVIEW_STARTED",
            )
            return self._review_reply(app)
        if missing:
            lang = self._lang(app)
            if (session.channel or "").lower() == "ivr":
                message = i18n_t(
                    "document_ivr_continue",
                    lang,
                    application_id=app.application_id,
                )
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=message,
                    prompt=message,
                    data={
                        "missing_documents": missing,
                        "continue_on_channels": ["web", "whatsapp"],
                        "application_id": app.application_id,
                    },
                )
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t("document_upload_required", lang),
                prompt=document_missing_list(missing, self.service, lang),
                data={"missing_documents": missing},
            )
        self._transition(
            app,
            session,
            JourneyState.REVIEW_CONFIRM,
            trace_id=trace_id,
            event_type="REVIEW_STARTED",
        )
        return self._review_reply(app)

    def _on_document_rejected_message(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        if text.strip().upper() in {"RETRY", "UPLOAD", "OK"}:
            self._transition(app, session, JourneyState.DOCUMENT_CAPTURE, trace_id=trace_id)
            missing = self._missing_documents(app)
            lang = self._lang(app)
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=i18n_t("document_reupload", lang, document_name=document_label(
                    missing[0], self.service, lang
                )) if missing else i18n_t("document_prompt", lang),
                prompt=(
                    document_next_prompt(missing[0], self.service, lang)
                    if missing
                    else i18n_t("document_prompt", lang)
                ),
                data={"missing_documents": missing},
            )
        lang = self._lang(app)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=i18n_t("document_rejected", lang),
            prompt=i18n_t("document_prompt", lang),
        )

    def _on_review(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        cmd = text.strip().upper()
        if cmd == "CORRECT":
            self._transition(
                app,
                session,
                JourneyState.CORRECTION,
                trace_id=trace_id,
                event_type="CORRECTION_REQUESTED",
            )
            get_metrics().record_correction()
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Which field do you want to correct?",
                prompt=", ".join(self.service.required_field_names()),
            )
        if cmd == "CONFIRM":
            if app.payment_completed:
                return self._finalize_submission(app, session, trace_id=trace_id)
            self._transition(
                app,
                session,
                JourneyState.FEE_QUOTE,
                trace_id=trace_id,
                event_type="FEE_QUOTE_STARTED",
                metadata={"application_ref": app.application_id},
            )
            return self._fee_quote_reply(app)
        return self._review_reply(app, error="reply_CONFIRM_or_CORRECT")

    def _fee_quote_reply(self, app: Application, error: str | None = None) -> JourneyReply:
        amount = app.fee_amount_paise or 0
        currency = app.fee_currency or "INR"
        rupees = amount / 100
        prompt_tpl = self.service.prompts.get(
            "fee_quote",
            "The application fee is {amount} {currency}. "
            "Say yes to pay now, or say change to edit your details.",
        )
        message = prompt_tpl.format(amount=f"{rupees:.2f}", currency=currency)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=message,
            prompt="Say yes to pay now, or say change to edit your details.",
            error=error,
            data={
                "fee": {
                    "amount_paise": amount,
                    "currency": currency,
                    "display": f"{rupees:.2f} {currency}",
                }
            },
        )

    def _on_fee_quote(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        cmd = text.strip().upper()
        if cmd in {"CANCEL", "BACK"}:
            # Return to review without entering field-by-field correction.
            self._transition(
                app,
                session,
                JourneyState.REVIEW_CONFIRM,
                trace_id=trace_id,
                event_type="PAYMENT_CANCELLED",
                metadata={"application_ref": app.application_id, "from_state": "FEE_QUOTE"},
            )
            return self._review_reply(app)
        if cmd == "CORRECT":
            self._transition(
                app,
                session,
                JourneyState.CORRECTION,
                trace_id=trace_id,
                event_type="CORRECTION_REQUESTED",
            )
            get_metrics().record_correction()
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Which field do you want to correct?",
                prompt=", ".join(self.service.required_field_names()),
            )
        if cmd in {"PAY", "YES", "CONFIRM", "OK"}:
            self._transition(
                app,
                session,
                JourneyState.PAYMENT,
                trace_id=trace_id,
                event_type="PAYMENT_STARTED",
            )
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=self.service.prompts.get(
                    "payment_prompt",
                    "Please confirm the payment. Say yes to complete it, or say cancel to go back.",
                ),
                prompt="Say yes to complete the payment, or say cancel to go back.",
                data={
                    "fee": {
                        "amount_paise": app.fee_amount_paise,
                        "currency": app.fee_currency,
                    }
                },
            )
        return self._fee_quote_reply(app, error="reply_PAY_or_CORRECT")

    def _on_payment(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        cmd = text.strip().upper()
        if cmd in {"CANCEL", "BACK"}:
            # Abort payment without submitting; return to fee quote.
            self._transition(
                app,
                session,
                JourneyState.FEE_QUOTE,
                trace_id=trace_id,
                event_type="PAYMENT_CANCELLED",
                metadata={"application_ref": app.application_id, "from_state": "PAYMENT"},
            )
            return self._fee_quote_reply(app)
        return self._attempt_payment(app, session, text, trace_id=trace_id)

    def _on_payment_failed(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        cmd = text.strip().upper()
        if cmd in {"CANCEL", "BACK"}:
            self._transition(
                app,
                session,
                JourneyState.FEE_QUOTE,
                trace_id=trace_id,
                event_type="PAYMENT_CANCELLED",
                metadata={"application_ref": app.application_id, "from_state": "PAYMENT_FAILED"},
            )
            return self._fee_quote_reply(app)
        if cmd in {"RETRY", "PAY", "YES", "OK"}:
            self._transition(app, session, JourneyState.PAYMENT, trace_id=trace_id)
            return self._attempt_payment(
                app,
                session,
                "PAY" if cmd == "RETRY" else cmd,
                trace_id=trace_id,
            )
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=self.service.prompts.get(
                "payment_failed",
                "The payment did not go through. Say yes to try again, or say cancel to go back.",
            ),
            prompt="Say yes to try again, or say cancel to go back.",
        )

    def _attempt_payment(
        self,
        app: Application,
        session: ConversationSession,
        text: str,
        *,
        trace_id: str | None,
    ) -> JourneyReply:
        amount = app.fee_amount_paise or 0
        currency = app.fee_currency or "INR"
        result = get_payment_provider().charge(
            amount_paise=amount,
            currency=currency,
            application_ref=app.application_id,
            scenario=text,
        )
        payment = PaymentRecord(
            application_id=app.id,
            amount_paise=amount,
            currency=currency,
            outcome=result.outcome.value,
            payment_ref=result.payment_ref,
            provider=result.provider,
            reason=result.reason,
            classification=Classification.INTERNAL.value,
        )
        self.db.add(payment)
        self.db.flush()
        get_metrics().record_payment(result.outcome.value)
        self._audit(
            "PAYMENT_ATTEMPT",
            trace_id=trace_id,
            actor_id=app.applicant_id,
            metadata={
                "application_ref": app.application_id,
                "outcome": result.outcome.value,
                "payment_ref": result.payment_ref,
                "amount_paise": amount,
                "provider": result.provider,
            },
        )

        if result.outcome == PaymentOutcome.SUCCESS:
            app.payment_completed = True
            app.payment_ref = result.payment_ref
            return self._finalize_submission(app, session, trace_id=trace_id)

        if result.outcome == PaymentOutcome.TIMEOUT:
            # Park safely in PAYMENT_FAILED without corrupting payment_completed
            if JourneyState(app.current_state) != JourneyState.PAYMENT_FAILED:
                self._transition(
                    app,
                    session,
                    JourneyState.PAYMENT_FAILED,
                    trace_id=trace_id,
                    event_type="PAYMENT_TIMEOUT",
                    metadata={"reason": result.reason},
                )
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=(
                    "Payment timed out. Your application is parked safely. "
                    "Say yes to try again."
                ),
                prompt="Say yes to try again, or say cancel to go back.",
                error="payment_timeout",
                data={"recovery": "RETRY"},
            )

        if JourneyState(app.current_state) != JourneyState.PAYMENT_FAILED:
            self._transition(
                app,
                session,
                JourneyState.PAYMENT_FAILED,
                trace_id=trace_id,
                event_type="PAYMENT_FAILED",
                metadata={"reason": result.reason},
            )
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message="The payment did not go through. Say yes to try again.",
            prompt="Say yes to try again, or say cancel to go back.",
            error="payment_failed",
            data={"recovery": "RETRY"},
        )

    def _finalize_submission(
        self,
        app: Application,
        session: ConversationSession,
        *,
        trace_id: str | None,
    ) -> JourneyReply:
        if JourneyState(app.current_state) != JourneyState.SUBMITTED:
            self._transition(
                app,
                session,
                JourneyState.SUBMITTED,
                trace_id=trace_id,
                event_type="APPLICATION_SUBMITTED",
                metadata={"application_ref": app.application_id},
            )
        app.processing_status = ProcessingStatus.UNDER_REVIEW.value
        app.correction_notes = None
        receipt = generate_receipt(db=self.db, app=app, trace_id=trace_id)
        get_metrics().record_status(app.processing_status)
        NotificationService(self.db).notify_submission(app)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=self.service.prompts.get("submitted", "Application submitted."),
            data={
                "application_id": app.application_id,
                "status": app.processing_status,
                "processing_status": app.processing_status,
                "payment_ref": app.payment_ref,
                "receipt_id": receipt.receipt_id,
                "receipt": receipt.body_text,
            },
        )

    def _on_submitted(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        receipt = latest_receipt(self.db, app.id)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message="Application already submitted. You can check status anytime.",
            data={
                "application_id": app.application_id,
                "status": app.processing_status,
                "processing_status": app.processing_status,
                "payment_ref": app.payment_ref,
                "receipt_id": receipt.receipt_id if receipt else None,
                "receipt": receipt.body_text if receipt else None,
                "correction_notes": app.correction_notes,
            },
        )

    def _on_escalated(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=self.service.prompts.get("escalate", "Escalated."),
            data={"processing_status": app.processing_status, "escalated": True},
        )

    def _review_reply(self, app: Application, error: str | None = None) -> JourneyReply:
        docs = [
            {
                "code": d.document_code,
                "filename": d.original_filename,
                "mime_type": d.mime_type,
                "size_bytes": d.size_bytes,
                "checksum_sha256": d.checksum_sha256,
                "verification_status": d.verification_status,
            }
            for d in app.documents
        ]
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            # Reached via the raw journey API too (document upload), so localize here
            # rather than relying on the channel orchestrator.
            message=i18n_t("review_intro", self._lang(app)),
            prompt=i18n_t("review_intro", self._lang(app)),
            error=error,
            data={
                "review": {
                    "application_id": app.application_id,
                    "service": app.service_code,
                    "language": app.language,
                    "fields": dict(app.form_data or {}),
                    "documents": docs,
                    "payment_completed": app.payment_completed,
                }
            },
        )

    def _status_reply(self, app: Application, session: ConversationSession) -> JourneyReply:
        receipt = latest_receipt(self.db, app.id)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message="Current application status.",
            data={
                "language": app.language,
                "service_code": app.service_code,
                "consent_granted": app.consent_granted,
                "fields_captured": list((app.form_data or {}).keys()),
                "auth_step": app.auth_step or (
                    "otp" if app.pending_mobile and app.current_state == "AUTHENTICATE" else None
                ),
                "otp_issued": bool(
                    app.auth_step == "otp" and app.pending_mobile
                ),
                "documents": [
                    {
                        "code": d.document_code,
                        "verification_status": d.verification_status,
                    }
                    for d in app.documents
                ],
                "channel": session.channel,
                "classification": app.classification,
                "processing_status": app.processing_status,
                "payment_completed": app.payment_completed,
                "payment_ref": app.payment_ref,
                "fee_amount_paise": app.fee_amount_paise,
                "fee_currency": app.fee_currency,
                "escalated": app.escalated,
                "correction_notes": app.correction_notes,
                "receipt_id": receipt.receipt_id if receipt else None,
                "receipt": receipt.body_text if receipt else None,
                "issued_certificate_available": any(
                    d.document_code == ISSUED_CERTIFICATE_CODE for d in app.documents
                )
                and app.processing_status == "ISSUED",
            },
        )

    def mark_document_rejected(
        self,
        application_id: str,
        access_token: str,
        *,
        reason: str,
        trace_id: str | None = None,
    ) -> JourneyReply:
        app = self._get_app_by_ref(application_id)
        session = self._get_session(app, access_token)
        self._transition(
            app,
            session,
            JourneyState.DOCUMENT_REJECTED,
            trace_id=trace_id,
            metadata={"reason": reason},
        )
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=i18n_t("document_rejected", self._lang(app)),
            prompt=i18n_t("document_prompt", self._lang(app)),
            data={"recovery": "RETRY", "reason": reason},
        )

    def after_document_upload(
        self,
        application_id: str,
        access_token: str,
        *,
        trace_id: str | None = None,
        document_code: str | None = None,
    ) -> JourneyReply:
        app = self._get_app_by_ref(application_id)
        session = self._get_session(app, access_token)
        self.db.refresh(app)
        if JourneyState(app.current_state) == JourneyState.DOCUMENT_REJECTED:
            self._transition(app, session, JourneyState.DOCUMENT_CAPTURE, trace_id=trace_id)
        # Any unverified docs keep capture open
        bad = [
            d
            for d in app.documents
            if (d.verification_status or "") != "VERIFIED"
        ]
        if bad:
            # Prefer explicit mismatch/unreadable over pending uploads
            failed = [
                d
                for d in bad
                if d.verification_status in {"MISMATCH", "UNREADABLE"}
            ]
            target = failed[0] if failed else None
            if target is not None:
                if JourneyState(app.current_state) != JourneyState.DOCUMENT_REJECTED:
                    self._transition(
                        app,
                        session,
                        JourneyState.DOCUMENT_REJECTED,
                        trace_id=trace_id,
                        metadata={
                            "document_code": target.document_code,
                            "outcome": target.verification_status,
                        },
                    )
                lang = self._lang(app)
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=i18n_t(
                        "document_verification_failed",
                        lang,
                        document_name=document_label(
                            target.document_code, self.service, lang
                        ),
                    ),
                    prompt=document_reupload_prompt(
                        target.document_code, self.service, lang
                    ),
                    error="document_verification_failed",
                    data={
                        "recovery": "RETRY",
                        "document_code": target.document_code,
                        "verification_status": target.verification_status,
                    },
                )
        missing = self._missing_documents(app)
        if missing:
            lang = self._lang(app)
            uploaded_code = (document_code or "").upper() or None
            if not uploaded_code:
                verified = {
                    d.document_code
                    for d in app.documents
                    if (d.verification_status or "") == "VERIFIED"
                }
                uploaded_code = next(
                    (
                        code
                        for code in self.service.required_document_codes()
                        if code in verified and code not in missing
                    ),
                    None,
                )
            category = (
                document_label(uploaded_code, self.service, lang)
                if uploaded_code
                else i18n_t("document_stored", lang)
            )
            message = (
                i18n_t("document_uploaded_ok", lang, document_name=category)
                if uploaded_code
                else i18n_t("document_stored", lang)
            )
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=message,
                prompt=document_next_prompt(missing[0], self.service, lang),
                data={"missing_documents": missing, "document_code": uploaded_code},
            )
        self._transition(
            app,
            session,
            JourneyState.REVIEW_CONFIRM,
            trace_id=trace_id,
            event_type="REVIEW_STARTED",
        )
        return self._review_reply(app)

    def get_receipt(self, application_id: str, access_token: str) -> JourneyReply:
        app = self._get_app_by_ref(application_id)
        self._get_session(app, access_token)
        receipt = latest_receipt(self.db, app.id)
        if not receipt:
            raise LookupError("Receipt not found")
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message="Receipt ready.",
            data={
                "receipt_id": receipt.receipt_id,
                "receipt": receipt.body_text,
                "payment_ref": receipt.payment_ref,
                "status": receipt.status,
                "amount_paise": receipt.amount_paise,
                "currency": receipt.currency,
            },
        )

    def get_issued_certificate_bytes(
        self, application_id: str, access_token: str
    ) -> tuple[bytes, str]:
        """Citizen download of the issued certificate. Session token required."""
        from app.services.documents import get_document, read_stored_bytes
        from app.services.state_machine import ProcessingStatus

        app = self._get_app_by_ref(application_id)
        self._get_session(app, access_token)
        if app.processing_status != ProcessingStatus.ISSUED.value:
            raise LookupError("Issued certificate not found")
        record = get_document(self.db, app.id, ISSUED_CERTIFICATE_CODE)
        if not record:
            raise LookupError("Issued certificate not found")
        try:
            payload = read_stored_bytes(record.storage_key)
        except FileNotFoundError as exc:
            raise LookupError("Issued certificate not found") from exc
        if not payload.startswith(b"%PDF"):
            raise LookupError("Issued certificate not found")
        return payload, record.original_filename
