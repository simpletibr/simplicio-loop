import json
from pathlib import Path
import shutil
import subprocess

import pytest

from simplicio_fast.capability_ranking import (
    CapabilityCandidate,
    CapabilityRankingError,
    candidates_from_manifest,
    rank_capabilities,
)


def test_capability_ranking_is_explainable_and_advisory() -> None:
    result = rank_capabilities(
        [
            CapabilityCandidate("worker:b", "worker", "1", ("query",), estimated_cost=1, provenance=("manifest:b",), policy_eligible=True),
            CapabilityCandidate("worker:a", "worker", "1", ("query", "rust"), estimated_cost=4, provenance=("manifest:a",), policy_eligible=True),
        ],
        ("query", "rust"),
    )
    assert result["authority"] == "advisory_only"
    assert result["candidates"][0]["handle"] == "worker:a"
    assert result["candidates"][0]["missing_capabilities"] == []
    assert result["candidates"][0]["eligible"] is True
    assert result["candidates"][0]["score_components"]["matched_capabilities"] == 200
    assert result["candidates"][1]["selection_reason"] == "missing_required_capabilities"


def test_capability_ranking_is_bounded_and_rejects_invalid_requests() -> None:
    result = rank_capabilities([CapabilityCandidate("a", "tool", "1", ("x",), policy_eligible=True)], ("x",), max_results=1)
    assert result["truncated"] is False
    with pytest.raises(CapabilityRankingError, match="ranking_request_invalid"):
        rank_capabilities([], (), max_results=1)


def test_capability_ranking_separates_hard_filters_and_unknown_metrics() -> None:
    result = rank_capabilities(
        [
            CapabilityCandidate("unknown", "worker", "1", ("query",), policy_eligible=None),
            CapabilityCandidate("other-tenant", "worker", "1", ("query",), policy_eligible=True, scope="tenant-b"),
        ],
        ("query",),
        required_scope="tenant-a",
    )
    assert all(item["eligible"] is False for item in result["candidates"])
    by_handle = {item["handle"]: item for item in result["candidates"]}
    assert by_handle["unknown"]["selection_reason"] == "policy_unknown"
    assert by_handle["unknown"]["metric_class"] == "unknown"
    assert by_handle["other-tenant"]["selection_reason"] == "scope_mismatch"


def test_capability_ranking_applies_owner_trust_floor_as_hard_filter() -> None:
    result = rank_capabilities(
        [
            CapabilityCandidate(
                "derived", "worker", "1", ("query",), trust="derived_fact", policy_eligible=True
            ),
            CapabilityCandidate(
                "verified", "worker", "1", ("query",), trust="verified", policy_eligible=True
            ),
        ],
        ("query",),
        required_trust="verified",
    )
    by_handle = {item["handle"]: item for item in result["candidates"]}
    assert by_handle["derived"]["eligible"] is False
    assert by_handle["derived"]["hard_filter"]["trust"] is False
    assert by_handle["derived"]["selection_reason"] == "trust_below_floor"
    assert by_handle["verified"]["eligible"] is True
    assert result["required_trust"] == "verified"
    with pytest.raises(CapabilityRankingError, match="ranking_trust_invalid"):
        rank_capabilities([], ("query",), required_trust="unknown")


def test_capability_ranking_applies_owner_freshness_bound() -> None:
    result = rank_capabilities(
        [
            CapabilityCandidate(
                "fresh",
                "worker",
                "1",
                ("query",),
                policy_eligible=True,
                freshness_seconds=10,
                health="healthy",
            ),
            CapabilityCandidate(
                "stale",
                "worker",
                "1",
                ("query",),
                policy_eligible=True,
                freshness_seconds=90,
                health="degraded",
            ),
            CapabilityCandidate(
                "unknown",
                "worker",
                "1",
                ("query",),
                policy_eligible=True,
            ),
        ],
        ("query",),
        max_freshness_seconds=60,
    )
    by_handle = {item["handle"]: item for item in result["candidates"]}
    assert by_handle["fresh"]["eligible"] is True
    assert by_handle["fresh"]["hard_filter"]["freshness"] is True
    assert by_handle["fresh"]["health"] == "healthy"
    assert by_handle["stale"]["eligible"] is False
    assert by_handle["stale"]["selection_reason"] == "freshness_stale"
    assert by_handle["unknown"]["eligible"] is False
    assert by_handle["unknown"]["selection_reason"] == "freshness_unknown"
    assert result["max_freshness_seconds"] == 60


def test_capability_ranking_rejects_invalid_freshness_contracts() -> None:
    with pytest.raises(CapabilityRankingError, match="candidate_freshness_invalid"):
        CapabilityCandidate("bad", "worker", "1", ("query",), freshness_seconds=-1)
    with pytest.raises(CapabilityRankingError, match="candidate_health_invalid"):
        CapabilityCandidate("bad", "worker", "1", ("query",), health="unknownish")
    with pytest.raises(CapabilityRankingError, match="ranking_freshness_invalid"):
        rank_capabilities([], ("query",), max_freshness_seconds=True)


def test_capability_ranking_accepts_explicit_global_scope_and_rejects_bad_inputs() -> None:
    global_candidate = CapabilityCandidate(
        "global", "tool", "1", ("query",), policy_eligible=True, scope="*"
    )
    result = rank_capabilities([global_candidate], ("query",), required_scope="tenant-a")
    assert result["candidates"][0]["eligible"] is True
    with pytest.raises(CapabilityRankingError, match="ranking_request_invalid"):
        rank_capabilities([], (1,))
    with pytest.raises(CapabilityRankingError, match="candidate_scope_invalid"):
        CapabilityCandidate("bad", "tool", "1", ("query",), scope="")


def test_capability_ranking_rejects_coercible_invalid_types() -> None:
    with pytest.raises(CapabilityRankingError, match="candidate_cost_invalid"):
        CapabilityCandidate("float", "tool", "1", ("query",), estimated_cost=1.5)
    with pytest.raises(CapabilityRankingError, match="candidate_policy_invalid"):
        CapabilityCandidate("policy", "tool", "1", ("query",), policy_eligible="yes")
    with pytest.raises(CapabilityRankingError, match="candidate_provenance_invalid"):
        CapabilityCandidate("provenance", "tool", "1", ("query",), provenance=(1,))
    with pytest.raises(CapabilityRankingError, match="candidate_capabilities_invalid"):
        CapabilityCandidate("capabilities", "tool", "1", "query")
    with pytest.raises(CapabilityRankingError, match="candidate_provenance_invalid"):
        CapabilityCandidate(
            "provenance-string", "tool", "1", ("query",), provenance="receipt"
        )
    with pytest.raises(CapabilityRankingError, match="candidate_type_invalid"):
        rank_capabilities([object()], ("query",))
    with pytest.raises(CapabilityRankingError, match="ranking_request_invalid"):
        rank_capabilities([], ("query",), max_results=True)
    with pytest.raises(CapabilityRankingError, match="ranking_request_invalid"):
        rank_capabilities([], ("query",), required_scope=True)


def test_capability_candidate_normalizes_mutable_sequences() -> None:
    candidate = CapabilityCandidate(
        "worker:normalized",
        "worker",
        "1",
        ["query"],
        provenance=["manifest:1"],
    )
    assert candidate.capabilities == ("query",)
    assert candidate.provenance == ("manifest:1",)


def test_capability_ranking_rejects_invalid_candidate_contract_edges() -> None:
    with pytest.raises(CapabilityRankingError, match="candidate_identity_invalid"):
        CapabilityCandidate("", "tool", "1", ("query",))
    with pytest.raises(CapabilityRankingError, match="candidate_capabilities_invalid"):
        CapabilityCandidate("tool", "tool", "1", ("",))
    with pytest.raises(CapabilityRankingError, match="candidate_availability_invalid"):
        CapabilityCandidate("tool", "tool", "1", ("query",), available=1)
    with pytest.raises(CapabilityRankingError, match="candidate_cost_invalid"):
        CapabilityCandidate("tool", "tool", "1", ("query",), estimated_latency_ms=-1)
    with pytest.raises(CapabilityRankingError, match="candidate_metric_class_invalid"):
        CapabilityCandidate("tool", "tool", "1", ("query",), metric_class="measured-ish")


def test_capability_ranking_explains_unavailable_candidates() -> None:
    result = rank_capabilities(
        [CapabilityCandidate("offline", "worker", "1", ("query",), available=False)],
        ("query",),
    )
    assert result["candidates"][0]["selection_reason"] == "unavailable"


def test_capability_ranking_exposes_pareto_frontier_without_auto_selecting() -> None:
    result = rank_capabilities(
        [
            CapabilityCandidate("cheap", "worker", "1", ("query",), estimated_cost=1, estimated_latency_ms=10, policy_eligible=True, metric_class="measured"),
            CapabilityCandidate("fast", "worker", "1", ("query",), estimated_cost=5, estimated_latency_ms=1, policy_eligible=True, metric_class="measured"),
            CapabilityCandidate("dominated", "worker", "1", ("query",), estimated_cost=5, estimated_latency_ms=10, policy_eligible=True, metric_class="measured"),
        ],
        ("query",),
    )
    assert [item["handle"] for item in result["pareto_frontier"]] == ["cheap", "fast"]
    assert result["candidates"][0]["handle"] in {"cheap", "fast"}
    assert len(result["pareto_frontier"]) == 2


def test_capability_ranking_keeps_missing_metrics_unknown() -> None:
    result = rank_capabilities(
        [CapabilityCandidate("unknown", "worker", "1", ("query",), policy_eligible=True)],
        ("query",),
    )
    assert result["candidates"][0]["score_components"]["cost"] is None
    assert result["candidates"][0]["score_components"]["latency"] is None


def test_capability_ranking_bounds_candidate_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("simplicio_fast.capability_ranking.MAX_CANDIDATES", 1)
    candidates = [
        CapabilityCandidate("a", "worker", "1", ("query",), policy_eligible=True),
        CapabilityCandidate("b", "worker", "1", ("query",), policy_eligible=True),
    ]
    with pytest.raises(CapabilityRankingError, match="candidate_count_limit"):
        rank_capabilities(candidates, ("query",))


def _installed_json(command: list[str]) -> dict[str, object]:
    assert shutil.which(command[0]) is not None
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


def test_capability_ranking_adapts_real_loop_fast_and_runtime_manifests() -> None:
    if shutil.which("simplicio-runtime") is None:
        pytest.skip(
            "simplicio-runtime is required for real loop/fast/runtime manifest"
            " adaptation and is optional in the current release"
            " (standalone default, REQUIRE_RUNTIME=off)"
        )
    preflight = _installed_json(
        ["simplicio-loop", "preflight", "--repo", str(Path.cwd()), "--json"]
    )
    fast = _installed_json(["simplicio-py", "fast", "capabilities", "--json"])
    runtime = _installed_json(
        [
            "simplicio-runtime",
            "contracts",
            "smoke",
            "--json",
            "--repo",
            str(Path.cwd()),
        ]
    )
    candidates = [
        *candidates_from_manifest(preflight),
        *candidates_from_manifest(fast),
        *candidates_from_manifest(runtime),
    ]
    handles = {candidate.handle for candidate in candidates}
    assert "operator:simplicio-mapper" in handles
    assert "operator:simplicio-runtime" in handles
    assert "operator:simplicio-fast" in handles
    assert "runtime:simplicio-runtime" in handles
    ranked = rank_capabilities(candidates, ("runtime:runtime:simplicio-runtime",))
    assert ranked["authority"] == "advisory_only"
    assert all(item["policy_eligibility"] == "unknown" for item in ranked["candidates"])
    assert all(item["eligible"] is False for item in ranked["candidates"])


def test_capability_manifest_adapter_rejects_unknown_schema_and_malformed_operator() -> None:
    with pytest.raises(CapabilityRankingError, match="manifest_schema_invalid"):
        candidates_from_manifest({"schema": "unknown/v1"})
    with pytest.raises(CapabilityRankingError, match="manifest_operator_invalid"):
        candidates_from_manifest(
            {"schema": "simplicio.preflight/v1", "operators": [{"name": "loop"}]}
        )


def test_capability_manifest_adapter_rejects_unknown_fast_status() -> None:
    with pytest.raises(CapabilityRankingError, match="manifest_capability_invalid"):
        candidates_from_manifest(
            {
                "schema": "simplicio.fast-capabilities/v1",
                "availability": {"fast_version": "2.0.20", "status": "maybe"},
                "commands": ["fast capabilities"],
                "languages": ["python"],
            }
        )
