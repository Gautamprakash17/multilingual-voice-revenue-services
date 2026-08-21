"""Data Boundary Gateway — policy and egress invariants."""

from __future__ import annotations

from app.boundary.classification import Classification
from app.boundary.gateway import DataBoundaryGateway, GatewayRequest
from app.boundary.providers import OptionalCloudProvider
from app.models.audit import AuditEvent
from sqlalchemy.orm import Session


def test_restricted_to_cloud_is_denied(
    gateway: DataBoundaryGateway, cloud_provider: OptionalCloudProvider
):
    result = gateway.evaluate(
        GatewayRequest(
            payload={"citizen_name": "Lakshmi"},
            classification=Classification.RESTRICTED,
            destination="cloud",
            purpose="stt",
        )
    )
    assert result.allowed is False
    assert cloud_provider.call_count == 0
    assert result.provider_result is None
    assert (result.provider_result is None) or (
        result.provider_result.http_calls_made == 0
    )


def test_internal_to_cloud_is_denied(
    gateway: DataBoundaryGateway, cloud_provider: OptionalCloudProvider
):
    result = gateway.evaluate(
        GatewayRequest(
            payload={"session_id": "abc"},
            classification=Classification.INTERNAL,
            destination="cloud",
            purpose="analytics",
        )
    )
    assert result.allowed is False
    assert cloud_provider.call_count == 0


def test_public_safe_cloud_denied_without_approval(
    gateway: DataBoundaryGateway, cloud_provider: OptionalCloudProvider
):
    result = gateway.evaluate(
        GatewayRequest(
            payload={"phrase": "hello"},
            classification=Classification.PUBLIC_SAFE,
            destination="cloud",
            purpose="synthetic_help",
            approved=False,
        )
    )
    assert result.allowed is False
    assert result.decision.requires_approval is True
    assert cloud_provider.call_count == 0


def test_public_safe_cloud_allowed_with_explicit_approval(
    gateway: DataBoundaryGateway, cloud_provider: OptionalCloudProvider
):
    result = gateway.evaluate(
        GatewayRequest(
            payload={"phrase": "help phrase"},
            classification=Classification.PUBLIC_SAFE,
            destination="cloud",
            purpose="synthetic_help",
            approved=True,
        )
    )
    assert result.allowed is True
    assert cloud_provider.call_count == 1
    assert result.provider_result is not None
    assert result.provider_result.http_calls_made == 0


def test_public_safe_cloud_denied_for_unknown_purpose(
    gateway: DataBoundaryGateway, cloud_provider: OptionalCloudProvider
):
    result = gateway.evaluate(
        GatewayRequest(
            payload={"phrase": "x"},
            classification=Classification.PUBLIC_SAFE,
            destination="cloud",
            purpose="exfiltrate_citizen_data",
            approved=True,
        )
    )
    assert result.allowed is False
    assert cloud_provider.call_count == 0


def test_denied_cloud_request_makes_zero_external_http_calls(
    gateway: DataBoundaryGateway, cloud_provider: OptionalCloudProvider
):
    result = gateway.evaluate(
        GatewayRequest(
            payload={"aadhaar": "1234", "password": "secret"},
            classification="RESTRICTED",
            destination="cloud",
            purpose="anything",
        )
    )
    assert result.allowed is False
    assert cloud_provider.call_count == 0
    assert result.metadata.get("http_calls_made") == 0


def test_unknown_destination_fails_closed(
    gateway: DataBoundaryGateway, cloud_provider: OptionalCloudProvider
):
    result = gateway.evaluate(
        GatewayRequest(
            payload={"x": 1},
            classification=Classification.PUBLIC_SAFE,
            destination="mars",
            purpose="synthetic_help",
            approved=True,
        )
    )
    assert result.allowed is False
    assert "fail closed" in result.decision.reason.lower()
    assert cloud_provider.call_count == 0


def test_missing_classification_on_gateway_defaults_restricted(
    gateway: DataBoundaryGateway, cloud_provider: OptionalCloudProvider
):
    result = gateway.evaluate(
        GatewayRequest(
            payload={"name": "X"},
            classification=None,
            destination="cloud",
            purpose="synthetic_help",
            approved=True,
        )
    )
    assert result.classification == Classification.RESTRICTED
    assert result.allowed is False
    assert cloud_provider.call_count == 0


def test_local_destination_always_allowed(gateway: DataBoundaryGateway):
    result = gateway.evaluate(
        GatewayRequest(
            payload={"slot": "income"},
            classification=Classification.RESTRICTED,
            destination="local",
            purpose="form_capture",
        )
    )
    assert result.allowed is True
    assert result.provider_result is not None
    assert result.provider_result.provider == "local"


def test_audit_event_created_for_boundary_decision(
    gateway: DataBoundaryGateway, db_session: Session
):
    result = gateway.evaluate(
        GatewayRequest(
            payload={"citizen_name": "Ramesh", "income": 120000},
            classification=Classification.RESTRICTED,
            destination="cloud",
            purpose="stt",
            trace_id="trace-audit-1",
        ),
        db=db_session,
    )
    db_session.commit()
    assert result.audit_event_id is not None
    events = db_session.query(AuditEvent).all()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "boundary.decision"
    assert event.classification == "RESTRICTED"
    assert event.trace_id == "trace-audit-1"
    assert event.metadata_json["allowed"] is False


def test_audit_data_does_not_contain_restricted_payload(
    gateway: DataBoundaryGateway, db_session: Session
):
    result = gateway.evaluate(
        GatewayRequest(
            payload={
                "citizen_name": "Lakshmi Devi",
                "aadhaar": "9999-8888-7777",
                "address": "12 Temple Street",
            },
            classification=Classification.RESTRICTED,
            destination="cloud",
            purpose="stt",
        ),
        db=db_session,
    )
    db_session.commit()
    event = db_session.query(AuditEvent).one()
    meta_str = str(event.metadata_json)
    assert "Lakshmi Devi" not in meta_str
    assert "9999-8888-7777" not in meta_str
    assert "Temple Street" not in meta_str
    # Keys may be listed, never values
    assert "citizen_name" in event.metadata_json.get("payload_keys", [])
    assert result.allowed is False
