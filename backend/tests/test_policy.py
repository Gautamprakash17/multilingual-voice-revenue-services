"""Policy engine fail-closed behaviour."""

from pathlib import Path

from app.boundary.classification import Classification
from app.boundary.policy import PolicyEngine


def test_missing_policy_file_fails_closed(tmp_path: Path):
    engine = PolicyEngine(tmp_path / "does-not-exist.yaml")
    decision = engine.evaluate(
        Classification.PUBLIC_SAFE, "cloud", "synthetic_help", approved=True
    )
    assert decision.allowed is False
    assert "fail closed" in decision.reason.lower()


def test_unknown_cloud_action_fails_closed(tmp_path: Path):
    policy = tmp_path / "bad.yaml"
    policy.write_text(
        "version: '1'\nclassifications:\n  PUBLIC_SAFE:\n    cloud:\n      action: MAYBE\n",
        encoding="utf-8",
    )
    engine = PolicyEngine(policy)
    decision = engine.evaluate(
        Classification.PUBLIC_SAFE, "cloud", "synthetic_help", approved=True
    )
    assert decision.allowed is False
