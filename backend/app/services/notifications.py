"""Citizen status notifications — persist + mock-channel delivery.

Dedupe is cycle-based: repeating the same status does not insert again.
A new meaningful transition (for example UNDER_REVIEW → NEEDS_CORRECTION,
or NEEDS_CORRECTION → resubmit UNDER_REVIEW) creates new rows.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.adapters.notifications import (
    MockEmailProvider,
    MockSmsProvider,
    MockWhatsAppProvider,
    NotificationProvider,
)
from app.models.application import Application
from app.models.notification import CitizenNotification
from app.services.catalogue import get_service
from app.services.documents import ISSUED_CERTIFICATE_CODE, get_document
from app.services.i18n import field_label_for_confirm
from app.services.i18n import t as i18n_t
from app.services.state_machine import ProcessingStatus

SUBMITTED = ProcessingStatus.SUBMITTED.value
UNDER_REVIEW = ProcessingStatus.UNDER_REVIEW.value
NEEDS_CORRECTION = ProcessingStatus.NEEDS_CORRECTION.value
ISSUED = ProcessingStatus.ISSUED.value
REJECTED = ProcessingStatus.REJECTED.value

_BREAK_EVENTS = frozenset({NEEDS_CORRECTION, ISSUED, REJECTED})

_I18N_BODY = {
    SUBMITTED: "notification_submitted",
    UNDER_REVIEW: "notification_under_review",
    NEEDS_CORRECTION: "notification_needs_correction",
    ISSUED: "notification_issued",
    REJECTED: "notification_rejected",
}
_I18N_SUBJECT = {
    SUBMITTED: "notification_email_subject_submitted",
    UNDER_REVIEW: "notification_email_subject_under_review",
    NEEDS_CORRECTION: "notification_email_subject_needs_correction",
    ISSUED: "notification_email_subject_issued",
    REJECTED: "notification_email_subject_rejected",
}


def localized_service_name(service_code: str, language: str | None) -> str:
    defn = get_service(service_code)
    lang = (language or "en").lower()
    names = defn.selection.display_names if defn.selection else {}
    if names and lang in names:
        return names[lang]
    return defn.display_name


def _mobile_from_app(app: Application) -> str:
    data = app.form_data or {}
    raw = str(data.get("mobile_number") or app.pending_mobile or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def _email_from_app(app: Application) -> str | None:
    data = app.form_data or {}
    raw = str(data.get("email") or "").strip()
    if not raw or "@" not in raw:
        return None
    return raw


class NotificationService:
    def __init__(
        self,
        db: Session,
        *,
        sms: NotificationProvider | None = None,
        whatsapp: NotificationProvider | None = None,
        email: NotificationProvider | None = None,
    ) -> None:
        self.db = db
        self.sms = sms or MockSmsProvider()
        self.whatsapp = whatsapp or MockWhatsAppProvider()
        self.email = email or MockEmailProvider()

    def notify_submission(self, app: Application) -> list[CitizenNotification]:
        """Citizen submit: journey SUBMITTED and processing UNDER_REVIEW together."""
        return self._ensure_events(app, (SUBMITTED, UNDER_REVIEW))

    def notify_status(self, app: Application, event_type: str) -> list[CitizenNotification]:
        if event_type not in _I18N_BODY:
            return []
        if event_type in (SUBMITTED, UNDER_REVIEW):
            return self.notify_submission(app)
        return self._ensure_events(app, (event_type,))

    def list_for_application(self, app: Application) -> list[dict[str, Any]]:
        rows = self._ordered(app)
        cert_ready = (
            app.processing_status == ISSUED
            and get_document(self.db, app.id, ISSUED_CERTIFICATE_CODE) is not None
        )
        return [self.to_public(row, app, certificate_ready=cert_ready) for row in rows]

    def to_public(
        self,
        row: CitizenNotification,
        app: Application,
        *,
        certificate_ready: bool,
    ) -> dict[str, Any]:
        channels = list(row.channels or [])
        return {
            "id": row.id,
            "application_id": app.application_id,
            "event_type": row.event_type,
            "message": row.message,
            "subject": row.subject,
            "channels": channels,
            "delivery_status": row.delivery_status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "language": row.language,
            "recipient_mobile_last4": row.recipient_mobile_last4,
            "has_email": bool(row.recipient_email),
            "certificate_available": row.event_type == ISSUED and certificate_ready,
            "continue_available": row.event_type == NEEDS_CORRECTION,
            "simulated": True,
        }

    def _ensure_events(
        self, app: Application, event_types: tuple[str, ...]
    ) -> list[CitizenNotification]:
        created: list[CitizenNotification] = []
        cycle = self._cycle_event_types(app)
        for event_type in event_types:
            if event_type in cycle:
                continue
            row = self._persist(app, event_type)
            created.append(row)
            cycle.add(event_type)
        return created

    def _cycle_event_types(self, app: Application) -> set[str]:
        types: set[str] = set()
        for row in self._ordered(app):
            if row.event_type in _BREAK_EVENTS:
                types = {row.event_type}
            else:
                types.add(row.event_type)
        return types

    def _ordered(self, app: Application) -> list[CitizenNotification]:
        return (
            self.db.query(CitizenNotification)
            .filter(CitizenNotification.application_id == app.id)
            .order_by(CitizenNotification.created_at.asc())
            .all()
        )

    def _persist(self, app: Application, event_type: str) -> CitizenNotification:
        language = (app.language or "en").lower()
        service_name = localized_service_name(app.service_code, language)
        body_key = _I18N_BODY[event_type]
        extra: dict[str, str] = {}
        if event_type == NEEDS_CORRECTION and app.correcting_field:
            body_key = "notification_needs_correction_field"
            extra["field"] = field_label_for_confirm(app.correcting_field, language)
        body = i18n_t(
            body_key,
            language,
            service_name=service_name,
            application_id=app.application_id,
            **extra,
        )
        subject = i18n_t(
            _I18N_SUBJECT[event_type],
            language,
            service_name=service_name,
            application_id=app.application_id,
        )
        mobile = _mobile_from_app(app)
        email = _email_from_app(app)
        channels: list[str] = []
        if mobile:
            if self.sms.deliver(recipient=mobile, message=body):
                channels.append("sms")
            if self.whatsapp.deliver(recipient=mobile, message=body):
                channels.append("whatsapp")
        if email and self.email.deliver(recipient=email, message=body, subject=subject):
            channels.append("email")
        row = CitizenNotification(
            application_id=app.id,
            event_type=event_type,
            message=body,
            subject=subject,
            language=language,
            recipient_mobile_last4=mobile[-4:] if len(mobile) >= 4 else None,
            recipient_email=email,
            channels=channels,
            delivery_status="simulated",
        )
        self.db.add(row)
        self.db.flush()
        return row
