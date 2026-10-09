"""The watcher's intake and pr stages join the turbo run's events.jsonl (#1469)."""
import json
from pathlib import Path

from simplicio_loop import dashboard_events, turbo, turbo_cli
from simplicio_loop.dashboard import runs as dashboard_runs
from simplicio_loop.watcher247 import events
from tests.test_turbo_1433_unit import RECEIPT, _doc, _plan_file, _stub_dev_cli, repo  # noqa: F401 (repo is a fixture)


def _read(repo_root: Path, run_id: str) -> list[dict]:
    return dashboard_events.read_events(repo_root / ".simplicio-loop" / "orchestrator" / "runs" / run_id)


def _entered(rows: list[dict]) -> list[str]:
    return [e["phase"] for e in rows if e["kind"] == "phase_entered"]


def test_open_run_writes_intake_with_ids_only_and_lists_the_run(repo):
    run_id = events.open_run(repo, "demo", 7, fix=False)
    assert run_id is not None
    rows = _read(repo, run_id)
    assert [e["kind"] for e in rows] == ["run_started", "phase_entered"]
    assert rows[1]["phase"] == "intake"
    assert rows[1]["payload"] == {"from": None, "repo": "demo", "issue": 7, "kind": "issue"}
    assert [r["run_id"] for r in dashboard_runs.list_runs(repo)] == [run_id]


def test_close_run_writes_pr_with_number_then_done(repo):
    run_id = events.open_run(repo, "demo", 7)
    events.close_run(repo, run_id, "ok", pr_url="https://github.com/o/demo/pull/42")
    rows = _read(repo, run_id)
    assert _entered(rows) == ["intake", "pr", "done"]
    assert next(e for e in rows if e.get("phase") == "pr" and e["kind"] == "phase_entered")["payload"]["pr_number"] == 42
    assert rows[-1]["kind"] == "run_finished" and rows[-1]["payload"] == {"outcome": "ok"}
    assert dashboard_runs.list_runs(repo)[0]["status"] == "done"


def test_close_run_without_a_pr_skips_the_pr_stage_and_failure_closes_as_failed(repo):
    no_diff = events.open_run(repo, "demo", 7)
    events.close_run(repo, no_diff, "ok", pr_url=None)
    assert _entered(_read(repo, no_diff)) == ["intake", "done"]
    failed = events.open_run(repo, "demo", 8)
    events.close_run(repo, failed, "failed", pr_url="https://github.com/o/demo/pull/9")
    rows = _read(repo, failed)
    assert _entered(rows) == ["intake", "done"], "a failed run never claims a pr stage"
    assert rows[-1]["payload"] == {"outcome": "failed"}


def test_close_run_is_idempotent_and_fail_open(repo, tmp_path):
    run_id = events.open_run(repo, "demo", 7)
    events.close_run(repo, run_id, "failed")
    before = _read(repo, run_id)
    events.close_run(repo, run_id, "failed")  # the except path after a close: nothing more is written
    assert _read(repo, run_id) == before
    events.close_run(repo, None, "ok")  # no run was opened
    (tmp_path / "file").write_text("x")
    assert events.open_run(tmp_path / "file", "demo", 7) is None  # telemetry never raises into the tick
    events.close_run(tmp_path / "file", "turbo-x", "ok")


def test_turbo_continues_the_run_the_watcher_opened_and_leaves_it_open(repo, tmp_path, monkeypatch, capsys):
    run_id = events.open_run(repo, "demo", 7)
    assert turbo_cli.run(str(repo), ["write hello.txt"], run_id=run_id) == 0
    assert _doc(capsys)["run_id"] == run_id
    monkeypatch.setattr(turbo, "_dev_cli_bin", lambda: str(_stub_dev_cli(tmp_path, json.dumps(RECEIPT))))
    rc = turbo_cli.run(str(repo), [], apply=str(_plan_file(tmp_path)), run_id=run_id, verify="true", leave_open=True)
    assert rc == 0 and _doc(capsys)["run_id"] == run_id
    assert _entered(_read(repo, run_id)) == ["intake", "orient", "plan", "apply", "verify"]
    assert dashboard_runs.list_runs(repo)[0]["status"] == "running", "turbo leaves an ok run open for the watcher"
    events.close_run(repo, run_id, "ok", pr_url="https://github.com/o/demo/pull/5")
    assert _entered(_read(repo, run_id)) == ["intake", "orient", "plan", "apply", "verify", "pr", "done"]
    assert [r["run_id"] for r in dashboard_runs.list_runs(repo)] == [run_id]


def test_leave_open_never_hides_a_failed_apply(repo, tmp_path, monkeypatch, capsys):
    run_id = events.open_run(repo, "demo", 7)
    monkeypatch.setattr(turbo, "_dev_cli_bin", lambda: str(_stub_dev_cli(tmp_path, json.dumps(RECEIPT))))
    rc = turbo_cli.run(str(repo), [], apply=str(_plan_file(tmp_path)), run_id=run_id, verify="false", leave_open=True)
    assert rc == 1
    _doc(capsys)
    assert dashboard_runs.list_runs(repo)[0]["status"] == "failed"
