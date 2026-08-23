"""Health and readiness endpoints."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import check_database
from app.services.catalogue import get_service_catalogue
from app.services.languages import get_language_catalog

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


@router.get("/languages")
def languages() -> dict:
    """Public language catalog for UI and client configuration."""
    catalog = get_language_catalog()
    return {
        "default": catalog.default_code,
        "languages": [lang.to_api_dict() for lang in catalog.languages],
    }


@router.get("/services")
def services() -> dict:
    """Public service catalog for citizen UI (read-only)."""
    catalogue = get_service_catalogue()
    items = []
    for defn in catalogue.values():
        fee = None
        if defn.fee:
            fee = {
                "amount_paise": defn.fee.amount_paise,
                "currency": defn.fee.currency,
                "description": defn.fee.description,
            }
        items.append(
            {
                "code": defn.service_code,
                "display_name": defn.display_name,
                "description": defn.description,
                "fee": fee,
                "fields": [
                    {
                        "name": field.name,
                        "type": field.type,
                        "required": field.required,
                        "prompt": field.prompt,
                    }
                    for field in defn.fields
                ],
                "documents": [
                    {
                        "code": doc.code,
                        "label": doc.label,
                        "required": doc.required,
                    }
                    for doc in defn.documents
                ],
            }
        )
    items.sort(key=lambda item: item["code"])
    return {"services": items}
