"""Audit, logging redaction, and health endpoint tests."""

from __future__ import annotations

import json
import logging

from app.core.security import redact_sensitive
from app.main import create_app
from app.models.audit import AuditEvent
from app.platform.audit import write_audit_event
from app.platform.logging import JsonFormatter
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_audit_insert_only_and_fields(db_session: Session):
    event = write_audit_event(
        db_session,
        event_type="test.event",
        classification="INTERNAL",
        trace_id="t-1",
        actor_id=None,
        metadata={"action": "ping", "password": "should-redact"},
    )
    db_session.commit()
    assert event.event_id
    assert event.timestamp is not None
    assert event.event_type == "test.event"
    assert event.classification == "INTERNAL"
    assert event.metadata_json["password"] == "[REDACTED]"
    assert event.metadata_json["action"] == "ping"
    # No update/delete helpers exist on the public API — verify row count
    assert db_session.query(AuditEvent).count() == 1


def test_secrets_are_not_logged_via_redaction():
    dirty = {
        "user": "officer1",
        "password": "hunter2",
        "token": "abc123",
        "api_key": "sk-secret",
        "otp": "123456",
        "nested": {"authorization": "Bearer xyz"},
    }
    clean = redact_sensitive(dirty)
    assert clean["password"] == "[REDACTED]"
    assert clean["token"] == "[REDACTED]"
    assert clean["api_key"] == "[REDACTED]"
    assert clean["otp"] == "[REDACTED]"
    assert clean["nested"]["authorization"] == "[REDACTED]"
    assert clean["user"] == "officer1"


def test_json_formatter_includes_correlation_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.event = "unit.test"  # type: ignore[attr-defined]
    record.trace_id = "trace-xyz"  # type: ignore[attr-defined]
    record.request_id = "req-xyz"  # type: ignore[attr-defined]
    record.extra_fields = {"otp": "999999", "path": "/api/v1/health"}  # type: ignore[attr-defined]
    line = formatter.format(record)
    data = json.loads(line)
    assert data["event"] == "unit.test"
    assert data["trace_id"] == "trace-xyz"
    assert data["request_id"] == "req-xyz"
    assert data["otp"] == "[REDACTED]"
    assert data["path"] == "/api/v1/health"
    assert "999999" not in line


def test_health_endpoint_works():
    client = TestClient(create_app())
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_ready_endpoint_reports_database_status():
    """Readiness reflects DB availability; may be 200 or 503 depending on env."""
    client = TestClient(create_app())
    response = client.get("/api/v1/ready")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "checks" in body
    assert "database" in body["checks"]
    if response.status_code == 200:
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "ok"
    else:
        assert body["status"] == "not_ready"
        assert body["checks"]["database"] == "unavailable"


def test_unhandled_errors_do_not_leak_stack_traces():
    from app.main import create_app
    from fastapi.testclient import TestClient as TC

    app = create_app()

    @app.get("/__test_boom")
    def test_boom() -> None:
        raise RuntimeError("secret stack detail")

    client = TC(app, raise_server_exceptions=False)
    response = client.get("/__test_boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["message"] == "Internal server error"
    assert "secret stack detail" not in response.text
    assert "RuntimeError" not in response.text
