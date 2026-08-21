"""Journey orchestration — Income Certificate web text flow."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.identity import IdentityProvider, get_identity_provider
from app.adapters.payment import PaymentOutcome, get_payment_provider
from app.boundary.classification import Classification
from app.boundary.gateway import DataBoundaryGateway, GatewayRequest
from app.models.application import Application, ConversationSession, PaymentRecord
from app.platform.audit import write_audit_event
from app.platform.metrics import get_metrics
from app.services.application_ids import generate_application_id
from app.services.catalogue import ServiceDefinition, get_service
from app.services.i18n import field_prompt as i18n_field_prompt
from app.services.i18n import t as i18n_t
from app.services.receipts import generate_receipt, latest_receipt
from app.services.state_machine import (
    InvalidTransitionError,
    JourneyState,
    ProcessingStatus,
    assert_transition,
    initial_state,
)
from app.services.validation import validate_field

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
        app = (
            self.db.query(Application)
            .filter(Application.application_id == application_id)
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
        prompt = i18n_t("language_select", "en")
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
                "Available service: Income Certificate. Reply INCOME_CERTIFICATE.",
            ),
        )

    def handle_message(
        self,
        application_id: str,
        access_token: str,
        text: str,
        *,
        trace_id: str | None = None,
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
        return handler(app, session, raw, trace_id=trace_id)

    # ---- state handlers ----

    def _on_language(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        lang = text.lower().strip()
        if lang not in self.service.languages:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Unsupported language.",
                prompt=self.service.prompts.get("language_select"),
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
            prompt="Enter your registered mobile number to authenticate.",
            data={"language": lang},
        )

    def _on_authenticate(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        # Two-step: mobile then OTP
        if not app.pending_mobile:
            mobile = "".join(ch for ch in text if ch.isdigit())
            challenge = self.identity.request_otp(mobile)
            self._audit(
                "AUTH_REQUESTED",
                trace_id=trace_id,
                metadata={
                    "application_ref": app.application_id,
                    "mobile_last4": mobile[-4:] if len(mobile) >= 4 else "****",
                },
            )
            if not challenge:
                app.auth_attempts += 1
                self._audit(
                    "AUTH_FAILED",
                    trace_id=trace_id,
                    metadata={
                        "application_ref": app.application_id,
                        "reason": "unknown_mobile",
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
                        prompt="Reply RETRY to try again, or ESCALATE for help.",
                        error="auth_failed",
                    )
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message="Mobile number not recognised. Use a seeded synthetic persona.",
                    prompt="Enter your registered mobile number.",
                    error="unknown_mobile",
                )
            app.pending_mobile = challenge.mobile
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="A one-time password has been sent (mock).",
                prompt="Enter the OTP.",
                data={"otp_hint": "Use the seeded OTP for this persona (never logged)."},
            )

        # Verify OTP — never audit the OTP value
        result = self.identity.verify_otp(app.pending_mobile, text)
        if not result.success or not result.persona:
            app.auth_attempts += 1
            self._audit(
                "AUTH_FAILED",
                trace_id=trace_id,
                metadata={
                    "application_ref": app.application_id,
                    "reason": result.reason or "invalid_otp",
                    "attempts": app.auth_attempts,
                },
            )
            if app.auth_attempts >= MAX_AUTH_ATTEMPTS:
                app.pending_mobile = None
                self._transition(
                    app, session, JourneyState.AUTH_FAILED, trace_id=trace_id
                )
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message="Authentication failed too many times.",
                    prompt="Reply RETRY to try again, or ESCALATE for help.",
                    error="auth_failed",
                )
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Incorrect OTP.",
                prompt="Enter the OTP again.",
                error="invalid_otp",
            )

        app.applicant_id = result.persona.id
        app.pending_mobile = None
        app.auth_attempts = 0
        self._audit(
            "AUTH_SUCCESS",
            trace_id=trace_id,
            actor_id=result.persona.id,
            metadata={"application_ref": app.application_id, "persona_id": result.persona.id},
        )
        self._transition(app, session, JourneyState.CONSENT, trace_id=trace_id)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=f"Authenticated as {result.persona.name}.",
            prompt=self.service.prompts.get("consent"),
            data={"persona_name": result.persona.name},
        )

    def _on_auth_failed(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        cmd = text.upper().strip()
        if cmd == "RETRY":
            app.auth_attempts = 0
            app.pending_mobile = None
            self._transition(app, session, JourneyState.AUTHENTICATE, trace_id=trace_id)
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Try authentication again.",
                prompt="Enter your registered mobile number.",
            )
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message="Authentication blocked.",
            prompt="Reply RETRY or ESCALATE.",
        )

    def _on_consent_message(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        answer = text.strip().upper()
        granted = answer in {"YES", "Y", "I AGREE", "AGREE"}
        declined = answer in {"NO", "N", "DECLINE"}
        if not granted and not declined:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Please reply YES to consent or NO to decline.",
                prompt=self.service.prompts.get("consent"),
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
        code = text.strip().upper().replace(" ", "_")
        if code not in {SERVICE_CODE, "INCOME", "YES"}:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Unknown service.",
                prompt=self.service.prompts.get("service_select"),
                error="unknown_service",
            )
        app.service_code = SERVICE_CODE
        self._transition(
            app,
            session,
            JourneyState.FORM_CAPTURE,
            trace_id=trace_id,
            event_type="SERVICE_SELECTED",
            metadata={"service_code": SERVICE_CODE, "application_ref": app.application_id},
        )
        first = self.service.required_field_names()[0]
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=f"Starting {self.service.display_name}.",
            prompt=self._field_prompt(first, app),
            data={"next_field": first},
        )

    def _on_form_capture(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        if not app.consent_granted:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Consent required before capturing data.",
                error="consent_required",
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
            missing = self._missing_documents(app)
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Form complete. Please upload required documents.",
                prompt=f"Upload next: {missing[0]}" if missing else "All documents uploaded.",
                data={"missing_documents": missing},
            )

        field = self.service.field_by_name(field_name)
        assert field is not None
        result = validate_field(field, text)
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

        data = dict(app.form_data or {})
        data[field_name] = result.value
        app.form_data = data
        was_correcting = app.correcting_field
        app.correcting_field = None
        self._audit(
            "FIELD_CAPTURED",
            trace_id=trace_id,
            actor_id=app.applicant_id,
            metadata={
                "field": field_name,
                "application_ref": app.application_id,
                # never store the raw citizen value
            },
        )

        if was_correcting:
            self._transition(app, session, JourneyState.DOCUMENT_CAPTURE, trace_id=trace_id)
            # Jump back toward review if docs already complete
            if not self._missing_documents(app):
                self._transition(
                    app,
                    session,
                    JourneyState.REVIEW_CONFIRM,
                    trace_id=trace_id,
                    event_type="REVIEW_STARTED",
                )
                return self._review_reply(app)
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=f"Updated {field_name}.",
                prompt="Continue document upload or proceed when complete.",
                data={"missing_documents": self._missing_documents(app)},
            )

        nxt = self._next_missing_field(app)
        if nxt:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message=f"Recorded {field_name}.",
                prompt=self._field_prompt(nxt, app),
                data={"next_field": nxt},
            )

        self._transition(app, session, JourneyState.DOCUMENT_CAPTURE, trace_id=trace_id)
        missing = self._missing_documents(app)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message="All form fields captured.",
            prompt=f"Upload document: {missing[0]}",
            data={"missing_documents": missing},
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
            data={"next_field": field_name},
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
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Please upload the required documents via the upload endpoint.",
                prompt=f"Still missing: {', '.join(missing)}",
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
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Please re-upload the rejected document.",
                prompt=f"Upload: {missing[0]}" if missing else "Upload a document.",
                data={"missing_documents": missing},
            )
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message="Document was rejected.",
            prompt="Reply RETRY to upload again.",
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
            "Application fee is {amount} {currency}. Reply PAY to proceed.",
        )
        message = prompt_tpl.format(amount=f"{rupees:.2f}", currency=currency)
        return JourneyReply(
            application_id=app.application_id,
            state=app.current_state,
            message=message,
            prompt="Reply PAY to continue, or CORRECT to edit.",
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
                    "Complete payment. Reply PAY, FAIL, or TIMEOUT.",
                ),
                prompt="Reply PAY / FAIL / TIMEOUT",
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
        return self._attempt_payment(app, session, text, trace_id=trace_id)

    def _on_payment_failed(
        self, app: Application, session: ConversationSession, text: str, *, trace_id: str | None
    ) -> JourneyReply:
        cmd = text.strip().upper()
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
                "Payment did not succeed. Reply RETRY to try again.",
            ),
            prompt="Reply RETRY or PAY",
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
                    "Reply RETRY to try again."
                ),
                prompt="Reply RETRY",
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
            message="Payment failed. Reply RETRY to try again.",
            prompt="Reply RETRY or PAY",
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
            message=self.service.prompts.get("review_intro", "Please review."),
            prompt="Reply CONFIRM to continue to fee payment, or CORRECT to change a field.",
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
            message=f"Document rejected: {reason}",
            prompt="Reply RETRY to upload again.",
            data={"recovery": "RETRY", "reason": reason},
        )

    def after_document_upload(
        self, application_id: str, access_token: str, *, trace_id: str | None = None
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
                return JourneyReply(
                    application_id=app.application_id,
                    state=app.current_state,
                    message=f"Document verification failed: {target.verification_reason}",
                    prompt="Reply RETRY to re-upload.",
                    error="document_verification_failed",
                    data={
                        "recovery": "RETRY",
                        "document_code": target.document_code,
                        "verification_status": target.verification_status,
                    },
                )
        missing = self._missing_documents(app)
        if missing:
            return JourneyReply(
                application_id=app.application_id,
                state=app.current_state,
                message="Document stored and verified locally.",
                prompt=f"Next upload: {missing[0]}",
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
