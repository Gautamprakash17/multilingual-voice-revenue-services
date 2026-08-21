"""Human-friendly application ID generation (e.g. INC-4729)."""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.models.application import Application

_PREFIX = "INC"


def generate_application_id(db: Session, max_attempts: int = 20) -> str:
    """Generate a unique INC-XXXX style reference. Never uses DB primary keys."""
    for _ in range(max_attempts):
        candidate = f"{_PREFIX}-{secrets.randbelow(9000) + 1000}"
        exists = (
            db.query(Application.id)
            .filter(Application.application_id == candidate)
            .first()
        )
        if not exists:
            return candidate
    # Extremely unlikely fallback with extra entropy
    suffix = secrets.token_hex(2).upper()
    return f"{_PREFIX}-{suffix}"
