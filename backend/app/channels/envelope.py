"""Channel-agnostic message envelope — sole input contract for orchestration."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.boundary.classification import Classification, parse_classification
from app.services.languages import get_language_catalog


class Channel(StrEnum):
    WEB = "web"
    WHATSAPP = "whatsapp"
    IVR = "ivr"


class Modality(StrEnum):
    TEXT = "text"
    VOICE = "voice"
    DTMF = "dtmf"
    MEDIA = "media"


class MessageEnvelope(BaseModel):
    """Normalized inbound message. Classification defaults to RESTRICTED."""

    session_ref: str | None = None
    application_ref: str | None = None
    channel: Channel
    modality: Modality
    content: dict[str, Any] = Field(default_factory=dict)
    language: str | None = None
    classification: Classification = Classification.RESTRICTED
    trace_id: str | None = None

    @field_validator("classification", mode="before")
    @classmethod
    def _fail_closed_classification(cls, value: Any) -> Classification:
        return parse_classification(value)

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        lang = value.strip().lower()
        catalog = get_language_catalog()
        if not catalog.is_supported(lang):
            codes = ", ".join(sorted(catalog.codes))
            raise ValueError(f"language must be one of: {codes}")
        return lang

    @model_validator(mode="after")
    def _validate_content(self) -> MessageEnvelope:
        if (
            self.modality == Modality.TEXT
            and not (self.content.get("text") or self.content.get("dtmf"))
            and not self.content.get("action")
        ):
            raise ValueError("text modality requires content.text")
        if self.modality == Modality.VOICE and not (
            self.content.get("audio_b64")
            or self.content.get("transcript")
            or self.content.get("audio_ref")
        ):
            raise ValueError(
                "voice modality requires content.audio_b64, transcript, or audio_ref"
            )
        if self.modality == Modality.DTMF and not self.content.get("dtmf"):
            raise ValueError("dtmf modality requires content.dtmf")
        return self

    def text_payload(self) -> str:
        """Extract user text for journey (never log the return value)."""
        if self.modality == Modality.DTMF:
            return str(self.content.get("dtmf") or "").strip()
        if self.modality == Modality.VOICE:
            return str(self.content.get("transcript") or "").strip()
        return str(self.content.get("text") or "").strip()


def validate_envelope(data: dict[str, Any]) -> MessageEnvelope:
    """Validate and normalize an inbound envelope dict."""
    return MessageEnvelope.model_validate(data)
