"""Journey API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StartJourneyRequest(BaseModel):
    channel: str = Field(default="web", max_length=32)


class JourneyMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ConsentRequest(BaseModel):
    granted: bool


class JourneyResponse(BaseModel):
    application_id: str
    state: str
    message: str
    prompt: str | None = None
    access_token: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    expected_format: str | None = None
