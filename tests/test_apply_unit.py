"""Unit tests for `simplicio_loop.apply` (issue #1310, Turn 2 of the
plan-once/apply-once hot path).

Covers: validate-all-in-memory before any write, chain grouping
(parallel vs ordered), the single-task shorthand, stdin ops loading, and
concurrency isolation env for checks. System-level (real dev-cli subprocess,
real concurrency timing) tests live in test_apply_system.py.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from simplicio_loop import apply as apply_mod


def seed_mapper_fast_survey(root):
    """Write the minimal Mapper + Fast survey `simplicio-loop apply` requires
    (issue #1318): the Mapper project map and the brief's per-task Fast
    provenance, as a real `orient --brief` leaves them."""
    state = root / ".simplicio-loop"
    state.mkdir(parents=True, exist_ok=True)
    (state / "project-map.json").write_text("{}", encoding="utf-8")
    (state / "survey.json").write_text(json.dumps({"generations": [{
        "task": "t", "operator": "simplicio-fast",
        "generation": "sha256:test", "context_hash": "sha256:test"}]}), encoding="utf-8")


@pytest.fixture(autouse=True)
def _mapper_fast_survey(request, tmp_path):
    if request.node.get_closest_marker("no_survey") is None:
        seed_mapper_fast_survey(tmp_path)


def _write(root, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_load_ops_from_file(tmp_path):
    ops_path = tmp_path / "ops.json"
    ops_path.write_text(json.dumps({"tasks": [{"id": "t1", "operations": []}]}))
    ops = apply_mod.load_ops(str(ops_path))
    assert ops["tasks"][0]["id"] == "t1"


def test_load_ops_from_stdin(monkeypatch):
    payload = json.dumps({"tasks": [{"id": "t1", "operations": []}]})
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(payload))
    ops = apply_mod.load_ops("-")
    assert ops["tasks"][0]["id"] == "t1"


def test_normalize_tasks_shorthand_single_task():
    """A single-task ops.json (no explicit list ceremony needed beyond one
    entry) normalizes the same as a multi-task one."""
    ops = {"tasks": [{"id": "solo", "operations": [{"path": "a.txt", "find": "x", "replace": "y"}]}]}
    tasks = apply_mod._normalize_tasks(ops)
    assert len(tasks) == 1
    assert tasks[0]["depends_on"] == []
    assert tasks[0]["check"] is None


def test_normalize_tasks_rejects_duplicate_ids():
    ops = {"tasks": [
        {"id": "t1", "operations": [{"path": "a", "find": "x", "replace": "y"}]},
        {"id": "t1", "operations": [{"path": "b", "find": "x", "replace": "y"}]},
    ]}
    with pytest.raises(ValueError):
        apply_mod._normalize_tasks(ops)


def test_build_chains_disjoint_paths_are_parallel():
    tasks = [
        {"id": "t1", "operations": [{"path": "a.html", "find": "x", "replace": "y"}], "depends_on": []},
        {"id": "t2", "operations": [{"path": "b.html", "find": "x", "replace": "y"}], "depends_on": []},
    ]
    chains = apply_mod.build_chains(tasks)
    assert sorted(tuple(c) for c in chains) == [("t1",), ("t2",)]


def test_build_chains_shared_path_is_one_ordered_chain():
    tasks = [
        {"id": "create", "operations": [{"path": "a.html", "find": "", "replace": "<html></html>"}], "depends_on": []},
        {"id": "edit", "operations": [{"path": "a.html", "find": "<html>", "replace": "<html lang=en>"}],
         "depends_on": ["create"]},
    ]
    chains = apply_mod.build_chains(tasks)
    assert chains == [["create", "edit"]]


def test_build_chains_depends_on_without_shared_path_still_ordered():
    tasks = [
        {"id": "t1", "operations": [{"path": "a.txt", "find": "x", "replace": "y"}], "depends_on": []},
        {"id": "t2", "operations": [{"path": "b.txt", "find": "x", "replace": "y"}], "depends_on": ["t1"]},
    ]
    chains = apply_mod.build_chains(tasks)
    assert chains == [["t1", "t2"]]


def test_validate_ops_missing_find_is_blocked(tmp_path):
    _write(tmp_path, "a.txt", "hello world")
    tasks = apply_mod._normalize_tasks({"tasks": [
        {"id": "t1", "operations": [{"path": "a.txt", "find": "NOPE", "replace": "y"}]},
    ]})
    chains = apply_mod.build_chains(tasks)
    problems = apply_mod.validate_ops(tmp_path, tasks, chains)
    assert len(problems) == 1
    assert problems[0]["reason"] == "find_not_found"


def test_validate_ops_non_unique_find_is_blocked(tmp_path):
    _write(tmp_path, "a.txt", "x x")
    tasks = apply_mod._normalize_tasks({"tasks": [
        {"id": "t1", "operations": [{"path": "a.txt", "find": "x", "replace": "y"}]},
    ]})
    chains = apply_mod.build_chains(tasks)
    problems = apply_mod.validate_ops(tmp_path, tasks, chains)
    assert len(problems) == 1
    assert problems[0]["reason"] == "find_not_unique"


def test_validate_ops_chained_find_sees_prior_operation_in_same_chain(tmp_path):
    """A dependent edit's `find` must be checked against the state left by
    the task it depends on, not the original on-disk file."""
    _write(tmp_path, "a.html", "<html></html>")
    tasks = apply_mod._normalize_tasks({"tasks": [
        {"id": "create", "operations": [{"path": "a.html", "find": "<html></html>",
                                          "replace": "<html><body></body></html>"}]},
        {"id": "edit", "operations": [{"path": "a.html", "find": "<body></body>",
                                        "replace": "<body>hi</body>"}], "depends_on": ["create"]},
    ]})
    chains = apply_mod.build_chains(tasks)
    problems = apply_mod.validate_ops(tmp_path, tasks, chains)
    assert problems == []


def test_validate_ops_missing_path_is_blocked(tmp_path):
    tasks = apply_mod._normalize_tasks({"tasks": [
        {"id": "t1", "operations": [{"path": "missing.txt", "find": "x", "replace": "y"}]},
    ]})
    chains = apply_mod.build_chains(tasks)
    problems = apply_mod.validate_ops(tmp_path, tasks, chains)
    assert problems[0]["reason"] == "path_not_found"


def test_validate_ops_create_new_file_with_empty_find(tmp_path):
    tasks = apply_mod._normalize_tasks({"tasks": [
        {"id": "t1", "operations": [{"path": "new.html", "find": "", "replace": "<html></html>"}]},
    ]})
    chains = apply_mod.build_chains(tasks)
    problems = apply_mod.validate_ops(tmp_path, tasks, chains)
    assert problems == []


def test_run_blocked_validation_writes_nothing(tmp_path, monkeypatch):
    _write(tmp_path, "a.txt", "hello")
    ops = {"tasks": [{"id": "t1", "operations": [{"path": "a.txt", "find": "NOPE", "replace": "y"}]}]}
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("must not shell out on BLOCKED validation")

    monkeypatch.setattr(subprocess, "run", _boom)
    result = apply_mod.run(ops, repo=tmp_path)
    assert result["status"] == "BLOCKED"
    assert called["n"] == 0
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"


def test_run_stale_generation_is_blocked_with_no_write(tmp_path, monkeypatch):
    _write(tmp_path, "a.txt", "hello")
    monkeypatch.setattr(apply_mod, "_repo_fingerprint",
                         lambda root, **_kw: {"tree_hash": "CURRENT", "head": "", "dirty_status_hash": ""})
    ops = {
        "tasks": [{"id": "t1", "operations": [{"path": "a.txt", "find": "hello", "replace": "bye"}]}],
        "repo_state_chain": {"tree_hash": "STALE"},
    }
    result = apply_mod.run(ops, repo=tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "stale_mapper_generation"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"


def test_run_ignores_ops_file_at_repo_root_when_checking_staleness(tmp_path, monkeypatch):
    """issue #1318: an untracked ops.json written at the repo root -- not
    just under `.simplicio-loop/` -- must never itself make the repo look
    stale relative to a `repo_state_chain` computed before that file
    existed."""
    _write(tmp_path, "a.txt", "hello")
    expected_state = apply_mod._repo_fingerprint(tmp_path)

    ops_path = tmp_path / "ops.json"
    ops = {
        "tasks": [{"id": "t1", "operations": [{"path": "a.txt", "find": "hello", "replace": "bye"}]}],
        "repo_state_chain": expected_state,
    }
    ops_path.write_text(json.dumps(ops), encoding="utf-8")

    monkeypatch.setattr(apply_mod, "_apply_task_devcli",
                         lambda root, task, run_dir: {"ok": True, "steps": [], "reason_code": None})
    result = apply_mod.run(ops, repo=tmp_path, ops_path=ops_path)
    assert result["status"] == "PASS", result


def test_run_without_ops_path_still_blocks_on_real_drift(tmp_path):
    """The exclusion must be scoped to the ops file itself -- a real content
    change elsewhere still trips the staleness gate."""
    _write(tmp_path, "a.txt", "hello")
    expected_state = apply_mod._repo_fingerprint(tmp_path)
    _write(tmp_path, "b.txt", "unexpected new file")
    ops = {
        "tasks": [{"id": "t1", "operations": [{"path": "a.txt", "find": "hello", "replace": "bye"}]}],
        "repo_state_chain": expected_state,
    }
    result = apply_mod.run(ops, repo=tmp_path, ops_path=tmp_path / "ops.json")
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "stale_mapper_generation"


def test_check_isolation_env_contains_expected_keys():
    env = apply_mod._isolated_check_env(base_env={"PATH": "/bin"}, run_id="r1", task_id="t1")
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "no:cacheprovider" in env["PYTEST_ADDOPTS"]
    assert "r1" in env["COVERAGE_FILE"] and "t1" in env["COVERAGE_FILE"]
    assert env["PATH"] == "/bin"


def test_run_result_carries_next_effort_medium_on_pass(tmp_path, monkeypatch):
    """issue #1310 follow-up: PASS -> the next turn reviews the result, so
    ``next_effort`` is the review-phase effort."""
    from simplicio_loop.effort import PHASE_EFFORT

    _write(tmp_path, "a.txt", "hello")
    monkeypatch.setattr(apply_mod, "_apply_task_devcli", lambda root, task, run_dir: {"ok": True, "steps": [], "reason_code": None})
    ops = {"tasks": [{"id": "t1", "operations": [{"path": "a.txt", "find": "hello", "replace": "bye"}]}]}
    result = apply_mod.run(ops, repo=tmp_path)
    assert result["status"] == "PASS"
    assert result["next_effort"] == PHASE_EFFORT["review"]


def test_run_result_carries_next_effort_low_on_fail(tmp_path, monkeypatch):
    """FAIL -> a mechanical fix turn with the failing tail already in hand,
    so ``next_effort`` is the execute-phase effort."""
    from simplicio_loop.effort import PHASE_EFFORT

    _write(tmp_path, "a.txt", "hello")
    monkeypatch.setattr(
        apply_mod, "_apply_task_devcli",
        lambda root, task, run_dir: {"ok": False, "steps": [], "reason_code": "dev_cli_apply_failed"},
    )
    ops = {"tasks": [{"id": "t1", "operations": [{"path": "a.txt", "find": "hello", "replace": "bye"}]}]}
    result = apply_mod.run(ops, repo=tmp_path)
    assert result["status"] == "FAIL"
    assert result["next_effort"] == PHASE_EFFORT["execute"]


def test_run_result_carries_next_effort_low_on_blocked_validation(tmp_path):
    from simplicio_loop.effort import PHASE_EFFORT

    ops = {"tasks": [{"id": "t1", "operations": [{"path": "missing.txt", "find": "x", "replace": "y"}]}]}
    result = apply_mod.run(ops, repo=tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["next_effort"] == PHASE_EFFORT["execute"]


@pytest.mark.no_survey
def test_run_without_mapper_fast_survey_is_blocked_and_writes_nothing(tmp_path):
    """Every flow goes through Mapper + Fast: no survey, no apply."""
    _write(tmp_path, "a.txt", "hello\n")
    ops = {"tasks": [{"id": "t1", "operations": [{"path": "a.txt", "find": "hello", "replace": "bye"}]}]}
    result = apply_mod.run(ops, repo=tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "mapper_fast_provenance_missing"
    assert (tmp_path / "a.txt").read_text() == "hello\n"


@pytest.mark.no_survey
def test_run_with_fast_provenance_but_no_mapper_map_is_blocked(tmp_path):
    _write(tmp_path, "a.txt", "hello\n")
    ops = {"tasks": [{"id": "t1", "operations": [{"path": "a.txt", "find": "hello", "replace": "bye"}]}],
           "brief_generations": [{"operator": "simplicio-fast", "generation": "g", "context_hash": "c"}]}
    assert apply_mod.run(ops, repo=tmp_path)["reason_code"] == "mapper_fast_provenance_missing"


def test_run_receipt_records_mapper_fast_provenance(tmp_path, monkeypatch):
    _write(tmp_path, "a.txt", "hello\n")
    monkeypatch.setattr(apply_mod, "_apply_task_devcli",
                        lambda root, task, run_dir: {"ok": True, "steps": [], "reason_code": None})
    ops = {"tasks": [{"id": "t1", "operations": [{"path": "a.txt", "find": "hello", "replace": "bye"}]}]}
    result = apply_mod.run(ops, repo=tmp_path)
    receipt = json.loads(open(result["receipt_path"]).read())
    assert receipt["mapper_fast"]["generations"][0]["context_hash"] == "sha256:test"


# --- issue #1336: compact/slim default `apply` CLI output ------------------


def test_slim_task_view_pass_has_only_id_and_status():
    view = apply_mod._slim_task_view({"id": "t1", "status": "PASS", "check": {"ok": True, "stdout_tail": "x" * 5000}})
    assert view == {"id": "t1", "status": "PASS"}


def test_slim_task_view_skipped_carries_reason_code():
    view = apply_mod._slim_task_view({"id": "t2", "status": "SKIPPED", "reason_code": "upstream_task_failed"})
    assert view == {"id": "t2", "status": "SKIPPED", "reason_code": "upstream_task_failed"}


def test_slim_task_view_fail_includes_check_tail_last_20_lines():
    lines = [f"line{i}" for i in range(1, 40)]
    task_result = {"id": "t3", "status": "FAIL",
                   "apply": {"ok": True}, "check": {"ok": False, "stderr_tail": "\n".join(lines)}}
    view = apply_mod._slim_task_view(task_result)
    assert view["id"] == "t3"
    assert view["status"] == "FAIL"
    kept = view["check_tail"].splitlines()
    assert len(kept) == 20
    assert kept[0] == "line20"
    assert kept[-1] == "line39"


def test_slim_task_view_fail_from_apply_step_has_reason_code_no_check_tail():
    task_result = {"id": "t4", "status": "FAIL", "apply": {"ok": False, "reason_code": "dev_cli_apply_failed"}}
    view = apply_mod._slim_task_view(task_result)
    assert view == {"id": "t4", "status": "FAIL", "reason_code": "dev_cli_apply_failed"}


def test_slim_result_blocked_is_passed_through_unchanged():
    blocked = {"schema": "s", "status": "BLOCKED", "reason_code": "x", "hint": "h"}
    assert apply_mod._slim_result(blocked) == blocked


def test_slim_result_pass_drops_diff_and_full_task_detail():
    result = {
        "schema": "s", "status": "PASS", "run_id": "r1", "ops_sha": "sha", "next_effort": "low",
        "receipt_path": "/tmp/receipt.json",
        "tasks": [{"id": "t1", "status": "PASS", "apply": {"ok": True, "steps": ["big"]},
                   "check": {"ok": True, "stdout_tail": "noise"}}],
        "diff": {"changed": ["a.txt"]},
    }
    slim = apply_mod._slim_result(result)
    assert slim["status"] == "PASS"
    assert slim["tasks"] == [{"id": "t1", "status": "PASS"}]
    assert slim["receipt_path"] == "/tmp/receipt.json"
    assert "diff" not in slim


def test_apply_main_default_stdout_is_compact_single_line(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.txt", "hello")
    monkeypatch.setattr(apply_mod, "_apply_task_devcli",
                        lambda root, task, run_dir: {"ok": True, "steps": [], "reason_code": None})
    ops_path = tmp_path / "ops.json"
    ops_path.write_text(json.dumps({"tasks": [{"id": "t1", "operations": [
        {"path": "a.txt", "find": "hello", "replace": "bye"}]}]}), encoding="utf-8")

    code = apply_mod.main(str(ops_path), repo=str(tmp_path))
    out = capsys.readouterr().out
    assert code == 0
    assert out.rstrip("\n").count("\n") == 0
    payload = json.loads(out)
    assert payload["status"] == "PASS"
    assert payload["tasks"] == [{"id": "t1", "status": "PASS"}]
    assert "diff" not in payload


def test_apply_main_pretty_flag_is_larger_and_indented(tmp_path, monkeypatch, capsys):
    _write(tmp_path, "a.txt", "hello")
    monkeypatch.setattr(apply_mod, "_apply_task_devcli",
                        lambda root, task, run_dir: {"ok": True, "steps": [], "reason_code": None})
    ops_path = tmp_path / "ops.json"
    ops_path.write_text(json.dumps({"tasks": [{"id": "t1", "operations": [
        {"path": "a.txt", "find": "hello", "replace": "bye"}]}]}), encoding="utf-8")

    apply_mod.main(str(ops_path), repo=str(tmp_path))
    slim_out = capsys.readouterr().out

    apply_mod.main(str(ops_path), repo=str(tmp_path), pretty=True)
    pretty_out = capsys.readouterr().out

    assert pretty_out.rstrip("\n").count("\n") > 0
    assert len(slim_out) < len(pretty_out)
    assert "diff" in json.loads(pretty_out)
