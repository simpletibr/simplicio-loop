from __future__ import annotations

from pathlib import Path

from simplicio.dev_cli_contracts import apply, compile_plan, dry_run, reconcile
from simplicio.standalone_migration import record_effect_unknown


def plan():
    return {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": ["a.txt"],
        "operations": [
            {"op": "replace_range", "path": "a.txt", "start_line": 1, "end_line": 1, "text": "new\n"}
        ],
    }


def test_plan_dry_run_apply_receipt_reconcile_contract(tmp_path: Path):
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    envelope = compile_plan(plan(), root=tmp_path, idempotency_key="issue-648-key")
    assert envelope["schema"] == "simplicio.dev-cli.plan/v1"
    assert envelope["status"] == "planned"
    preview = dry_run(envelope, root=tmp_path)
    assert preview["schema"] == "simplicio.dev-cli.dry-run/v1"
    assert preview["applied"] is False
    assert preview["plan_digest"] == preview["effect_digest"]
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "old\n"
    receipt = apply(envelope, root=tmp_path)
    assert receipt["schema"] == "simplicio.dev-cli.receipt/v1"
    assert receipt["status"] == "committed"
    assert receipt["plan_digest"] == envelope["plan_digest"]
    assert receipt["effect_digest"] == envelope["effect_digest"]
    assert receipt["provenance"] == envelope["provenance"]
    replay = apply(envelope, root=tmp_path)
    assert replay["replayed"] is True
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "new\n"
    reconciled = reconcile(root=tmp_path, idempotency_key="issue-648-key")
    assert reconciled["status"] == "reconciled"
    assert reconciled["outcome"] == "committed"


def test_blocked_plan_and_precondition_failure_are_actionable(tmp_path: Path):
    blocked = compile_plan({"schema": "wrong", "operations": []}, root=tmp_path, idempotency_key="blocked")
    assert blocked["status"] == "blocked"
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    envelope = compile_plan(plan(), root=tmp_path, idempotency_key="stale")
    (tmp_path / "a.txt").write_text("changed\n", encoding="utf-8")
    result = apply(envelope, root=tmp_path)
    assert result["status"] == "blocked"
    assert result["reason"] == "preconditions_failed"
    assert result["preconditions"]["expected"] != result["preconditions"]["actual"]


def test_reconcile_unknown_and_not_found_states(tmp_path: Path):
    record_effect_unknown(str(tmp_path), {"idempotency_key": "unknown-key", "evidence_file": "evidence.json"})
    unknown = reconcile(root=tmp_path, idempotency_key="unknown-key")
    assert unknown == {
        "schema": "simplicio.dev-cli.reconcile/v1",
        "status": "unknown",
        "outcome": "effect_unknown",
        "recovery_locator": "evidence.json",
    }
    not_found = reconcile(root=tmp_path, idempotency_key="missing")
    assert not_found["status"] == "not-found"
    assert not_found["outcome"] == "not-found"
