"""Channel-agnostic APIs — web / WhatsApp sim / IVR sim / voice / resume / metrics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_gateway
from app.boundary.gateway import DataBoundaryGateway
from app.channels.envelope import Channel
from app.channels.orchestrator import ChannelOrchestrator, ChannelReply
from app.core.database import get_db
from app.platform.metrics import get_metrics
from app.services.state_machine import InvalidTransitionError
from app.speech.tts import TTSUnavailableError

router = APIRouter(tags=["channels"])

_CITIZEN_TTS_UNAVAILABLE = "Speech playback is temporarily unavailable. Please continue with text."


def _raise_tts_unavailable() -> None:
    raise HTTPException(status_code=503, detail=_CITIZEN_TTS_UNAVAILABLE)


class ChannelMessageRequest(BaseModel):
    application_id: str
    text: str | None = None
    modality: str = "text"
    language: str | None = None
    dtmf: str | None = None
    audio_b64: str | None = None
    transcript: str | None = None
    content: dict[str, Any] | None = None


class ResumeRequest(BaseModel):
    application_id: str
    channel: str = Field(description="Target channel: web | whatsapp | ivr")


class ChannelResponse(BaseModel):
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
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    expected_format: str | None = None


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _token(x_session_token: str | None) -> str:
    if not x_session_token:
        raise HTTPException(status_code=401, detail="X-Session-Token header required")
    return x_session_token


def _to_response(reply: ChannelReply) -> ChannelResponse:
    return ChannelResponse(
        application_id=reply.application_id,
        state=reply.state,
        message=reply.message,
        prompt=reply.prompt,
        access_token=reply.access_token,
        language=reply.language,
        channel=reply.channel,
        transcript=reply.transcript,
        intent=reply.intent,
        audio_b64=reply.audio_b64,
        audio_mime=reply.audio_mime,
        data=reply.data,
        error=reply.error,
        expected_format=reply.expected_format,
    )


@router.post("/channels/{channel}/start", response_model=ChannelResponse)
def channel_start(
    channel: str,
    request: Request,
    db: Session = Depends(get_db),
    gateway: DataBoundaryGateway = Depends(get_gateway),
) -> ChannelResponse:
    try:
        Channel(channel.lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported channel") from exc
    orch = ChannelOrchestrator(db, gateway=gateway)
    try:
        reply = orch.start(channel=channel.lower(), trace_id=_trace(request))
        db.commit()
    except TTSUnavailableError:
        db.rollback()
        get_metrics().record_channel_error()
        _raise_tts_unavailable()
    return _to_response(reply)


@router.post("/channels/{channel}/message", response_model=ChannelResponse)
def channel_message(
    channel: str,
    body: ChannelMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
    gateway: DataBoundaryGateway = Depends(get_gateway),
    x_session_token: str | None = Header(default=None),
) -> ChannelResponse:
    token = _token(x_session_token)
    try:
        Channel(channel.lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported channel") from exc

    payload: dict[str, Any] = {
        "application_id": body.application_id,
        "access_token": token,
        "session_ref": token,
        "modality": body.modality,
        "language": body.language,
        "trace_id": _trace(request),
        "content": body.content or {},
    }
    if body.text is not None:
        payload["text"] = body.text
        payload["content"]["text"] = body.text
    if body.dtmf is not None:
        payload["dtmf"] = body.dtmf
    if body.audio_b64 is not None:
        payload["audio_b64"] = body.audio_b64
    if body.transcript is not None:
        payload["transcript"] = body.transcript

    orch = ChannelOrchestrator(db, gateway=gateway)
    try:
        reply = orch.process_channel_payload(channel.lower(), payload)
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
        get_metrics().record_channel_error()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except TTSUnavailableError:
        db.rollback()
        get_metrics().record_channel_error()
        _raise_tts_unavailable()
    return _to_response(reply)


@router.post("/channels/resume", response_model=ChannelResponse)
def channel_resume(
    body: ResumeRequest,
    request: Request,
    db: Session = Depends(get_db),
    gateway: DataBoundaryGateway = Depends(get_gateway),
    x_session_token: str | None = Header(default=None),
) -> ChannelResponse:
    token = _token(x_session_token)
    orch = ChannelOrchestrator(db, gateway=gateway)
    try:
        reply = orch.resume(
            application_id=body.application_id,
            access_token=token,
            channel=body.channel.lower(),
            trace_id=_trace(request),
        )
        db.commit()
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except TTSUnavailableError:
        db.rollback()
        get_metrics().record_channel_error()
        _raise_tts_unavailable()
    return _to_response(reply)


@router.get("/metrics")
def metrics() -> dict[str, Any]:
    return {"status": "ok", "metrics": get_metrics().snapshot()}
