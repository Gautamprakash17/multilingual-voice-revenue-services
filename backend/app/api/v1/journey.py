"""Web text journey endpoints — Income Certificate POC."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
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
from app.services.documents import (
    ISSUED_CERTIFICATE_CODE,
    DocumentValidationError,
    store_document,
)
from app.services.i18n import document_label
from app.services.i18n import t as i18n_t
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


@router.get("/{application_id}/receipt", response_model=JourneyResponse)
def get_receipt(
    application_id: str,
    request: Request,
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None),
) -> JourneyResponse:
    token = _require_token(x_session_token)
    service = JourneyService(db)
    try:
        reply = service.get_receipt(application_id, token)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    return _to_response(reply)


@router.get("/{application_id}/documents/{document_code}")
def download_issued_certificate(
    application_id: str,
    document_code: str,
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None),
    download: bool = False,
) -> Response:
    """Citizen download of the issued certificate. Requires the session token."""
    token = _require_token(x_session_token)
    if document_code.upper() != ISSUED_CERTIFICATE_CODE:
        raise HTTPException(status_code=404, detail="Document not found")
    service = JourneyService(db)
    try:
        payload, filename = service.get_issued_certificate_bytes(application_id, token)
    except LookupError:
        raise HTTPException(status_code=404, detail="Issued certificate not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None
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


@router.post("/{application_id}/message", response_model=JourneyResponse)
def post_message(
    application_id: str,
    body: JourneyMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
    gateway: DataBoundaryGateway = Depends(get_gateway),
    x_session_token: str | None = Header(default=None),
) -> JourneyResponse:
    """Web text messages go through the channel-agnostic envelope + orchestrator."""
    token = _require_token(x_session_token)
    from app.channels.orchestrator import ChannelOrchestrator

    orch = ChannelOrchestrator(db, gateway=gateway)
    try:
        reply = orch.process_channel_payload(
            "web",
            {
                "application_id": application_id,
                "access_token": token,
                "session_ref": token,
                "modality": "text",
                "text": body.text,
                "trace_id": _trace(request),
            },
        )
        db.commit()
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    except InvalidTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return JourneyResponse(
        application_id=reply.application_id,
        state=reply.state,
        message=reply.message,
        prompt=reply.prompt,
        access_token=reply.access_token,
        data={
            **(reply.data or {}),
            "language": reply.language,
            "intent": reply.intent,
            "channel": reply.channel,
        },
        error=reply.error,
        expected_format=reply.expected_format,
    )


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
    document_type: str | None = Form(default=None),
    db: Session = Depends(get_db),
    gateway: DataBoundaryGateway = Depends(get_gateway),
    x_session_token: str | None = Header(default=None),
) -> JourneyResponse:
    token = _require_token(x_session_token)
    service = JourneyService(db, gateway=gateway)
    try:
        app = service._get_app_by_ref(application_id)
        session = service._get_session(app, token)
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    if app.current_state not in {"DOCUMENT_CAPTURE", "DOCUMENT_REJECTED", "CORRECTION"}:
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
            form_data=dict(app.form_data or {}),
            gateway=gateway,
            document_type=document_type,
        )
        db.refresh(app)
        reply = service.after_document_upload(
            application_id,
            session.access_token,
            trace_id=_trace(request),
            document_code=doc_def.code,
        )
        db.commit()
    except DocumentValidationError as exc:
        db.rollback()
        lang = app.language or "en"
        category = document_label(doc_def.code, catalogue, lang)
        detail = str(exc)
        if "Document type is required" in detail:
            detail = i18n_t("document_type_required", lang)
        elif "is not accepted" in detail:
            detail = i18n_t("document_type_unsupported", lang, document_name=category)
        try:
            svc = JourneyService(db)
            app2 = svc._get_app_by_ref(application_id)
            if app2.current_state == "DOCUMENT_CAPTURE":
                reply = svc.mark_document_rejected(
                    application_id,
                    token,
                    reason=detail,
                    trace_id=_trace(request),
                )
                db.commit()
                response = _to_response(reply)
                response.error = "document_rejected"
                response.message = detail
                return response
            raise HTTPException(status_code=400, detail=detail) from None
        except HTTPException:
            raise
        except Exception:
            db.rollback()
            raise HTTPException(status_code=400, detail=detail) from None
    except InvalidTransitionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None

    return _to_response(reply)
