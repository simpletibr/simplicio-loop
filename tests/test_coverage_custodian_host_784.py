from simplicio_loop import coverage_custodians as cc
from simplicio_loop.coverage_custodian_host import CustodianHost, proceed_decision
from simplicio_loop.hookwall_gate import HookwallBlocked
import pytest


def fixture():
    gap = {
        "kind": "cache_integrity", "subject": "cache:x",
        "acceptance_criteria": "clean rescan", "evidence_refs": ["mapper://x"],
    }
    gap["gap_id"] = cc.digest({
        "base_atlas_digest": "sha256:atlas", "kind": gap["kind"], "subject": gap["subject"],
    })
    delta = cc.validate_coverage_delta({
        "schema": cc.COVERAGE_DELTA_SCHEMA, "source": "mapper@installed",
        "base_atlas_digest": "sha256:atlas", "gaps": [gap],
    })
    address = {"schema": cc.CUSTODIAN_ADDRESS_SCHEMA, "capability": gap["kind"],
               "target": "fast://cache", "generation": 1}
    address["address_id"] = cc.digest(address)
    decision = cc.decide(delta, [address], {"dispatch_budget": 1})[0]
    envelope = cc.build_envelope(
        gap, decision, {"run_id": "r", "fence": "f1", "plan_revision": "1"},
        {"cpu_ms": 100, "max_attempts": 1},
    )
    return gap, envelope


def fast_receipt(gap, envelope):
    value = {
        "schema": cc.CUSTODIAN_RECEIPT_SCHEMA,
        "verdict_schema": cc.WORKER_VERDICT_SCHEMA,
        "gap_id": gap["gap_id"], "envelope_digest": envelope["envelope_digest"],
        "idempotency_key": envelope["idempotency_key"], "fence": envelope["fence"],
        "agent_instance_id": "fast-worker-1", "verdict": "FIXED",
        "evidence_refs": ["fast://receipt/1"],
    }
    value["receipt_digest"] = cc.digest(value)
    return value


def test_worker_only_materializes_after_hookwall_and_duplicate_is_replayed(tmp_path):
    gap, envelope = fixture()
    calls = []
    host = CustodianHost(tmp_path / "journal.json")
    pre = lambda value: proceed_decision(value, phase="pre")
    post = lambda value, receipt: proceed_decision(
        value, phase="post", receipt_hash=receipt["receipt_hash"],
    )
    worker = lambda value: calls.append(value) or fast_receipt(gap, value)
    first = host.dispatch(
        envelope, workspace=str(tmp_path), policy_hash="policy", pre_hook=pre,
        worker=worker, post_hook=post,
    )
    second = host.dispatch(
        envelope, workspace=str(tmp_path), policy_hash="policy", pre_hook=pre,
        worker=worker, post_hook=post,
    )
    assert first == second
    assert len(calls) == 1
    assert first["completion_authority"] == "LOOP_ONLY"
    assert host.metrics()["workers_materialized"] == 1
    assert host.metrics()["workers_avoided"] == 1


def test_missing_hookwall_never_materializes_worker_and_persists_nothing(tmp_path):
    _, envelope = fixture()
    calls = []
    host = CustodianHost(tmp_path / "journal.json")
    with pytest.raises(HookwallBlocked, match="hookwall_pre"):
        host.dispatch(
            envelope, workspace=str(tmp_path), policy_hash="policy",
            pre_hook=lambda value: {}, worker=lambda value: calls.append(value),
            post_hook=lambda value, receipt: {},
        )
    assert calls == []
    assert host.metrics()["workers_materialized"] == 0


def test_cancel_before_hookwall_and_invalid_fast_receipt_fail_closed(tmp_path):
    gap, envelope = fixture()
    host = CustodianHost(tmp_path / "journal.json")
    with pytest.raises(HookwallBlocked, match="cancelled"):
        host.dispatch(
            envelope, workspace=str(tmp_path), policy_hash="policy",
            pre_hook=lambda value: proceed_decision(value, phase="pre"),
            worker=lambda value: fast_receipt(gap, value),
            post_hook=lambda value, receipt: {}, cancelled=lambda: True,
        )
    with pytest.raises(HookwallBlocked, match="fast_receipt_invalid"):
        host.dispatch(
            envelope, workspace=str(tmp_path), policy_hash="policy",
            pre_hook=lambda value: proceed_decision(value, phase="pre"),
            worker=lambda value: {"receipt_digest": "bad"},
            post_hook=lambda value, receipt: {},
        )


def test_corrupt_journal_fails_closed(tmp_path):
    path = tmp_path / "journal.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(HookwallBlocked, match="journal_corrupt"):
        CustodianHost(path).metrics()
