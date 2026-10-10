"""NO WASTED RETRIES: a deterministic operator failure is recorded once,
never retried across the retry budget -- see AGENTS.md item B."""
from __future__ import annotations

from simplicio_loop import runner as runner_mod
from tests.runner_patch import patch_runner


def _bad_find_record(**overrides):
    record = {
        "schema": "simplicio.operator-worker/v1",
        "worker_id": "w1",
        "repo": "/repo",
        "run_id": "run-1",
        "task_index": 1,
        "status": "failed",
        "execution_state": "blocked",
        "reason_code": "find_target_not_unique",
        "failure_fingerprint": "deadbeef",
    }
    record.update(overrides)
    return record


def test_deterministic_failure_stops_after_one_attempt(monkeypatch):
    calls = []

    def fake_dispatch_attempt(dispatch_item):
        calls.append(dispatch_item)
        return dict(_bad_find_record())

    patch_runner(monkeypatch, "_operator_dispatch_attempt", fake_dispatch_attempt)

    item = {
        "repo": "/repo", "run_id": "run-1", "task_index": 1,
        "worker_id": "w1", "task_id": "t1",
    }
    attempts = runner_mod._run_operator_item_process(item, retry_budget=3)

    assert len(calls) == 1
    assert len(attempts) == 1
    assert attempts[0]["dead_letter"] is True
    assert attempts[0]["retry_skipped_reason"] == "deterministic_failure_no_retry"


def test_transient_failure_still_retries_up_to_budget(monkeypatch):
    calls = []

    def fake_dispatch_attempt(dispatch_item):
        calls.append(dispatch_item)
        return {
            "schema": "simplicio.operator-worker/v1",
            "worker_id": "w1", "repo": "/repo", "run_id": "run-1", "task_index": 1,
            "status": "failed", "execution_state": "error",
            "reason_code": "lease_lost_during_execution",
            "failure_fingerprint": f"fp-{len(calls)}",
        }

    patch_runner(monkeypatch, "_operator_dispatch_attempt", fake_dispatch_attempt)

    item = {
        "repo": "/repo", "run_id": "run-1", "task_index": 1,
        "worker_id": "w1", "task_id": "t1",
    }
    attempts = runner_mod._run_operator_item_process(item, retry_budget=3)

    # retry_budget=3 -> up to 4 attempts, none deterministic, none succeed.
    assert len(calls) == 4
    assert len(attempts) == 4
    assert attempts[-1]["dead_letter"] is True
    assert "retry_skipped_reason" not in attempts[-1]


def test_classify_devcli_receipt_failure_from_stdout_text():
    assert runner_mod._classify_devcli_receipt_failure(
        {"stderr": "find target is not unique in file.py"}
    ) == "find_target_not_unique"
    assert runner_mod._classify_devcli_receipt_failure(
        {"stdout": {"error": "find text not found"}}
    ) == "find_target_not_found"
    assert runner_mod._classify_devcli_receipt_failure({"reason_code": "plan_compile_failed"}) == (
        "plan_compile_failed"
    )
    assert runner_mod._classify_devcli_receipt_failure({}) == ""


def test_classify_operator_exception_reason_code():
    assert runner_mod._classify_operator_exception_reason_code(
        RuntimeError("repository changed after planning; re-run mapper before execution")
    ) == "plan_repo_state_stale"
    assert runner_mod._classify_operator_exception_reason_code(
        RuntimeError("plan validation failed before operator execution: bad schema")
    ) == "plan_validation_failed"
    assert runner_mod._classify_operator_exception_reason_code(
        RuntimeError("simplicio-dev-cli missing required capabilities")
    ) == "operator_capabilities_missing"
    assert runner_mod._classify_operator_exception_reason_code(
        runner_mod.DevCliCapabilitiesUnavailableError("nope")
    ) == "devcli_capabilities_unavailable"
    assert runner_mod._classify_operator_exception_reason_code(
        RuntimeError("some other unrelated failure")
    ) == "operator_exception"
