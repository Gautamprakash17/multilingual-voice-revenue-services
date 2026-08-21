"""JSON structured logging.

Never log passwords, tokens, API keys, OTPs, raw citizen data, audio, or documents.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.security import redact_sensitive


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", None),
            "request_id": getattr(record, "request_id", None),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(redact_sensitive(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Drop nulls for cleanliness
        return json.dumps({k: v for k, v in payload.items() if v is not None})


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger for JSON stdout output."""
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    trace_id: str | None = None,
    request_id: str | None = None,
    **fields: Any,
) -> None:
    """Emit a structured log event with automatic redaction."""
    logger.log(
        level,
        event,
        extra={
            "event": event,
            "trace_id": trace_id,
            "request_id": request_id,
            "extra_fields": redact_sensitive(fields),
        },
    )
