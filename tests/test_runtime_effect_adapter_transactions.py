from dataclasses import replace

import pytest

from simplicio_loop.runtime_effect_adapter import EffectRequest, RuntimeEffectAdapter


def request(**overrides):
    values = {
        "workspace": "C:/repo",
        "idempotency_key": "run-1:task-1:attempt-1",
        "write_set": ("repo:src",),
        "lease_id": "lease-1",
        "fencing_token": 7,
        "attempt": 2,
        "gate_id": "gate-1",
        "runtime_generation": "generation-3",
        "transaction_id": "tx-1",
    }
    values.update(overrides)
    return EffectRequest(**values)


def test_standalone_effect_binds_transaction_identity_and_action_digest():
    receipt = RuntimeEffectAdapter().execute(request(), ["pytest", "-q"], env={"SIMPLICIO_MODEL": "local"})
    assert receipt["status"] == "UNAVAILABLE"
    assert receipt["transaction"]["schema"] == "simplicio.effect-transaction/v1"
    assert receipt["transaction"]["lease"] == {"id": "lease-1", "fence": 7}
    assert receipt["transaction"]["attempt"] == 2
    assert receipt["transaction"]["idempotency"]["transaction_id"] == "tx-1"
    assert receipt["transaction"]["idempotency"]["action_digest"].startswith("sha256:")
    assert receipt["correlation_id"] == "tx-1"


def test_explicit_effect_methods_are_standalone():
    receipt = RuntimeEffectAdapter().edit(request(), {"path": "src/main.py"})
    assert receipt["status"] == "UNAVAILABLE"
    assert receipt["delivery"] == "STANDALONE"


def test_standalone_effects_are_explicitly_unavailable_and_deterministic():
    receipt = RuntimeEffectAdapter(profile="standalone").evidence(request(), {"status": "PASS"})
    assert receipt["status"] == "UNAVAILABLE"
    assert receipt["delivery"] == "STANDALONE"
    assert receipt["transaction"]["executor"] == "STANDALONE"
    assert receipt["correlation_id"] == "tx-1"


def test_metrics_report_null_reasons_with_no_samples():
    receipt = RuntimeEffectAdapter().execute(request(), ["python", "-V"])
    assert receipt["metrics"]["latency"]["p50_ms"] is None
    assert receipt["metrics"]["latency"]["reason"] == "no_samples"
    assert receipt["metrics"]["tokens"] is None
    assert receipt["metrics"]["tokens_reason"] == "runtime_not_reported"


def test_all_production_methods_are_standalone_and_allowlisted():
    adapter = RuntimeEffectAdapter()
    expected = {
        "map": "simplicio_map",
        "read": "simplicio_read",
        "edit": "simplicio_edit",
        "validate": "simplicio_validate",
        "checkpoint": "simplicio_checkpoint",
        "evidence": "simplicio_evidence",
    }
    for method, _tool in expected.items():
        receipt = getattr(adapter, method)(request(), {"probe": method})
        assert receipt["status"] == "UNAVAILABLE"
        assert receipt["result"]["reason"] == "standalone_profile"


def test_invalid_effect_surfaces_fail_before_dispatch():
    adapter = RuntimeEffectAdapter()
    with pytest.raises(Exception, match="argv"):
        adapter.execute(request(), [])
    with pytest.raises(Exception, match="allowlisted"):
        adapter.call(request(), "subprocess", {})
    with pytest.raises(Exception, match="allowlisted"):
        adapter.call(request(), "simplicio_bad/tool", {})
    with pytest.raises(Exception, match="object"):
        adapter.call(request(), "simplicio_status", [])  # type: ignore[arg-type]
    with pytest.raises(Exception, match="profile"):
        RuntimeEffectAdapter(profile="automatic")  # type: ignore[arg-type]


def test_authorization_digest_is_bound_to_transaction_and_receipt():
    digest = "sha256:" + "a" * 64
    req = replace(request(), authorization_digest=digest)
    receipt = RuntimeEffectAdapter().execute(req, ["python", "-V"])
    assert receipt["authorization_digest"] == digest
    assert receipt["transaction"]["authorization_digest"] == digest


def test_authorization_digest_rejects_non_sha256_values():
    with pytest.raises(Exception, match="authorization_digest"):
        replace(request(), authorization_digest="not-a-digest")
