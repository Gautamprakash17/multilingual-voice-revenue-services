"""Officer review APIs — RBAC via X-Officer-Token (POC)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.certificate import CertificateGenerationError
from app.services.documents import ISSUED_CERTIFICATE_CODE
from app.services.officer import (
    OfficerActionError,
    OfficerAuthError,
    OfficerService,
    require_officer,
)

router = APIRouter(prefix="/officer", tags=["officer"])


class OfficerActionRequest(BaseModel):
    reason: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=500)
    target_fields: list[str] = Field(default_factory=list)


class OfficerApplicationResponse(BaseModel):
    application_id: str
    service_code: str
    journey_state: str
    processing_status: str
    language: str | None = None
    escalated: bool = False
    payment_completed: bool = False
    payment_ref: str | None = None
    correction_notes: str | None = None
    documents: list[dict] = Field(default_factory=list)
    fields_present: list[str] = Field(default_factory=list)
    created_at: str | None = None
    channel: str | None = None
    issued_certificate: dict | None = None


class OfficerHistoryItemResponse(BaseModel):
    application_id: str
    service_code: str
    service_display_name: str
    processing_status: str
    journey_state: str
    last_action: str
    last_action_label: str
    action_at: str
    escalated: bool = False


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _officer(x_officer_token: str | None = Header(default=None)) -> str:
    try:
        return require_officer(x_officer_token)
    except OfficerAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None


def _to_resp(view) -> OfficerApplicationResponse:
    return OfficerApplicationResponse(
        application_id=view.application_id,
        service_code=view.service_code,
        journey_state=view.journey_state,
        processing_status=view.processing_status,
        language=view.language,
        escalated=view.escalated,
        payment_completed=view.payment_completed,
        payment_ref=view.payment_ref,
        correction_notes=view.correction_notes,
        documents=view.documents,
        fields_present=view.fields_present,
        created_at=view.created_at,
        channel=view.channel,
        issued_certificate=view.issued_certificate,
    )


def _to_history(item) -> OfficerHistoryItemResponse:
    return OfficerHistoryItemResponse(
        application_id=item.application_id,
        service_code=item.service_code,
        service_display_name=item.service_display_name,
        processing_status=item.processing_status,
        journey_state=item.journey_state,
        last_action=item.last_action,
        last_action_label=item.last_action_label,
        action_at=item.action_at,
        escalated=item.escalated,
    )


@router.get("/queue", response_model=list[OfficerApplicationResponse])
def list_queue(
    db: Session = Depends(get_db),
    actor_id: str = Depends(_officer),
) -> list[OfficerApplicationResponse]:
    _ = actor_id
    return [_to_resp(v) for v in OfficerService(db).list_queue()]


@router.get("/history", response_model=list[OfficerHistoryItemResponse])
def list_history(
    limit: int = 50,
    db: Session = Depends(get_db),
    actor_id: str = Depends(_officer),
) -> list[OfficerHistoryItemResponse]:
    """Completed officer actions from the append-only audit trail."""
    _ = actor_id
    return [_to_history(item) for item in OfficerService(db).list_history(limit=limit)]


@router.get("/{application_id}", response_model=OfficerApplicationResponse)
def get_application(
    application_id: str,
    db: Session = Depends(get_db),
    actor_id: str = Depends(_officer),
) -> OfficerApplicationResponse:
    """Application detail for queue or history selection."""
    _ = actor_id
    try:
        return _to_resp(OfficerService(db).get_application(application_id))
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None


@router.post("/{application_id}/approve", response_model=OfficerApplicationResponse)
def approve(
    application_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor_id: str = Depends(_officer),
) -> OfficerApplicationResponse:
    try:
        view = OfficerService(db).approve(
            application_id, actor_id=actor_id, trace_id=_trace(request)
        )
        db.commit()
        return _to_resp(view)
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except CertificateGenerationError:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Certificate PDF could not be generated. The application was not issued.",
        ) from None
    except OfficerActionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get("/{application_id}/documents/{document_code}")
def download_officer_document(
    application_id: str,
    document_code: str,
    db: Session = Depends(get_db),
    actor_id: str = Depends(_officer),
    download: bool = False,
) -> Response:
    """Stream an issued certificate. Never returns storage paths."""
    _ = actor_id
    if document_code.upper() != ISSUED_CERTIFICATE_CODE:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        payload, filename = OfficerService(db).get_issued_certificate_bytes(application_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Issued certificate not found") from None
    disposition = "attachment" if download else "inline"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.post("/{application_id}/reject", response_model=OfficerApplicationResponse)
def reject(
    application_id: str,
    body: OfficerActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor_id: str = Depends(_officer),
) -> OfficerApplicationResponse:
    try:
        view = OfficerService(db).reject(
            application_id,
            reason=body.reason or "Rejected by officer",
            actor_id=actor_id,
            trace_id=_trace(request),
        )
        db.commit()
        return _to_resp(view)
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except OfficerActionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{application_id}/request-correction", response_model=OfficerApplicationResponse)
def request_correction(
    application_id: str,
    body: OfficerActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor_id: str = Depends(_officer),
) -> OfficerApplicationResponse:
    try:
        view = OfficerService(db).request_correction(
            application_id,
            notes=body.notes or body.reason or "Please correct highlighted fields",
            target_fields=body.target_fields,
            actor_id=actor_id,
            trace_id=_trace(request),
        )
        db.commit()
        return _to_resp(view)
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except OfficerActionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{application_id}/escalate", response_model=OfficerApplicationResponse)
def escalate(
    application_id: str,
    body: OfficerActionRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor_id: str = Depends(_officer),
) -> OfficerApplicationResponse:
    try:
        view = OfficerService(db).escalate(
            application_id,
            reason=body.reason or "Escalated by officer",
            actor_id=actor_id,
            trace_id=_trace(request),
        )
        db.commit()
        return _to_resp(view)
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except OfficerActionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
