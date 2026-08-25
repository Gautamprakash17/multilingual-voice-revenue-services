"""Local synthetic SMS inbox for the demo phone simulator.

This is NOT an authentication API and NOT a real SMS provider.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.journey import JourneyService
from app.services.notifications import NotificationService
from app.services.state_machine import JourneyState

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/sms")
def get_demo_sms(
    application_id: str = Query(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None),
) -> dict:
    if not x_session_token:
        raise HTTPException(status_code=401, detail="X-Session-Token header required")
    service = JourneyService(db)
    try:
        app = service._get_app_by_ref(application_id)
        service._get_session(app, x_session_token)
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    if JourneyState(app.current_state) != JourneyState.AUTHENTICATE:
        return {"active": False}
    if (app.auth_step or "") != "otp" or not app.pending_mobile:
        return {"active": False}

    peek = getattr(service.identity, "get_demo_sms", None)
    sms = peek(app.pending_mobile) if callable(peek) else None
    if sms is None:
        return {"active": False}
    return {
        "active": True,
        "from": sms.sender,
        "label": sms.label,
        "code": sms.code,
        "issued_at": sms.issued_at.isoformat(),
        "mobile_last4": (app.pending_mobile or "")[-4:],
    }


@router.get("/notifications")
def get_demo_notifications(
    application_id: str = Query(..., min_length=3, max_length=32),
    db: Session = Depends(get_db),
    x_session_token: str | None = Header(default=None),
) -> dict:
    """Simulated citizen inbox. Requires the same session token as the journey."""
    if not x_session_token:
        raise HTTPException(status_code=401, detail="X-Session-Token header required")
    service = JourneyService(db)
    try:
        app = service._get_app_by_ref(application_id)
        service._get_session(app, x_session_token)
    except LookupError:
        raise HTTPException(status_code=404, detail="Application not found") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    return {
        "simulated": True,
        "notifications": NotificationService(db).list_for_application(app),
    }
