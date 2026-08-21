"""Web text journey endpoints — Income Certificate POC."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_gateway
from app.api.v1.schemas import (
    ConsentRequest,
    JourneyMessageRequest,
    JourneyResponse,
    StartJourneyRequest,
)
from app.boundary.gateway import DataBoundaryGateway
from app.core.database import get_db
from app.services.catalogue import get_service
from app.services.documents import DocumentValidationError, store_document
from app.services.journey import JourneyService
from app.services.state_machine import InvalidTransitionError

router = APIRouter(prefix="/journey", tags=["journey"])

SERVICE_CODE = "INCOME_CERTIFICATE"


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _require_token(x_session_token: str | None) -> str:
    if not x_session_token:
        raise HTTPException(status_code=401, detail="X-Session-Token header required")
    return x_session_token


def _to_response(reply) -> JourneyResponse:
    return JourneyResponse(
        application_id=reply.application_id,
        state=reply.state,
        message=reply.message,
        prompt=reply.prompt,
        access_token=reply.access_token,
        data=reply.data,
        error=reply.error,
        expected_format=reply.expected_format,
    )


@router.post("/start", response_model=JourneyResponse)
def start_journey(
    body: StartJourneyRequest,
    request: Request,
    db: Session = Depends(get_db),
    gateway: DataBoundaryGateway = Depends(get_gateway),
) -> JourneyResponse:
    service = JourneyService(db, gateway=gateway)
    reply = service.start(channel=body.channel, trace_id=_trace(request))
    db.commit()
    return _to_response(reply)


@router.get("/{application_id}", response_model=JourneyResponse)
def get_journey(
    application_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None),
) -> JourneyResponse:
    token = _require_token(x_session_token)
    service = JourneyService(db)
    try:
        reply = service.get_status(application_id, token)
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    return _to_response(reply)


@router.post("/{application_id}/message", response_model=JourneyResponse)
def post_message(
    application_id: str,
    body: JourneyMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
    gateway: DataBoundaryGateway = Depends(get_gateway),
    x_session_token: str | None = Header(default=None),
) -> JourneyResponse:
    token = _require_token(x_session_token)
    service = JourneyService(db, gateway=gateway)
    try:
        reply = service.handle_message(
            application_id, token, body.text, trace_id=_trace(request)
        )
        db.commit()
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    except InvalidTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _to_response(reply)


@router.post("/{application_id}/consent", response_model=JourneyResponse)
def post_consent(
    application_id: str,
    body: ConsentRequest,
    request: Request,
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None),
) -> JourneyResponse:
    token = _require_token(x_session_token)
    service = JourneyService(db)
    try:
        reply = service.record_consent(
            application_id, token, granted=body.granted, trace_id=_trace(request)
        )
        db.commit()
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    except InvalidTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return _to_response(reply)


@router.post("/{application_id}/documents/{document_code}", response_model=JourneyResponse)
async def upload_document(
    application_id: str,
    document_code: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None),
) -> JourneyResponse:
    token = _require_token(x_session_token)
    service = JourneyService(db)
    try:
        app = service._get_app_by_ref(application_id)
        session = service._get_session(app, token)
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    if app.current_state not in {"DOCUMENT_CAPTURE", "DOCUMENT_REJECTED"}:
        raise HTTPException(
            status_code=409,
            detail=f"Documents cannot be uploaded in state {app.current_state}",
        )

    catalogue = get_service(SERVICE_CODE)
    doc_def = catalogue.document_by_code(document_code.upper())
    if not doc_def:
        raise HTTPException(status_code=400, detail="Unknown document code")

    try:
        await store_document(
            db,
            application_pk=app.id,
            document_def=doc_def,
            upload=file,
            actor_id=app.applicant_id,
            trace_id=_trace(request),
        )
        # Refresh relationship
        db.refresh(app)
        reply = service.after_document_upload(
            application_id, session.access_token, trace_id=_trace(request)
        )
        db.commit()
    except DocumentValidationError as exc:
        db.rollback()
        try:
            # Re-load after rollback
            svc = JourneyService(db)
            app2 = svc._get_app_by_ref(application_id)
            if app2.current_state == "DOCUMENT_CAPTURE":
                reply = svc.mark_document_rejected(
                    application_id,
                    token,
                    reason=str(exc),
                    trace_id=_trace(request),
                )
                db.commit()
                response = _to_response(reply)
                response.error = "document_rejected"
                return response
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except HTTPException:
            raise
        except Exception:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from None
    except InvalidTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None

    return _to_response(reply)
