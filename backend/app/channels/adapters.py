"""Channel adapter interfaces and simulator implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from app.boundary.classification import Classification
from app.channels.envelope import Channel, MessageEnvelope, Modality


class ChannelAdapter(ABC):
    """Adapters normalize channel-specific payloads into MessageEnvelope."""

    channel: Channel

    @abstractmethod
    def to_envelope(self, payload: dict[str, Any]) -> MessageEnvelope:
        """Convert inbound channel payload to a validated envelope."""


class WebChannelAdapter(ChannelAdapter):
    channel = Channel.WEB

    def to_envelope(self, payload: dict[str, Any]) -> MessageEnvelope:
        modality = Modality(payload.get("modality", "text"))
        content = dict(payload.get("content") or {})
        if modality == Modality.TEXT and "text" not in content and payload.get("text"):
            content["text"] = payload["text"]
        if modality == Modality.VOICE and payload.get("audio_b64"):
            content["audio_b64"] = payload["audio_b64"]
        if modality == Modality.VOICE and payload.get("transcript"):
            content["transcript"] = payload["transcript"]
        return MessageEnvelope(
            session_ref=payload.get("session_ref") or payload.get("access_token"),
            application_ref=payload.get("application_ref")
            or payload.get("application_id"),
            channel=Channel.WEB,
            modality=modality,
            content=content,
            language=payload.get("language"),
            classification=parse_or_restricted(payload.get("classification")),
            trace_id=payload.get("trace_id") or str(uuid4()),
        )


class WhatsAppSimulatorAdapter(ChannelAdapter):
    channel = Channel.WHATSAPP

    def to_envelope(self, payload: dict[str, Any]) -> MessageEnvelope:
        # Mimic WhatsApp webhook-ish shape
        text = payload.get("text") or (payload.get("message") or {}).get("text")
        content = dict(payload.get("content") or {})
        if text and "text" not in content:
            content["text"] = text
        return MessageEnvelope(
            session_ref=payload.get("session_ref") or payload.get("access_token"),
            application_ref=payload.get("application_ref")
            or payload.get("application_id"),
            channel=Channel.WHATSAPP,
            modality=Modality.TEXT,
            content=content,
            language=payload.get("language"),
            classification=parse_or_restricted(payload.get("classification")),
            trace_id=payload.get("trace_id") or str(uuid4()),
        )


class IVRSimulatorAdapter(ChannelAdapter):
    channel = Channel.IVR

    def to_envelope(self, payload: dict[str, Any]) -> MessageEnvelope:
        dtmf = payload.get("dtmf")
        transcript = payload.get("transcript") or payload.get("speech_text")
        if dtmf is not None:
            modality = Modality.DTMF
            content = {"dtmf": str(dtmf)}
        elif payload.get("audio_b64") or transcript:
            modality = Modality.VOICE
            content = {}
            if payload.get("audio_b64"):
                content["audio_b64"] = payload["audio_b64"]
            if transcript:
                content["transcript"] = transcript
        else:
            modality = Modality.TEXT
            content = {"text": str(payload.get("text") or "")}
        return MessageEnvelope(
            session_ref=payload.get("session_ref")
            or payload.get("access_token")
            or payload.get("call_id"),
            application_ref=payload.get("application_ref")
            or payload.get("application_id"),
            channel=Channel.IVR,
            modality=modality,
            content=content,
            language=payload.get("language"),
            classification=parse_or_restricted(payload.get("classification")),
            trace_id=payload.get("trace_id") or str(uuid4()),
        )


def parse_or_restricted(value: Any) -> Classification:
    from app.boundary.classification import parse_classification

    return parse_classification(value)


def get_adapter(channel: str | Channel) -> ChannelAdapter:
    mapping: dict[Channel, ChannelAdapter] = {
        Channel.WEB: WebChannelAdapter(),
        Channel.WHATSAPP: WhatsAppSimulatorAdapter(),
        Channel.IVR: IVRSimulatorAdapter(),
    }
    ch = Channel(str(channel).lower())
    return mapping[ch]
