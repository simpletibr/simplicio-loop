"""Integration test (#284): the mandatory-by-default mutation-authority gate wired
into `execute_operator()`/`execute_operator_batch()`.

`execute_operator()` already refuses to run without fresh mapper/plan/operator
preflight receipts, a passing `validate_plan()`, an unchanged repo state, and an
authorized target (pre-existing behavior). This test covers the #284 gate on top of
that: a valid `planning-receipt.json` whose mutation authority matches the current
run/attempt/contract/plan identity is now required BY DEFAULT (no flag needed) --
`SIMPLICIO_REQUIRE_MUTATION_AUTHORITY` only lets a caller explicitly opt back OUT
(`=0`/`false`/`no`/`off`/`legacy`) for a legacy path that cannot satisfy the gate yet.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from simplicio_loop import runner as runner_mod
from tests._contract_only_hookwall import ContractOnlyHookwallLedger


@pytest.fixture(autouse=True)
def _contract_only_hookwall(monkeypatch):
    monkeypatch.setattr(
        runner_mod,
        "_hookwall_ledger",
        lambda *_args, **_kwargs: ContractOnlyHookwallLedger(),
    )
from simplicio_loop.plan_contract import validate_plan
from simplicio_loop.planning_gate import build_planning_receipt, content_hash, receipt_path

from tests.test_runner_cli_integration import _arm_deterministic_preflight_fixture
from tests.planning_gate_fixtures import stage_valid_planning_receipt

ENV_FLAG = "SIMPLICIO_REQUIRE_MUTATION_AUTHORITY"


def _exec_env(extra=None):
    env = {
        "SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON": json.dumps({
            "returncode": 0, "stdout": {"kind": "operator-applied", "ok": True}, "stderr": "",
            "write_files": {"src/app.py": "def main():\n    return 'updated'\n"},
        }),
    }
    if extra:
        env.update(extra)
    return env


def test_default_unset_blocks_without_receipt_fail_closed(tmp_path, monkeypatch):
    # Mandatory-by-default: with the flag unset entirely (no opt-out), no receipt on
    # disk must block execution exactly like the explicit `=1` case used to.
    # Auto-build is ALSO mandatory-by-default (#284 follow-up) -- disable it explicitly
    # so `arm_run()` does not self-satisfy the very gate this test exercises.
    monkeypatch.setenv("SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT", "0")
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = armed_payload["manifest"]["run_id"]
    assert not receipt_path(run_dir).exists()
    with patch.dict(os.environ, _exec_env(), clear=False):
        os.environ.pop(ENV_FLAG, None)
        with pytest.raises(RuntimeError, match="mutation authority required"):
            runner_mod.execute_operator(str(repo), run_id)
    assert json.loads((run_dir / "operator-receipt.json").read_text(encoding="utf-8"))["execution_state"] != "applied"


def test_explicit_opt_out_restores_zero_behavior_change(tmp_path, monkeypatch):
    # Legacy escape hatch: an explicit falsy value disables the gate entirely, same as
    # the old (pre-#284) unconditional behavior.
    monkeypatch.setenv("SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT", "0")
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = armed_payload["manifest"]["run_id"]
    assert not receipt_path(run_dir).exists()
    with patch.dict(os.environ, _exec_env({ENV_FLAG: "0"}), clear=False):
        payload = runner_mod.execute_operator(str(repo), run_id)
    assert payload["state"]["phase"] == "validating"


def test_execute_operator_blocks_on_plan_path_outside_authorized_targets(tmp_path, monkeypatch):
    """A host edit-plan naming a path outside the plan's authorized targets
    used to surface as the opaque PLAN_REQUIRED/plan_compile_failed dev-cli
    subprocess failure; it must now block with a precise, actionable
    reason_code naming the offending path and the authorized targets."""
    monkeypatch.setenv("SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT", "0")
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = armed_payload["manifest"]["run_id"]
    (run_dir / "edit-plan-1.json").write_text(json.dumps({
        "operations": [{"path": "other.py", "find": "x", "replace": "y"}],
    }), encoding="utf-8")
    with patch.dict(os.environ, {ENV_FLAG: "0"}, clear=False):
        os.environ.pop("SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON", None)
        runner_mod.execute_operator(str(repo), run_id)
    receipt = json.loads((run_dir / "operator-receipt.json").read_text(encoding="utf-8"))
    assert receipt["reason_code"] == "plan_path_not_authorized"
    assert "other.py" in receipt["stderr"]
    assert "src/app.py" in receipt["stderr"]
    assert receipt["execution_state"] == "blocked"


def test_flag_set_without_receipt_blocks_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT", "0")
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = armed_payload["manifest"]["run_id"]
    assert not receipt_path(run_dir).exists()
    with patch.dict(os.environ, _exec_env({ENV_FLAG: "1"}), clear=False):
        with pytest.raises(RuntimeError, match="mutation authority required"):
            runner_mod.execute_operator(str(repo), run_id)
    # fail-closed: no repository mutation happened
    assert json.loads((run_dir / "operator-receipt.json").read_text(encoding="utf-8"))["execution_state"] != "applied"


def test_flag_set_with_valid_receipt_allows_execution(tmp_path, monkeypatch):
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = armed_payload["manifest"]["run_id"]

    receipt = stage_valid_planning_receipt(repo=repo, run_dir=run_dir, armed_payload=armed_payload, run_id=run_id)
    assert receipt["ready_for_mutation"] is True

    with patch.dict(os.environ, _exec_env({ENV_FLAG: "1"}), clear=False):
        payload = runner_mod.execute_operator(str(repo), run_id)
    assert payload["state"]["phase"] == "validating"
    op_receipt = json.loads((run_dir / "operator-receipt.json").read_text(encoding="utf-8"))
    assert op_receipt["execution_state"] == "applied"


def test_flag_set_with_stale_receipt_blocks_after_plan_drift(tmp_path, monkeypatch):
    # A planning receipt minted for one plan must NOT authorize execution once the
    # plan on disk has drifted (simulates a repo/plan change between planning and
    # execution -- the exact "stale authority" scenario #284 calls out).
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = armed_payload["manifest"]["run_id"]

    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    stage_valid_planning_receipt(
        repo=repo, run_dir=run_dir, armed_payload=armed_payload, run_id=run_id,
        plan_override={**plan, "extra_marker": "stale-plan-version"},
    )

    with patch.dict(os.environ, _exec_env({ENV_FLAG: "1"}), clear=False):
        with pytest.raises(RuntimeError, match="mutation authority required"):
            runner_mod.execute_operator(str(repo), run_id)


def test_flag_set_blocks_on_github_source_drift_between_planning_and_execution(tmp_path, monkeypatch):
    # #284 item 1: the receipt was minted while the GitHub issue had content hash
    # "hash-a"; a caller that re-captures the source right before mutation and
    # writes source-snapshot-current.json with a DIFFERENT hash (the issue was
    # edited in between) must block execution instead of silently proceeding.
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = armed_payload["manifest"]["run_id"]

    source_at_planning = {"schema": "simplicio.source-snapshot/v1",
                          "source": {"provider": "github", "repo": "acme/repo", "item_id": "284",
                                     "revision": "r1", "snapshot_hash": "hash-a", "observed_at": "t1"}}
    receipt = stage_valid_planning_receipt(
        repo=repo, run_dir=run_dir, armed_payload=armed_payload, run_id=run_id,
        source_snapshot=source_at_planning,
    )
    assert receipt["ready_for_mutation"] is True

    # a fresh re-query right before mutation observes a DIFFERENT issue content hash
    (run_dir / "source-snapshot-current.json").write_text(
        json.dumps({"source": {"snapshot_hash": "hash-b-after-edit"}}), encoding="utf-8",
    )

    with patch.dict(os.environ, _exec_env({ENV_FLAG: "1"}), clear=False):
        with pytest.raises(RuntimeError, match="source_drift"):
            runner_mod.execute_operator(str(repo), run_id)


def test_flag_set_allows_execution_when_source_snapshot_unchanged(tmp_path, monkeypatch):
    repo, _, armed_payload, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = armed_payload["manifest"]["run_id"]

    source_snapshot = {"schema": "simplicio.source-snapshot/v1",
                       "source": {"provider": "github", "repo": "acme/repo", "item_id": "284",
                                  "revision": "r1", "snapshot_hash": "hash-a", "observed_at": "t1"}}
    stage_valid_planning_receipt(
        repo=repo, run_dir=run_dir, armed_payload=armed_payload, run_id=run_id,
        source_snapshot=source_snapshot,
    )
    (run_dir / "source-snapshot-current.json").write_text(
        json.dumps({"source": {"snapshot_hash": "hash-a"}}), encoding="utf-8",
    )

    with patch.dict(os.environ, _exec_env({ENV_FLAG: "1"}), clear=False):
        payload = runner_mod.execute_operator(str(repo), run_id)
    assert payload["state"]["phase"] == "validating"
    op_receipt = json.loads((run_dir / "operator-receipt.json").read_text(encoding="utf-8"))
    assert op_receipt["execution_state"] == "applied"


# --- same mandatory-by-default gate extended to execute_operator_batch() ----------


def test_batch_default_unset_blocks_without_receipt_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT", "0")
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)

    def fake_dispatch(items, **kwargs):
        raise AssertionError("dispatch must not be reached without a valid mutation authority")

    monkeypatch.setattr(runner_mod, "dispatch_operator_batch", fake_dispatch)
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop(ENV_FLAG, None)
        with pytest.raises(RuntimeError, match="mutation authority required"):
            runner_mod.execute_operator_batch(
                str(repo), armed["manifest"]["run_id"], max_workers=1,
                isolated_contexts={1: {"isolation": "shared"}}, auto_fan_out=False,
            )


def test_batch_explicit_opt_out_restores_zero_behavior_change(tmp_path, monkeypatch):
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    dispatched = []

    def fake_dispatch(items, **kwargs):
        dispatched.extend(list(items))
        return {"failed_task_indices": [], "dead_letter_task_indices": []}

    monkeypatch.setattr(runner_mod, "dispatch_operator_batch", fake_dispatch)
    with patch.dict(os.environ, {ENV_FLAG: "0"}, clear=False):
        result = runner_mod.execute_operator_batch(
            str(repo), armed["manifest"]["run_id"], max_workers=1,
            isolated_contexts={1: {"isolation": "shared"}}, auto_fan_out=False,
        )
    assert result["failed_task_indices"] == []
    assert len(dispatched) == 1


def test_batch_flag_set_without_receipt_blocks_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT", "0")
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    assert not receipt_path(run_dir).exists()

    def fake_dispatch(items, **kwargs):
        raise AssertionError("dispatch must not be reached without a valid mutation authority")

    monkeypatch.setattr(runner_mod, "dispatch_operator_batch", fake_dispatch)
    with patch.dict(os.environ, {ENV_FLAG: "1"}, clear=False):
        with pytest.raises(RuntimeError, match="mutation authority required"):
            runner_mod.execute_operator_batch(
                str(repo), armed["manifest"]["run_id"], max_workers=1,
                isolated_contexts={1: {"isolation": "shared"}}, auto_fan_out=False,
            )


def test_batch_flag_set_with_valid_receipt_dispatches(tmp_path, monkeypatch):
    repo, _, armed, run_dir = _arm_deterministic_preflight_fixture(monkeypatch, tmp_path)
    run_id = armed["manifest"]["run_id"]

    receipt = stage_valid_planning_receipt(repo=repo, run_dir=run_dir, armed_payload=armed, run_id=run_id)
    assert receipt["ready_for_mutation"] is True

    dispatched = []

    def fake_dispatch(items, **kwargs):
        dispatched.extend(list(items))
        return {"failed_task_indices": [], "dead_letter_task_indices": []}

    monkeypatch.setattr(runner_mod, "dispatch_operator_batch", fake_dispatch)
    with patch.dict(os.environ, {ENV_FLAG: "1"}, clear=False):
        result = runner_mod.execute_operator_batch(
            str(repo), run_id, max_workers=1,
            isolated_contexts={1: {"isolation": "shared"}}, auto_fan_out=False,
        )
    assert result["failed_task_indices"] == []
    assert len(dispatched) == 1
