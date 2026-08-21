"""Health and readiness endpoints."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import check_database

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness probe — process is up."""
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }


@router.get("/ready")
def ready() -> JSONResponse:
    """Readiness probe — database must be reachable."""
    db_ok = check_database()
    payload = {
        "status": "ready" if db_ok else "not_ready",
        "checks": {
            "database": "ok" if db_ok else "unavailable",
        },
    }
    code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=payload, status_code=code)
