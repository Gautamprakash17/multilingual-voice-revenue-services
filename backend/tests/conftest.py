"""Shared pytest fixtures — SQLite in-memory for isolation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend package is importable
BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.boundary.gateway import DataBoundaryGateway  # noqa: E402
from app.boundary.policy import PolicyEngine  # noqa: E402
from app.boundary.providers import LocalProvider, OptionalCloudProvider  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture
def policy_path() -> Path:
    return REPO_ROOT / "config" / "boundary" / "policies.yaml"


@pytest.fixture
def policy_engine(policy_path: Path) -> PolicyEngine:
    return PolicyEngine(policy_path)


@pytest.fixture
def cloud_provider() -> OptionalCloudProvider:
    provider = OptionalCloudProvider()
    provider.reset_call_count()
    return provider


@pytest.fixture
def gateway(
    policy_engine: PolicyEngine, cloud_provider: OptionalCloudProvider
) -> DataBoundaryGateway:
    return DataBoundaryGateway(
        policy_engine=policy_engine,
        local_provider=LocalProvider(),
        cloud_provider=cloud_provider,
    )


@pytest.fixture
def db_session() -> Session:
    """In-memory SQLite session with schema created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
