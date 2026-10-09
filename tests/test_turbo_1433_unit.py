"""#1433: turbo success needs a dev-cli receipt, the plan prompt is versioned, each run writes an
execution report, and each run writes dashboard stage events the run reader parses.

Red first: these tests describe the behavior before the implementation exists.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from simplicio_loop import dashboard_events, turbo, turbo_cli, turbo_provider
from simplicio_loop.dashboard import runs as dashboard_runs

REPO_FIXTURE = Path(__file__).resolve().parents[1] / "bench" / "llm_ab" / "fixture_hard"
PLAN = {"operations": [{"path": "hello.txt", "find": "", "replace": "hi\n"}]}
RECEIPT = {"schema": "simplicio.dev-cli.edit-receipt/v1", "applied": True, "receipt_digest": "deadbeef"}


def _stub_dev_cli(tmp_path: Path, apply_stdout: str | None) -> Path:
    """A dev-cli stand-in: `edit --apply` prints ``apply_stdout`` (or nothing); compile always succeeds."""
    body = "#!/bin/sh\ncase \"$*\" in *--apply*)\n"
    body += f"  printf '%s\\n' '{apply_stdout}' ;;\nesac\nexit 0\n" if apply_stdout else "  : ;;\nesac\nexit 0\n"
    path = tmp_path / "stub-dev-cli"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    (root / "hello.txt").write_text("", encoding="utf-8")
    state = root / ".simplicio-loop"
    state.mkdir()
    (state / "project-map.json").write_text(
        json.dumps({"schema": "simplicio.project-map/v1", "files": [{"path": "hello.txt", "symbols": []}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", AsyncMock(return_value=None))
    return root


def _plan_file(tmp_path: Path) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(PLAN), encoding="utf-8")
    return path


def _doc(capsys) -> dict:
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    return json.loads(lines[-1])


def _apply_host(repo: Path, tmp_path: Path, monkeypatch, stdout: str | None, capsys, **kwargs) -> tuple[int, dict]:
    monkeypatch.setattr(turbo, "_dev_cli_bin", lambda: str(_stub_dev_cli(tmp_path, stdout)))
    rc = turbo_cli.run(str(repo), [], apply=str(_plan_file(tmp_path)), **kwargs)
    return rc, _doc(capsys)


def _provider(repo: Path, tmp_path: Path, monkeypatch, stdout: str | None, capsys, *, usage: bool = True,
              verify: str | None = None) -> tuple[int, dict]:
    monkeypatch.setattr(turbo, "_dev_cli_bin", lambda: str(_stub_dev_cli(tmp_path, stdout)))
    monkeypatch.setattr(turbo_provider, "require_key", lambda api_key=None: "sk-test")

    async def fake_complete(arm, messages, *, session_id, **kwargs):
        reply = {"ok": True, "content": json.dumps(PLAN), "hedged": False, "latency_s": 0.01,
                 "provider": "test", "session_id": session_id, "cost": None, "usage_reported": usage}
        if usage:
            reply.update(prompt_tokens=10, completion_tokens=4, cached_tokens=0, reasoning_tokens=0)
        return reply

    monkeypatch.setattr(turbo_provider, "complete", fake_complete)
    rc = turbo_cli.run(str(repo), ["write hello.txt"], provider="openrouter", verify=verify)
    return rc, _doc(capsys)


# --- 1. success only with a dev-cli receipt -------------------------------------------------

def test_apply_without_dev_cli_receipt_is_blocked(repo, tmp_path, monkeypatch, capsys):
    rc, doc = _apply_host(repo, tmp_path, monkeypatch, None, capsys)

    assert rc == 2
    assert doc["status"] == "blocked"
    assert doc["reason_code"] == "no_apply_receipt"
    assert doc.get("applied") in (None, [])


def test_apply_with_dev_cli_receipt_is_ok_and_persisted(repo, tmp_path, monkeypatch, capsys):
    rc, doc = _apply_host(repo, tmp_path, monkeypatch, json.dumps(RECEIPT), capsys)

    assert rc == 0
    assert doc["status"] == "ok"
    assert doc["applied"] == ["hello.txt"]
    (receipt,) = doc["receipts"]
    stored = repo / receipt["path"]
    assert stored.is_file()
    assert stored.is_relative_to(repo / ".simplicio-loop" / "orchestrator" / "runs" / doc["run_id"])
    assert receipt["digest"] == hashlib.sha256(stored.read_bytes()).hexdigest()
    assert json.loads(stored.read_text(encoding="utf-8"))["receipt_digest"] == "deadbeef"


def test_receipt_is_found_after_human_text_on_stdout(repo, tmp_path, monkeypatch, capsys):
    noisy = "applying 1 operation\n" + json.dumps(RECEIPT)
    rc, doc = _apply_host(repo, tmp_path, monkeypatch, noisy, capsys)

    assert rc == 0 and doc["status"] == "ok"


def test_provider_success_requires_a_receipt(repo, tmp_path, monkeypatch, capsys):
    rc, doc = _provider(repo, tmp_path, monkeypatch, None, capsys)

    assert rc == 2
    assert doc["status"] == "blocked"
    assert doc["reason_code"] == "no_apply_receipt"


def test_provider_success_persists_every_receipt(repo, tmp_path, monkeypatch, capsys):
    rc, doc = _provider(repo, tmp_path, monkeypatch, json.dumps(RECEIPT), capsys)

    assert rc == 0 and doc["status"] == "ok"
    assert len(doc["receipts"]) == len(doc["applied"]) == 1
    assert (repo / doc["receipts"][0]["path"]).is_file()


# --- 2. versioned plan prompt ---------------------------------------------------------------

def test_prompt_version_is_a_constant_with_the_template_digest():
    assert turbo.PLAN_PROMPT_VERSION == "turbo-plan/v1"
    assert turbo.plan_prompt() == {
        "prompt_version": "turbo-plan/v1",
        "prompt_sha256": hashlib.sha256(turbo._PLANNER_SYSTEM.encode("utf-8")).hexdigest(),
    }


def test_prompt_version_is_in_the_request_and_the_apply_document(repo, tmp_path, monkeypatch, capsys):
    expected = turbo.plan_prompt()
    assert turbo_cli.run(str(repo), ["write hello.txt"]) == 0
    request = _doc(capsys)
    assert {k: request[k] for k in expected} == expected

    _rc, applied = _apply_host(repo, tmp_path, monkeypatch, json.dumps(RECEIPT), capsys)
    assert {k: applied[k] for k in expected} == expected


# --- 3. execution report per run ------------------------------------------------------------

def _report(repo: Path, run_id: str) -> dict:
    return json.loads((repo / ".simplicio-loop" / "runtime" / "execution-reports" / f"{run_id}.json").read_text(encoding="utf-8"))


def test_provider_run_writes_execution_report_with_measured_tokens(repo, tmp_path, monkeypatch, capsys):
    _rc, doc = _provider(repo, tmp_path, monkeypatch, json.dumps(RECEIPT), capsys)

    report = _report(repo, doc["run_id"])
    assert report["schema"] == "simplicio.execution-report/v1"
    assert doc["execution_report"] == f".simplicio-loop/runtime/execution-reports/{doc['run_id']}.json"
    (task,) = report["tasks"]
    assert task["wall_ms"] is not None and task["wall_ms"] >= 0
    assert task["tokens"]["tokens_in"] == 10
    assert task["tokens"]["tokens_out"] == 4
    assert task["tokens"]["source"] == "cli_measured"
    assert task["turbo"]["model_calls"] == 1
    assert task["turbo"]["hedges_fired"] == 0


def test_provider_without_usage_records_null_tokens_as_unverified(repo, tmp_path, monkeypatch, capsys):
    _rc, doc = _provider(repo, tmp_path, monkeypatch, json.dumps(RECEIPT), capsys, usage=False)

    report = _report(repo, doc["run_id"])
    (task,) = report["tasks"]
    assert task["tokens"]["tokens_in"] is None
    assert task["tokens"]["tokens_out"] is None
    assert task["tokens"]["source"] == "absent"
    assert "tokens_*" in report["unverified_fields"]
    assert task["turbo"]["model_calls"] == 1


def test_host_run_has_no_invented_tokens(repo, tmp_path, monkeypatch, capsys):
    _rc, doc = _apply_host(repo, tmp_path, monkeypatch, json.dumps(RECEIPT), capsys)

    report = _report(repo, doc["run_id"])
    (task,) = report["tasks"]
    assert task["tokens"]["tokens_in"] is None
    assert task["turbo"]["model_calls"] is None
    assert task["turbo"]["hedges_fired"] is None


# --- 4. stage events the dashboard reads ----------------------------------------------------

def _events(run_dir: Path) -> list[dict]:
    return dashboard_events.read_events(run_dir)


def test_provider_run_emits_stage_events_the_dashboard_reader_parses(repo, tmp_path, monkeypatch, capsys):
    emitter = dashboard_events.load()
    _rc, doc = _provider(repo, tmp_path, monkeypatch, json.dumps(RECEIPT), capsys, verify="true")

    run_dir = repo / ".simplicio-loop" / "orchestrator" / "runs" / doc["run_id"]
    events = _events(run_dir)
    assert events and all(not emitter.validate_envelope(e) for e in events)
    entered = [e["phase"] for e in events if e["kind"] == "phase_entered"]
    assert entered == ["orient", "plan", "apply", "verify", "done"]
    assert events[-1]["kind"] == "run_finished"

    rows = dashboard_runs.list_runs(repo)
    (row,) = [r for r in rows if r["run_id"] == doc["run_id"]]
    assert row["status"] == "done"
    assert row["last_seq"] == events[-1]["seq"]
    assert row["repo"] == str(repo)


def test_host_request_and_apply_share_one_run(repo, tmp_path, monkeypatch, capsys):
    assert turbo_cli.run(str(repo), ["write hello.txt"]) == 0
    request = _doc(capsys)
    assert request["status"] == "needs_plan"
    assert "--run-id" in request["apply"] and request["run_id"] in request["apply"]

    monkeypatch.setattr(turbo, "_dev_cli_bin", lambda: str(_stub_dev_cli(tmp_path, json.dumps(RECEIPT))))
    rc = turbo_cli.run(str(repo), [], apply=str(_plan_file(tmp_path)), run_id=request["run_id"], verify="true")
    applied = _doc(capsys)

    assert rc == 0 and applied["run_id"] == request["run_id"]
    run_dir = repo / ".simplicio-loop" / "orchestrator" / "runs" / request["run_id"]
    phases = [e["phase"] for e in _events(run_dir) if e["kind"] == "phase_entered"]
    assert phases == ["orient", "plan", "apply", "verify", "done"]
    assert [r["run_id"] for r in dashboard_runs.list_runs(repo)] == [request["run_id"]]


def test_blocked_run_is_visible_on_the_dashboard_as_blocked(repo, tmp_path, monkeypatch, capsys):
    rc, doc = _apply_host(repo, tmp_path, monkeypatch, None, capsys)

    assert rc == 2
    (row,) = dashboard_runs.list_runs(repo)
    assert row["run_id"] == doc["run_id"]
    assert row["status"] == "blocked"
