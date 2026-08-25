"""Officer review service — server-side RBAC for approve/reject/correct/escalate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.boundary.classification import Classification
from app.core.config import get_settings
from app.models.application import Application, ConversationSession
from app.models.audit import AuditEvent
from app.platform.audit import write_audit_event
from app.platform.metrics import get_metrics
from app.services.application_ids import normalize_application_id
from app.services.catalogue import get_service
from app.services.certificate import (
    CertificateGenerationError,
    certificate_filename,
    render_income_certificate_pdf,
)
from app.services.documents import (
    ISSUED_CERTIFICATE_CODE,
    get_document,
    read_stored_bytes,
    store_issued_certificate,
)
from app.services.notifications import ISSUED, NEEDS_CORRECTION, REJECTED, NotificationService
from app.services.state_machine import JourneyState, ProcessingStatus, assert_transition


class OfficerAuthError(PermissionError):
    pass


class OfficerActionError(ValueError):
    pass


@dataclass
class OfficerView:
    application_id: str
    service_code: str
    journey_state: str
    processing_status: str
    language: str | None
    escalated: bool
    payment_completed: bool
    payment_ref: str | None
    correction_notes: str | None
    documents: list[dict[str, Any]]
    fields_present: list[str]
    # Safe metadata only — no storage paths, no raw restricted field values by default
    created_at: str | None
    channel: str | None = None
    issued_certificate: dict[str, Any] | None = None


@dataclass
class OfficerHistoryItem:
    """Summary of a completed officer action — derived from audit + application."""

    application_id: str
    service_code: str
    service_display_name: str
    processing_status: str
    journey_state: str
    last_action: str
    last_action_label: str
    action_at: str
    escalated: bool = False


# Audit event types that represent completed officer work (newest wins per app).
_OFFICER_HISTORY_EVENTS: dict[str, str] = {
    "CERTIFICATE_ISSUED": "Approved and issued",
    "OFFICER_REJECTED": "Rejected",
    "OFFICER_ESCALATED": "Escalated",
    "OFFICER_REQUEST_CORRECTION": "Requested correction",
}


def require_officer(token: str | None) -> str:
    settings = get_settings()
    expected = settings.officer_api_token
    if not token or token != expected:
        raise OfficerAuthError("Officer authentication required")
    return "officer"


class OfficerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _audit(
        self,
        event_type: str,
        *,
        actor_id: str,
        metadata: dict[str, Any],
        trace_id: str | None,
    ) -> None:
        write_audit_event(
            self.db,
            event_type=event_type,
            classification=Classification.INTERNAL.value,
            trace_id=trace_id,
            actor_id=actor_id,
            metadata=metadata,
        )

    def _get_app(self, application_id: str) -> Application:
        ref = normalize_application_id(application_id)
        app = self.db.query(Application).filter(Application.application_id == ref).one_or_none()
        if not app:
            raise LookupError("Application not found")
        return app

    def _session(self, app: Application) -> ConversationSession | None:
        return (
            self.db.query(ConversationSession)
            .filter(ConversationSession.application_id == app.id)
            .order_by(ConversationSession.last_activity_at.desc())
            .first()
        )

    def _issued_certificate_meta(self, app: Application) -> dict[str, Any] | None:
        record = get_document(self.db, app.id, ISSUED_CERTIFICATE_CODE)
        if not record:
            return None
        return {
            "code": ISSUED_CERTIFICATE_CODE,
            "available": True,
            "filename": record.original_filename,
            "mime_type": record.mime_type,
            "size_bytes": record.size_bytes,
            "issued_at": record.created_at.isoformat() if record.created_at else None,
        }

    def _view(self, app: Application) -> OfficerView:
        session = self._session(app)
        return OfficerView(
            application_id=app.application_id,
            service_code=app.service_code,
            journey_state=app.current_state,
            processing_status=app.processing_status,
            language=app.language,
            escalated=bool(app.escalated),
            payment_completed=bool(app.payment_completed),
            payment_ref=app.payment_ref,
            correction_notes=app.correction_notes,
            documents=[
                {
                    "code": d.document_code,
                    "verification_status": d.verification_status,
                    "verification_reason": d.verification_reason,
                    "mime_type": d.mime_type,
                    "size_bytes": d.size_bytes,
                }
                for d in app.documents
            ],
            fields_present=list((app.form_data or {}).keys()),
            created_at=app.created_at.isoformat() if app.created_at else None,
            # Latest session channel is display metadata only — never a queue filter.
            channel=session.channel if session else None,
            issued_certificate=self._issued_certificate_meta(app),
        )

    def list_queue(self) -> list[OfficerView]:
        statuses = {
            ProcessingStatus.SUBMITTED.value,
            ProcessingStatus.UNDER_REVIEW.value,
            ProcessingStatus.NEEDS_CORRECTION.value,
        }
        apps = (
            self.db.query(Application)
            .filter(
                (Application.processing_status.in_(statuses))
                | (Application.escalated.is_(True))
                | (Application.current_state == JourneyState.ESCALATED.value)
            )
            .order_by(Application.updated_at.desc())
            .all()
        )
        return [self._view(a) for a in apps]

    def get_application(self, application_id: str) -> OfficerView:
        """Load a single application for officer detail (active or historical)."""
        return self._view(self._get_app(application_id))

    def list_history(self, *, limit: int = 50) -> list[OfficerHistoryItem]:
        """Officer-completed actions from the append-only audit trail.

        Active queue filters exclude ISSUED/REJECTED — history surfaces those
        (and other officer actions) from persisted audit events. One row per
        application, newest qualifying action first.
        """
        capped = max(1, min(int(limit), 200))
        events = (
            self.db.query(AuditEvent)
            .filter(AuditEvent.event_type.in_(tuple(_OFFICER_HISTORY_EVENTS)))
            .order_by(AuditEvent.timestamp.desc())
            .limit(capped * 8)
            .all()
        )
        seen: set[str] = set()
        items: list[OfficerHistoryItem] = []
        for event in events:
            meta = event.metadata_json or {}
            ref = meta.get("application_ref")
            if not isinstance(ref, str) or not ref or ref in seen:
                continue
            try:
                app = self._get_app(ref)
            except LookupError:
                continue
            seen.add(ref)
            label = _OFFICER_HISTORY_EVENTS.get(event.event_type, event.event_type)
            try:
                display = get_service(app.service_code).display_name
            except KeyError:
                display = app.service_code
            items.append(
                OfficerHistoryItem(
                    application_id=app.application_id,
                    service_code=app.service_code,
                    service_display_name=display,
                    processing_status=app.processing_status,
                    journey_state=app.current_state,
                    last_action=event.event_type,
                    last_action_label=label,
                    action_at=event.timestamp.isoformat() if event.timestamp else "",
                    escalated=bool(app.escalated),
                )
            )
            if len(items) >= capped:
                break
        return items

    def _persist_issued_certificate(self, app: Application) -> None:
        """Generate and store the issued PDF. Must run before status becomes ISSUED."""
        previous = app.processing_status
        app.processing_status = ProcessingStatus.ISSUED.value
        try:
            pdf_bytes = render_income_certificate_pdf(app)
            store_issued_certificate(
                self.db,
                app,
                pdf_bytes,
                filename=certificate_filename(app.application_id),
            )
        except (CertificateGenerationError, ValueError, OSError) as exc:
            app.processing_status = previous
            raise CertificateGenerationError("Certificate PDF could not be generated") from exc
        finally:
            if app.processing_status != ProcessingStatus.ISSUED.value:
                app.processing_status = previous

    def get_issued_certificate_bytes(self, application_id: str) -> tuple[bytes, str]:
        """Return (pdf_bytes, filename) for the issued certificate of this application."""
        app = self._get_app(application_id)
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

    def approve(self, application_id: str, *, actor_id: str, trace_id: str | None) -> OfficerView:
        app = self._get_app(application_id)
        if app.processing_status == ProcessingStatus.ISSUED.value:
            # Idempotent retry: keep ISSUED, reuse existing PDF, do not re-audit.
            if get_document(self.db, app.id, ISSUED_CERTIFICATE_CODE) is None:
                self._persist_issued_certificate(app)
            return self._view(app)
        if app.processing_status not in {
            ProcessingStatus.UNDER_REVIEW.value,
            ProcessingStatus.SUBMITTED.value,
        }:
            raise OfficerActionError(
                f"Cannot approve from processing status {app.processing_status}"
            )
        self._persist_issued_certificate(app)
        app.processing_status = ProcessingStatus.APPROVED.value
        app.updated_at = datetime.now(UTC)
        get_metrics().record_status(app.processing_status)
        self._audit(
            "OFFICER_APPROVED",
            actor_id=actor_id,
            trace_id=trace_id,
            metadata={"application_ref": app.application_id, "status": app.processing_status},
        )
        app.processing_status = ProcessingStatus.ISSUED.value
        get_metrics().record_status(app.processing_status)
        self._audit(
            "CERTIFICATE_ISSUED",
            actor_id=actor_id,
            trace_id=trace_id,
            metadata={"application_ref": app.application_id, "status": app.processing_status},
        )
        NotificationService(self.db).notify_status(app, ISSUED)
        return self._view(app)

    def reject(
        self,
        application_id: str,
        *,
        reason: str,
        actor_id: str,
        trace_id: str | None,
    ) -> OfficerView:
        app = self._get_app(application_id)
        if app.processing_status not in {
            ProcessingStatus.UNDER_REVIEW.value,
            ProcessingStatus.SUBMITTED.value,
            ProcessingStatus.NEEDS_CORRECTION.value,
        }:
            raise OfficerActionError(
                f"Cannot reject from processing status {app.processing_status}"
            )
        app.processing_status = ProcessingStatus.REJECTED.value
        app.correction_notes = reason
        app.updated_at = datetime.now(UTC)
        get_metrics().record_status(app.processing_status)
        self._audit(
            "OFFICER_REJECTED",
            actor_id=actor_id,
            trace_id=trace_id,
            metadata={
                "application_ref": application_id,
                "status": app.processing_status,
                "reason": reason,
            },
        )
        NotificationService(self.db).notify_status(app, REJECTED)
        return self._view(app)

    def request_correction(
        self,
        application_id: str,
        *,
        notes: str,
        target_fields: list[str] | None,
        actor_id: str,
        trace_id: str | None,
    ) -> OfficerView:
        app = self._get_app(application_id)
        if app.processing_status not in {
            ProcessingStatus.UNDER_REVIEW.value,
            ProcessingStatus.SUBMITTED.value,
        }:
            raise OfficerActionError(f"Cannot request correction from {app.processing_status}")
        session = self._session(app)
        if not session:
            raise OfficerActionError("No citizen session bound to application")
        assert_transition(app.current_state, JourneyState.CORRECTION)
        previous = app.current_state
        app.current_state = JourneyState.CORRECTION.value
        session.current_state = JourneyState.CORRECTION.value
        app.processing_status = ProcessingStatus.NEEDS_CORRECTION.value
        app.correction_notes = notes
        if target_fields:
            # Targeted correction: clear only requested fields
            data = dict(app.form_data or {})
            for name in target_fields:
                data.pop(name, None)
            app.form_data = data
            app.correcting_field = target_fields[0] if len(target_fields) == 1 else None
        app.updated_at = datetime.now(UTC)
        get_metrics().record_correction()
        get_metrics().record_status(app.processing_status)
        self._audit(
            "OFFICER_REQUEST_CORRECTION",
            actor_id=actor_id,
            trace_id=trace_id,
            metadata={
                "application_ref": application_id,
                "from_state": previous,
                "to_state": JourneyState.CORRECTION.value,
                "target_fields": target_fields or [],
                # notes may be operational; keep short
                "notes_present": bool(notes),
            },
        )
        NotificationService(self.db).notify_status(app, NEEDS_CORRECTION)
        return self._view(app)

    def escalate(
        self,
        application_id: str,
        *,
        reason: str,
        actor_id: str,
        trace_id: str | None,
    ) -> OfficerView:
        app = self._get_app(application_id)
        session = self._session(app)
        if session and JourneyState(app.current_state) != JourneyState.ESCALATED:
            # From SUBMITTED, SM allows only CORRECTION — mark escalated flag instead
            if JourneyState(app.current_state) == JourneyState.SUBMITTED:
                app.escalated = True
            else:
                assert_transition(app.current_state, JourneyState.ESCALATED)
                app.current_state = JourneyState.ESCALATED.value
                session.current_state = JourneyState.ESCALATED.value
                app.escalated = True
        else:
            app.escalated = True
        app.updated_at = datetime.now(UTC)
        get_metrics().record_escalation()
        self._audit(
            "OFFICER_ESCALATED",
            actor_id=actor_id,
            trace_id=trace_id,
            metadata={
                "application_ref": application_id,
                "reason": reason,
                "journey_state": app.current_state,
            },
        )
        return self._view(app)
