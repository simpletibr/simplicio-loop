"""TDD unit tests for run.py's ``--tasks`` CLI flag and task-count-aware
results filename -- the pure/parseable pieces, not a real benchmark run
(which needs live LLM calls and is never invoked from a test)."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import run  # noqa: E402


def test_build_arg_parser_defaults_tasks_to_2():
    ap = run.build_arg_parser()
    args = ap.parse_args(["--arms", "normal"])
    assert args.tasks == 2


@pytest.mark.parametrize("n", [1, 2, 4])
def test_build_arg_parser_accepts_each_supported_task_count(n):
    ap = run.build_arg_parser()
    args = ap.parse_args(["--tasks", str(n)])
    assert args.tasks == n


def test_build_arg_parser_rejects_unsupported_task_count():
    ap = run.build_arg_parser()
    with pytest.raises(SystemExit):
        ap.parse_args(["--tasks", "3"])


def test_result_filename_includes_task_count():
    name = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=4)
    assert name == "2026-09-26-abc1234-t4.json"


def test_result_filename_differs_per_task_count():
    a = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=1)
    b = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=2)
    c = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=4)
    assert len({a, b, c}) == 3


def test_build_arg_parser_defaults_task_timeout_to_opencode_default():
    ap = run.build_arg_parser()
    args = ap.parse_args([])
    assert args.task_timeout == run.oc.DEFAULT_RUN_TIMEOUT


def test_build_arg_parser_accepts_custom_task_timeout():
    ap = run.build_arg_parser()
    args = ap.parse_args(["--task-timeout", "120"])
    assert args.task_timeout == 120


def test_build_arg_parser_batch_defaults_to_false():
    ap = run.build_arg_parser()
    args = ap.parse_args([])
    assert args.batch is False


def test_build_arg_parser_accepts_batch_flag():
    ap = run.build_arg_parser()
    args = ap.parse_args(["--batch"])
    assert args.batch is True


def test_result_filename_gets_batch_suffix_when_batch():
    name = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=4, batch=True)
    assert name == "2026-09-26-abc1234-t4-batch.json"


def test_result_filename_no_batch_suffix_by_default():
    name = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=4)
    assert name == "2026-09-26-abc1234-t4.json"


def test_build_arg_parser_settle_defaults_match_opencode_agent():
    ap = run.build_arg_parser()
    args = ap.parse_args([])
    assert args.settle_reads == run.oc.DEFAULT_SETTLE_READS
    assert args.settle_interval == run.oc.DEFAULT_SETTLE_INTERVAL_S
    assert args.settle_max_wait == run.oc.DEFAULT_SETTLE_MAX_WAIT_S


def test_build_arg_parser_accepts_custom_settle_values():
    ap = run.build_arg_parser()
    args = ap.parse_args(["--settle-reads", "5", "--settle-interval", "1.5", "--settle-max-wait", "30"])
    assert args.settle_reads == 5
    assert args.settle_interval == 1.5
    assert args.settle_max_wait == 30.0


# -- settled-usage baseline threading across tasks (issue #1335, no leakage) -

def test_run_arm_threads_settled_usage_as_next_tasks_baseline(monkeypatch, tmp_path):
    """``run_arm`` must (1) settle the ledger BEFORE task 1 and (2) hand each
    task's OWN settled reading to the next task as its baseline -- never the
    stale pre-run baseline -- so no task's cost can leak into another's."""
    monkeypatch.setattr(run.checker, "seed_repo", lambda fixture_dir, dest: None)
    monkeypatch.setattr(run.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(run, "_commit_if_changed", lambda *a, **k: None)
    monkeypatch.setattr(run.checker, "run_check", lambda *a, **k: (True, "ok", {}))
    monkeypatch.setattr(run.lc, "get_key", lambda arm: f"key-{arm}")

    settle_calls = {"n": 0}

    def fake_poll_settled_usage(fetch_fn, **kwargs):
        settle_calls["n"] += 1
        return {"value": 100.0, "settled": True}  # the pre-task-1 settle

    monkeypatch.setattr(run.oc, "poll_settled_usage", fake_poll_settled_usage)

    baselines_seen = []

    def fake_run_opencode(arm, text, repo_dir, *, key, config_dir, timeout, skill,
                           usage_baseline, settle_reads, settle_interval_s, settle_max_wait_s):
        baselines_seen.append(usage_baseline)
        # Each task settles at a strictly higher, distinct value.
        settled_value = usage_baseline + 0.001
        return {
            "turns": 1, "llm_calls": [], "commands": [], "final_text": None,
            "totals": run.oc.summarize([], []),
            "usage_settled_value": settled_value,
        }

    monkeypatch.setattr(run.oc, "run_opencode", fake_run_opencode)

    task_list = [
        {"index": 1, "kind": "create", "text": "t1", "verify_stage": 1},
        {"index": 2, "kind": "edit", "text": "t2", "verify_stage": 2},
    ]
    run.run_arm("normal", str(tmp_path / "fixture"), str(tmp_path / "repo"), sys.executable,
                60, task_list=task_list, config_dir=str(tmp_path / "home"))

    # Task 1's baseline is the pre-run settle (100.0); task 2's baseline is
    # task 1's OWN settled value (100.001), not the original 100.0 again.
    assert baselines_seen == [100.0, 100.001]


def test_build_batch_prompt_combines_all_task_texts_in_one_user_prompt():
    """Per-arm skill install/prefixing is ``opencode_agent.run_opencode``'s
    job now (``skill=True``); ``build_batch_prompt`` just concatenates the
    raw task texts into one prompt, arm-agnostic."""
    task_list = [
        {"index": 1, "text": "Create a.html"},
        {"index": 2, "text": "Edit a.html"},
    ]
    prompt = run.build_batch_prompt(task_list)
    assert "Create a.html" in prompt
    assert "Edit a.html" in prompt
    assert not prompt.startswith("/simplicio-loop")
