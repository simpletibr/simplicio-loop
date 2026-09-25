import json

import pytest

from simplicio_fast import decision_cache


def make_key(**overrides: str | None) -> decision_cache.DecisionCacheKey:
    values: dict[str, str | None] = {
        "model_digest": "sha256:model",
        "artifact_digest": "sha256:artifact",
        "quant_digest": "sha256:q4",
        "tokenizer_template_identity": "chat-template-v1",
        "backend_version": "llama-cpp-v1",
        "hardware_topology_fingerprint": "cpu-8c-avx2",
        "device_placement_class": "same-device",
        "context_kv_pressure_bucket": "medium",
        "workload_class": "interactive",
        "concurrency_bucket": "c2",
        "fast_policy_version": "policy-v3",
        "generation": "generation-7",
    }
    values.update(overrides)
    return decision_cache.DecisionCacheKey(**values)


def test_key_contains_minimum_dimensions_and_is_deterministic() -> None:
    first = make_key()
    second = make_key()

    assert first.digest == second.digest
    assert first.to_dict()["schema"] == decision_cache.KEY_SCHEMA
    assert set(first.to_dict()) == {
        "schema",
        "model_digest",
        "artifact_digest",
        "quant_digest",
        "tokenizer_template_identity",
        "backend_version",
        "hardware_topology_fingerprint",
        "device_placement_class",
        "context_kv_pressure_bucket",
        "workload_class",
        "concurrency_bucket",
        "fast_policy_version",
        "generation",
    }


def test_hit_miss_receipts_are_versioned_and_content_safe() -> None:
    cache = decision_cache.DecisionCache(generation="generation-7")
    key = make_key()

    miss = cache.lookup(key)
    assert miss == {
        "schema": decision_cache.RECEIPT_SCHEMA,
        "operation": "lookup",
        "outcome": "miss",
        "reason": "entry_missing",
        "key_digest": key.digest,
        "generation": "generation-7",
    }
    cache.put(key, {"strategy": "baseline", "draft_tokens": 0})
    hit = cache.lookup(key)
    assert hit["schema"] == decision_cache.RECEIPT_SCHEMA
    assert hit["outcome"] == "hit"
    assert hit["reason"] == "cache_hit"
    assert hit["decision"] == {"strategy": "baseline", "draft_tokens": 0}
    assert "generation-7" in json.dumps(hit, sort_keys=True)


def test_generation_change_invalidates_old_entries_explicitly() -> None:
    cache = decision_cache.DecisionCache()
    old_key = make_key()
    new_key = make_key(generation="generation-8")
    cache.put(old_key, {"strategy": "baseline"})

    activated = cache.activate_generation("generation-8")
    assert activated["outcome"] == "activated"
    assert activated["reason"] == decision_cache.InvalidationReason.GENERATION_ADVANCED
    assert activated["invalidated_key_digests"] == [old_key.digest]
    stale = cache.lookup(old_key)
    assert stale["outcome"] == "miss"
    assert stale["reason"] == decision_cache.InvalidationReason.GENERATION_MISMATCH
    assert (
        cache.lookup(new_key)["reason"]
        == decision_cache.InvalidationReason.ENTRY_MISSING
    )


def test_bounded_lru_eviction_is_deterministic() -> None:
    cache = decision_cache.DecisionCache(max_entries=2, generation="generation-7")
    first = make_key(workload_class="first")
    second = make_key(workload_class="second")
    third = make_key(workload_class="third")
    cache.put(first, {"strategy": "baseline"})
    cache.put(second, {"strategy": "baseline"})
    cache.lookup(first)
    receipt = cache.put(third, {"strategy": "baseline"})

    assert receipt["evicted_key_digests"] == [second.digest]
    assert (
        cache.lookup(second)["reason"]
        == decision_cache.InvalidationReason.CAPACITY_EVICTION
    )
    assert cache.lookup(first)["outcome"] == "hit"
    assert len(cache) == 2


def test_drift_invalidation_reports_dimension_reason() -> None:
    cache = decision_cache.DecisionCache(generation="generation-7")
    old_key = make_key(backend_version="backend-v1")
    current_key = make_key(backend_version="backend-v2")
    cache.put(old_key, {"strategy": "baseline"})

    receipt = cache.invalidate_drift(
        current_key,
        dimensions=("backend_version",),
    )
    assert receipt["outcome"] == "invalidated"
    assert receipt["reason"] == decision_cache.InvalidationReason.BACKEND_DRIFT
    assert receipt["invalidated_key_digests"] == [old_key.digest]
    assert (
        cache.lookup(old_key)["reason"]
        == decision_cache.InvalidationReason.BACKEND_DRIFT
    )


def test_telemetry_contradiction_quarantines_without_exposing_values() -> None:
    cache = decision_cache.DecisionCache(generation="generation-7")
    key = make_key()
    cache.put(
        key,
        {"strategy": "speculative", "draft_tokens": 4},
        expected={"throughput_class": "improving"},
    )

    receipt = cache.lookup(key, observed={"throughput_class": "regressing"})
    assert receipt["outcome"] == "quarantined"
    assert (
        receipt["reason"]
        == decision_cache.InvalidationReason.OBSERVED_TELEMETRY_CONTRADICTION
    )
    assert receipt["contradiction_fields"] == ["throughput_class"]
    assert "improving" not in json.dumps(receipt)
    assert cache.lookup(key)["outcome"] == "quarantined"


def test_regression_disable_blocks_reuse_until_generation_changes() -> None:
    cache = decision_cache.DecisionCache(generation="generation-7")
    key = make_key()
    cache.put(key, {"strategy": "speculative"})

    disabled = cache.disable_for_regression(key)
    assert disabled["outcome"] == "disabled"
    assert disabled["reason"] == decision_cache.InvalidationReason.REGRESSION_DETECTED
    assert cache.lookup(key)["outcome"] == "disabled"
    cache.activate_generation("generation-8")
    assert cache.lookup(make_key(generation="generation-8"))["outcome"] == "miss"


def test_raw_content_and_invalid_reasons_are_rejected() -> None:
    with pytest.raises(
        decision_cache.DecisionCacheError, match="raw_content_forbidden"
    ):
        make_key(workload_class="raw user prompt")
    with pytest.raises(
        decision_cache.DecisionCacheError, match="raw_content_forbidden"
    ):
        decision_cache.DecisionCache(generation="generation-7").put(
            make_key(), {"prompt": "do not cache this"}
        )
    with pytest.raises(
        decision_cache.DecisionCacheError, match="invalidation_reason_invalid"
    ):
        decision_cache.DecisionCache().invalidate(make_key(), reason="backend drift")


def test_snapshot_and_state_receipts_are_versioned_and_bounded() -> None:
    cache = decision_cache.DecisionCache(max_entries=1, generation="generation-7")
    cache.put(make_key(), {"strategy": "baseline"})

    snapshot = cache.snapshot()
    state = cache.receipt()
    assert snapshot["schema"] == decision_cache.CACHE_SCHEMA
    assert snapshot["capacity"] == 1
    assert len(snapshot["entries"]) == 1
    assert state["schema"] == decision_cache.RECEIPT_SCHEMA
    assert state["size"] == 1
    assert state["capacity"] == 1
