import json
from pathlib import Path

import pytest

from benchmarks.bench_capability_governed_346 import (
    HEALTH_SCHEMA,
    POLICY_SCHEMA,
    GovernedReceiptError,
    build_receipt,
)


def _inputs() -> tuple[dict[str, object], dict[str, object]]:
    fixture = json.loads(
        Path("fixtures/delivery/v1/issue346-governed-receipts.json").read_text(
            encoding="utf-8"
        )
    )
    return fixture["policy"], fixture["health"]


def _manifests() -> list[dict[str, object]]:
    return [
        {
            "schema": "simplicio.standard-io-smoke/v1",
            "runtime": "simplicio-runtime",
            "version": "3.5.7",
            "status": "passed",
            "checks": [{"name": "simplicio-runtime", "passed": True}],
        },
        {
            "schema": "simplicio.fast-capabilities/v1",
            "availability": {"fast_version": "2.0.20", "status": "degraded"},
            "commands": ["fast capabilities"],
            "languages": ["python"],
        },
    ]


def test_governed_receipt_applies_owner_policy_and_health_without_dispatch() -> None:
    policy, health = _inputs()
    receipt = build_receipt(
        _manifests(),
        policy_receipt=policy,
        health_receipt=health,
        required=("runtime:simplicio-runtime",),
    )
    ranked = receipt["ranking"]["candidates"]
    runtime = next(item for item in ranked if item["handle"] == "runtime:simplicio-runtime")
    assert runtime["eligible"] is True
    assert runtime["policy_eligibility"] == "eligible"
    assert runtime["health"] == "healthy"
    assert receipt["authority"] == "advisory_only"
    assert receipt["dispatch"]["performed"] is False
    assert receipt["governed_inputs"]["feedback"] == "only_verified_receipts"
    assert receipt["redaction"]["status"] == "excluded"


def test_governed_receipt_is_deterministic_and_catalog_is_content_addressed() -> None:
    policy, health = _inputs()
    first = build_receipt(_manifests(), policy_receipt=policy, health_receipt=health, required=("runtime:simplicio-runtime",))
    second = build_receipt(_manifests(), policy_receipt=policy, health_receipt=health, required=("runtime:simplicio-runtime",))
    assert first == second
    assert len(first["catalog"]["generation"]) == 64


def test_unverified_policy_is_rejected_closed() -> None:
    policy, health = _inputs()
    policy["status"] = "unverified"
    with pytest.raises(GovernedReceiptError, match="receipt_not_verified"):
        build_receipt(_manifests(), policy_receipt=policy, health_receipt=health, required=("runtime:simplicio-runtime",))


def test_cross_scope_owner_facts_do_not_leak_into_candidate() -> None:
    policy, health = _inputs()
    policy["decisions"] = [{"handle": "runtime:simplicio-runtime", "scope": "tenant-b", "eligible": True}]
    health["observations"] = [{"handle": "runtime:simplicio-runtime", "scope": "tenant-b", "health": "healthy", "freshness_seconds": 0}]
    receipt = build_receipt(
        _manifests(),
        policy_receipt=policy,
        health_receipt=health,
        required=("runtime:simplicio-runtime",),
        required_scope="tenant-a",
    )
    runtime = next(item for item in receipt["ranking"]["candidates"] if item["handle"] == "runtime:simplicio-runtime")
    assert runtime["eligible"] is False
    assert runtime["selection_reason"] == "policy_unknown"


def test_receipt_schemas_are_versioned() -> None:
    policy, health = _inputs()
    assert policy["schema"] == POLICY_SCHEMA
    assert health["schema"] == HEALTH_SCHEMA
