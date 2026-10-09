"""One watcher tick on a real target repo: admit, map, plan, apply, verify, PR, status, events, report.

The watcher, turbo, Mapper and Dev CLI are real. GitHub (`gh`) and the model are fakes (see conftest).
Assertions that depend on integrations not yet on the service path are strict xfails: they flip to
XPASS-as-failure once the integration lands, and the marker must then be removed.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import execution_report
from simplicio_loop.dashboard import runs as dashboard_runs
from simplicio_loop.dashboard_events import read_events
from simplicio_loop.watcher247 import config, subscription, tick
from tests.flow.conftest import ISSUE_NUMBER, REPO_NAME

IDENT = f"{REPO_NAME}#{ISSUE_NUMBER}"
HEAD = f"loop/issue-{ISSUE_NUMBER}"
STAGES = ["intake", "map", "plan", "apply", "verify", "pr", "report"]
AWAIT_1469 = "awaits #1469: watcher and skill share the stage pipeline and write events.jsonl"


@pytest.fixture(scope="module")
def tick_run(flow_env, flow_base: Path, remote_bare: Path):
    """Run exactly one watcher tick with the issue already past the baseline."""
    state_dir = flow_base / "watcher-state"
    previous_root = config.ROOT
    config.set_state_dir(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "baseline.json").write_text(json.dumps(
        {"created_at": "2026-10-08T00:00:00Z", "issues": []}))
    original_subscription = subscription.mcp_subscription

    async def active_subscription() -> dict:
        return {"active": True, "reason": "ok"}

    subscription.mcp_subscription = active_subscription
    try:
        asyncio.run(tick.tick())
    finally:
        subscription.mcp_subscription = original_subscription
        config.set_state_dir(previous_root)
    clone = flow_base / "watcher-state" / "work" / REPO_NAME
    calls = [json.loads(line) for line in (flow_base / "gh-calls.jsonl").read_text().splitlines()]
    return {"state": state_dir, "clone": clone, "remote": remote_bare, "calls": calls}


def _claims(run) -> dict:
    return json.loads((run["state"] / "claims.json").read_text())


def _turbo_document(run) -> dict:
    log = run["state"] / "logs" / f"{REPO_NAME}-{ISSUE_NUMBER}-1.log"
    return tick.parse_turbo(log.read_text().split("\n--- stderr ---")[0])


def _canonical_calls(run) -> list[dict]:
    """Writes to the issue's status comments: the POST that creates it and every PATCH that updates it."""
    return [c for c in run["calls"] if c.get("method") in ("POST", "PATCH") and "/comments" in c.get("path", "")]


def _run_dirs(run) -> list[dict]:
    return dashboard_runs.discover_runs(run["clone"])


def test_issue_admitted(tick_run):
    claim = _claims(tick_run).get(IDENT)
    assert claim is not None, "the open issue was not admitted"
    assert claim["attempts"] == 1
    assert claim["status"] == "done", claim


def test_lease_acquired_and_released(tick_run):
    claim = _claims(tick_run)[IDENT]
    assert claim.get("owner") == "simplicio-loop-247", "lease was not acquired by the watcher"
    assert not claim.get("owner_token"), "lease token still held after the tick"
    assert claim.get("lease_expires_at") is None, "lease not released"


def test_mapper_produced_project_map(tick_run):
    project_map = tick_run["clone"] / ".simplicio-loop" / "project-map.json"
    assert project_map.is_file(), "mapper did not write project-map.json"
    document = json.loads(project_map.read_text())
    assert document["schema"] == "simplicio.project-map/v1"
    assert any(f["path"] == "src/app.py" for f in document["files"])


def test_plan_applied_to_the_branch(tick_run):
    shown = subprocess.run(
        ["git", "--git-dir", str(tick_run["remote"]), "show", f"{HEAD}:src/app.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert 'return "hi"' in shown
    assert 'return "hello"' not in shown


@pytest.mark.xfail(strict=True, reason="awaits #1463: the watcher must pass --verify to turbo")
def test_verify_ran(tick_run):
    verify = _turbo_document(tick_run).get("verify")
    assert verify is not None, "verify did not run"
    assert verify["passed"] is True


def test_commit_and_pr_closes_issue(tick_run):
    message = subprocess.run(
        ["git", "--git-dir", str(tick_run["remote"]), "log", "-1", "--format=%B", HEAD],
        capture_output=True, text=True, check=True,
    ).stdout
    assert f"Closes #{ISSUE_NUMBER}" in message
    pr_calls = [c for c in tick_run["calls"] if c["argv"][:2] == ["pr", "create"]]
    assert len(pr_calls) == 1, "gh pr create was not called exactly once"
    assert pr_calls[0]["base"] == "main"
    assert pr_calls[0]["head"] == HEAD
    assert f"Closes #{ISSUE_NUMBER}" in pr_calls[0]["body"]


@pytest.mark.xfail(strict=True, reason="awaits #1492: the status comment must be PATCHed through the verify phase")
def test_one_canonical_status_comment_updated_across_phases(tick_run):
    ids = {c["comment_id"] for c in _canonical_calls(tick_run)}
    updates = [c for c in _canonical_calls(tick_run) if c["method"] == "PATCH"]
    assert len(ids) == 1, f"expected one status comment, got {len(ids)}"
    assert len(updates) >= 2, "the status comment was not updated across phases"


@pytest.mark.xfail(strict=True, reason=AWAIT_1469 + " (events.jsonl per run, stages in order)")
def test_events_jsonl_stages_in_order(tick_run):
    runs = _run_dirs(tick_run)
    assert len(runs) == 1, f"expected one run directory, got {len(runs)}"
    events = read_events(runs[0]["run_dir"])
    phases = [e["phase"] for e in events if e["kind"] == "phase_entered"]
    assert phases == STAGES


def test_events_parseable_by_dashboard_runs(tick_run):
    runs = dashboard_runs.list_runs(tick_run["clone"])
    assert len(runs) == 1, f"dashboard sees {len(runs)} runs"
    assert runs[0]["last_seq"] >= len(STAGES)


def test_execution_report_written(tick_run):
    report = execution_report.load_latest(tick_run["clone"])
    assert report is not None, "no execution report was written"
