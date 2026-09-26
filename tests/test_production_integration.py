from simplicio_loop.execution_route import decide_route
from simplicio_loop.production_integration import (
    evaluate_production_integration,
    run_production_integration_harness,
)
from simplicio_loop.installed_runtime_e2e import COMPONENTS, run_installed_smoke
from simplicio_loop.runtime_effect_adapter import EffectRequest, RuntimeEffectAdapter
from simplicio_loop.runtime_execution_receipt import build_runtime_execution_receipt


def evidence():
    route = decide_route("mechanically update the indexed file", True, False).to_dict()
    return {
        "route": route,
        "effect": {
            "profile": "runtime-backed", "executor": "simplicio-runtime", "status": "MEASURED",
            "idempotency_key": "k", "lease_id": "l", "fencing_token": 1,
        },
        "context": {"status": "READY"}, "sessions": {"status": "READY"},
        "installed": {"status": "READY"},
    }


def test_full_production_evidence_allows_effects():
    report = evaluate_production_integration(evidence())
    assert report["status"] == "READY"
    assert report["effects_allowed"] is True
    assert len(report["integration_hash"]) == 64


def test_partial_or_standalone_evidence_blocks_without_false_success():
    partial = evidence()
    partial.pop("installed")
    partial["effect"]["profile"] = "standalone"
    report = evaluate_production_integration(partial)
    assert report["status"] == "BLOCKED"
    assert report["effects_allowed"] is False
    assert "missing:installed" in report["reasons"]
    assert "effect_not_runtime_authoritative" in report["reasons"]


def test_route_hash_drift_blocks_integration():
    drifted = evidence()
    drifted["route"]["reason"] = "tampered"
    report = evaluate_production_integration(drifted)
    assert report["status"] == "BLOCKED"
    assert "route_hash_invalid" in report["reasons"]


def harness_evidence():
    route = decide_route("mechanically update the indexed file", True, False).to_dict()
    probes = {name: (lambda context, name=name: {"status": "READY", "component": name}) for name in COMPONENTS}
    installed = run_installed_smoke("C:/repo", probes, mapper_envelope_hash="mapper", plan_hash="plan")
    # There is no Runtime-backed adapter in this stack any more; the harness's
    # own "production-authoritative effect" shape is exercised directly here
    # rather than through RuntimeEffectAdapter, which is standalone-only.
    effect = dict(RuntimeEffectAdapter().execute(
        EffectRequest("C:/repo", "k", ("repo:src",), "l", 1), ["simplicio", "status"],
    ))
    effect["profile"] = "runtime-backed"
    effect["executor"] = "simplicio-runtime"
    effect["status"] = "READY"
    execution = build_runtime_execution_receipt(
        route_id=route["receipt_sha"],
        requested={"runtime": "simplicio", "provider": "simplicio", "model_id": "UNAVAILABLE"},
        resolved={"runtime": "simplicio", "provider": "simplicio", "model_id": "runtime", "verified": True},
        driver={"name": "simplicio-runtime", "binary": "simplicio", "version": "1", "identity_verified": True},
        session={"worker_id": "w1", "device_id": "d1", "attempt_id": "a1", "lease_id": "l", "fence_token": "1"},
        argv_redacted=["simplicio", "serve"], env_allowlist=["PATH"],
        tree={"base_sha": "base", "head_sha": "head", "changed_paths": []},
        exit_status=0, duration_seconds=0.01, stop_reason="completed",
        evidence_refs=[installed["report_hash"]], usage={"tokens": 0, "cost_usd": 0, "latency_seconds": 0.01},
    )
    return {
        "route": route, "effect": effect,
        "context": {"status": "READY"}, "sessions": {"status": "READY"},
        "installed": installed, "execution": execution,
        "observed_effect": {"intent_id": "k", "succeeded": True},
    }


def test_production_harness_reconciles_every_component_before_allowing_effects():
    evidence = harness_evidence()
    report = run_production_integration_harness(evidence)
    again = run_production_integration_harness(evidence)
    assert report["schema"] == "simplicio.loop-runtime-production-harness/v1"
    assert report["status"] == "READY"
    assert report["effects_allowed"] is True
    assert all(check["verified"] for check in report["checks"].values())
    assert report["integration_hash"] == again["integration_hash"]


def test_production_harness_executes_and_reconciles_through_injected_boundaries():
    evidence = harness_evidence()
    execution = evidence.pop("execution")
    evidence.pop("observed_effect")
    report = run_production_integration_harness(
        evidence,
        execute=lambda context: execution,
        reconcile=lambda intent: {"intent_id": intent["intent_id"], "succeeded": True},
    )
    assert report["status"] == "READY"
    assert report["checks"]["reconciliation"]["outcome"] == "succeeded"


def test_production_harness_blocks_uncertain_or_tampered_execution():
    evidence = harness_evidence()
    evidence.pop("observed_effect")
    evidence["execution"]["argv_redacted"] = ["tampered"]
    report = run_production_integration_harness(evidence)
    assert report["status"] == "BLOCKED"
    assert report["effects_allowed"] is False
    assert "execution_receipt_tampered" in report["reasons"]
    assert "no observation available yet; retry remains blocked" == report["checks"]["reconciliation"]["detail"]
