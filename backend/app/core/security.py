"""Security helpers — headers and sensitive-field redaction."""

from typing import Any

# Fields that must never appear in logs or audit metadata payloads.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "token",
        "api_key",
        "apikey",
        "secret",
        "authorization",
        "otp",
        "aadhaar",
        "raw_audio",
        "audio",
        "document_content",
        "document_bytes",
        "citizen_data",
        "ssn",
        "pan",
    }
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "0",
    "Cache-Control": "no-store",
}


def redact_sensitive(data: Any, depth: int = 0) -> Any:
    """Recursively redact sensitive keys from dict-like structures."""
    if depth > 8:
        return "[truncated]"
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for key, value in data.items():
            if str(key).lower().replace("-", "_") in SENSITIVE_KEYS:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_sensitive(value, depth + 1)
        return result
    if isinstance(data, list):
        return [redact_sensitive(item, depth + 1) for item in data[:50]]
    return data
