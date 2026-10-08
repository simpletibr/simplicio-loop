"""Integration: `apply.run` emits quality events (test/lint/coverage from each
task's check, and the apply diff) into the active run's events.jsonl, and the
emission never changes what `run` returns (issue #1403 follow-up).

Every emitted line must satisfy the simplicio.dashboard-event/v1 envelope.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import dashboard_events as de
import pytest

from simplicio_loop import apply as apply_mod

QUALITY_KINDS = {"test_result", "lint_result", "coverage_result"}
RESULT_KEYS = {"schema", "status", "ops_sha", "tasks", "diff", "run_id", "receipt_path", "next_effort"}
RECEIPT_KEYS = {"schema", "ops_sha", "chains", "tasks", "status", "repo_state_before",
                "repo_state_after", "diff", "mapper", "run_id", "created_at"}
TASK_RECORD_KEYS = {"id", "apply", "apply_duration_s", "check", "status"}


def seed_mapper_survey(root: Path) -> None:
    state = root / ".simplicio-loop"
    state.mkdir(parents=True, exist_ok=True)
    (state / "project-map.json").write_text("{}", encoding="utf-8")
    (state / "survey.json").write_text(json.dumps({"generations": [{
        "task": "t", "operator": "simplicio-mapper",
        "generation": "sha256:test", "context_hash": "sha256:test"}]}), encoding="utf-8")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True).stdout


def _apply_in_process(root: Path, task: dict, run_dir: Path) -> dict:
    """Stands in for simplicio-dev-cli: applies the task's find/replace in-process."""
    for op in task["operations"]:
        path = root / op["path"]
        path.write_text(path.read_text(encoding="utf-8").replace(op["find"], op["replace"], 1), encoding="utf-8")
    return {"ok": True, "steps": [], "reason_code": None}


@pytest.fixture(autouse=True)
def _hermetic_repo(tmp_path, monkeypatch):
    for name in ("SIMPLICIO_DASHBOARD_EVENTS", "SIMPLICIO_RUN_DIR", "SIMPLICIO_RUN_ID", "SIMPLICIO_ITERATION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    seed_mapper_survey(tmp_path)
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.setattr(apply_mod, "_apply_task_devcli", _apply_in_process)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv("SIMPLICIO_RUN_DIR", str(run))
    monkeypatch.setenv("SIMPLICIO_ITERATION", "3")
    return run


def _ops(check=None, replace="bye\n", task_id="T1"):
    task = {"id": task_id, "operations": [{"path": "a.txt", "find": "hello\n", "replace": replace}]}
    if check is not None:
        task["check"] = check
    return {"tasks": [task]}


def _events(run: Path) -> list[dict]:
    path = run / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _of_kind(run: Path, kind: str) -> list[dict]:
    return [e for e in _events(run) if e["kind"] == kind]


def _assert_all_valid(run: Path) -> None:
    events = _events(run)
    assert events, "expected at least one emitted event"
    for evt in events:
        assert de.validate_envelope(evt) == [], evt


def test_pytest_summary_check_emits_one_test_result(run_dir, tmp_path):
    result = apply_mod.run(_ops(check="printf '3 passed in 0.10s\\n'"), repo=tmp_path)
    assert result["status"] == "PASS"
    events = _of_kind(run_dir, "test_result")
    assert len(events) == 1
    evt = events[0]
    assert evt["payload"]["passed"] == 3
    assert evt["payload"]["status"] == "pass"
    assert evt["iteration"] == 3
    assert evt["task_id"] == "T1"
    assert evt["scope"] == "task"
    _assert_all_valid(run_dir)


def test_ruff_style_output_emits_one_lint_result(run_dir, tmp_path):
    check = ("printf 'src/a.py:1:1: F401 os imported but unused\\n"
             "src/b.py:10:80: E501 Line too long\\nFound 2 errors.\\n'; exit 1")
    result = apply_mod.run(_ops(check=check), repo=tmp_path)
    assert result["status"] == "FAIL"
    events = _of_kind(run_dir, "lint_result")
    assert len(events) == 1
    assert events[0]["payload"]["errors"] == 2
    assert events[0]["payload"]["status"] == "fail"
    assert events[0]["task_id"] == "T1"
    _assert_all_valid(run_dir)


def test_coverage_total_line_emits_one_coverage_result(run_dir, tmp_path):
    check = "printf 'Name Stmts Miss Cover\\nsrc/a.py 10 2 80%%\\nTOTAL 30 2 93%%\\n'"
    result = apply_mod.run(_ops(check=check), repo=tmp_path)
    assert result["status"] == "PASS"
    events = _of_kind(run_dir, "coverage_result")
    assert len(events) == 1
    assert events[0]["payload"]["percent"] == 93.0
    assert events[0]["payload"]["scope"] == "total"
    _assert_all_valid(run_dir)


def test_changed_file_emits_one_diff_apply_result_matching_git(run_dir, tmp_path):
    result = apply_mod.run(_ops(), repo=tmp_path)
    assert result["status"] == "PASS"
    events = _of_kind(run_dir, "apply_result")
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["step"] == "diff"
    assert events[0]["task_id"] == "apply"
    assert events[0]["scope"] == "task"

    numstat = _git(tmp_path, "diff", "--numstat", "HEAD").strip().split("\t")
    added, deleted, path = int(numstat[0]), int(numstat[1]), numstat[2]
    assert payload["files"] == [path]
    assert payload["files_total"] == 1
    assert payload["added"] == added
    assert payload["deleted"] == deleted
    assert payload["files"] == result["diff"]["measurements"]["changed_files"]
    _assert_all_valid(run_dir)


def test_unrecognised_check_output_emits_no_quality_events(run_dir, tmp_path):
    result = apply_mod.run(_ops(check="echo hello"), repo=tmp_path)
    assert result["status"] == "PASS"
    assert result["tasks"][0]["check"]["stdout_tail"] == "hello\n"
    assert not [e for e in _events(run_dir) if e["kind"] in QUALITY_KINDS]


def test_without_run_dir_nothing_is_written_and_result_is_unchanged(tmp_path):
    result = apply_mod.run(_ops(check="printf '3 passed in 0.10s\\n'"), repo=tmp_path)
    assert result["status"] == "PASS"
    assert result["tasks"][0]["check"]["stdout_tail"] == "3 passed in 0.10s\n"
    assert list(tmp_path.rglob("events.jsonl")) == []


def test_emission_does_not_change_result_or_receipt_keys(run_dir, tmp_path, monkeypatch):
    check = "printf '3 passed in 0.10s\\n'"
    with_events = apply_mod.run(_ops(check=check), repo=tmp_path)
    monkeypatch.delenv("SIMPLICIO_RUN_DIR")
    _git(tmp_path, "checkout", "--", "a.txt")
    without_events = apply_mod.run(_ops(check=check), repo=tmp_path)

    for result in (with_events, without_events):
        assert set(result) == RESULT_KEYS
        assert set(result["tasks"][0]) == TASK_RECORD_KEYS
        assert result["status"] == "PASS"
        receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        assert set(receipt) == RECEIPT_KEYS
    assert _of_kind(run_dir, "test_result")
