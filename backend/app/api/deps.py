"""Shared FastAPI dependencies (P1 stubs)."""

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from sqlalchemy.orm import Session

from app.boundary.gateway import DataBoundaryGateway
from app.boundary.policy import PolicyEngine
from app.core.config import get_settings
from app.core.database import get_db

# Re-export for convenience
__all__ = ["get_db", "get_gateway", "get_trace_id"]


def get_trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _resolve_policy_path() -> Path:
    settings = get_settings()
    path = Path(settings.boundary_policy_path)
    if path.is_absolute() and path.exists():
        return path
    # Walk up from this file to find repo root containing config/
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / settings.boundary_policy_path
        if candidate.exists():
            return candidate
        # Also try relative to cwd
    cwd_candidate = Path.cwd() / settings.boundary_policy_path
    if cwd_candidate.exists():
        return cwd_candidate
    # Parent of backend/ when running from backend/
    backend_parent = Path.cwd().parent / settings.boundary_policy_path
    if backend_parent.exists():
        return backend_parent
    return path


@lru_cache
def get_policy_engine() -> PolicyEngine:
    return PolicyEngine(_resolve_policy_path())


@lru_cache
def get_gateway() -> DataBoundaryGateway:
    return DataBoundaryGateway(policy_engine=get_policy_engine())


def db_session() -> Generator[Session, None, None]:
    yield from get_db()
