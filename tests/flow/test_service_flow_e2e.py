"""One watcher tick on a real target repo: admit, map, plan, apply, verify, PR, status, events, report.

The watcher, turbo, Mapper and Dev CLI are real. GitHub (`gh`) and the planner CLI (`claude`) are fakes (see conftest).
The run uses the DEFAULT executor (host mode, `exec`): the planner CLI only plans, `turbo --apply -` applies and verifies.
One tick leaves one kanban run whose events.jsonl holds the whole pipeline (#1469).
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import execution_report
from simplicio_loop.dashboard import runs as dashboard_runs
from simplicio_loop.dashboard_events import read_events
from simplicio_loop.watcher247 import config, subscription, tick, verify
from tests.flow.conftest import ISSUE_NUMBER, ISSUE_TITLE, REPO_NAME

IDENT = f"{REPO_NAME}#{ISSUE_NUMBER}"
HEAD = f"loop/issue-{ISSUE_NUMBER}"
# The pipeline of #1469: the watcher's own stages wrap the turbo ones.
PIPELINE_STAGES = ["intake", "orient", "plan", "apply", "verify", "pr", "done"]
STATE_ROW = re.compile(r"\| Estado \| (\w+) \|")


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
    work = flow_base / "watcher-state" / "work"
    calls = [json.loads(line) for line in (flow_base / "gh-calls.jsonl").read_text().splitlines()]
    # #1601: the base clone is never edited. The item runs in `<repo>.wt/<issue>` and its `.simplicio-loop/` (map, events,
    # reports) is kept in `<repo>.state/<issue>` once the worktree is removed.
    return {"state": state_dir, "clone": work / REPO_NAME, "item_state": work / f"{REPO_NAME}.state" / str(ISSUE_NUMBER),
            "remote": remote_bare, "calls": calls}


def _claims(run) -> dict:
    return json.loads((run["state"] / "claims.json").read_text())


def _turbo_document(run) -> dict:
    log = run["state"] / "logs" / f"{REPO_NAME}-{ISSUE_NUMBER}-1-s1.log"  # attempt 1, planner step 1
    return verify.parse_turbo(log.read_text().split("\n--- stderr ---")[0])


def _canonical_calls(run) -> list[dict]:
    """Writes to the issue's status comments: the POST that creates it and every PATCH that updates it."""
    return [c for c in run["calls"] if c.get("method") in ("POST", "PATCH") and "/comments" in c.get("path", "")
            and "APROVADO PELO SQUAD" not in c.get("body", "")]  # the squad approval is on the PR


def _run_dirs(run) -> list[dict]:
    return dashboard_runs.discover_runs(run["item_state"])


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


def test_default_executor_planned_with_the_exec_cli_read_only(tick_run, planner_log):
    calls = [json.loads(line) for line in planner_log.read_text().splitlines()]
    assert len(calls) == 1, "the default executor must ask the exec CLI for exactly one plan"
    argv = calls[0]
    assert argv[0] == "-p" and ISSUE_TITLE in argv[1], "the planner gets the issue as its prompt"
    assert argv[argv.index("--permission-mode") + 1] == "plan", "the planner CLI must be plan-only"
    assert argv[argv.index("--output-format") + 1] == "json"


def test_mapper_produced_project_map(tick_run):
    assert not (tick_run["clone"] / ".simplicio-loop" / "project-map.json").exists(), "the base clone must stay unedited (#1601)"
    project_map = tick_run["item_state"] / ".simplicio-loop" / "project-map.json"
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


def test_verify_ran(tick_run):
    verify = _turbo_document(tick_run).get("verify")
    assert verify is not None, "verify did not run"
    assert verify["passed"] is True
    pr_calls = [c for c in tick_run["calls"] if c["argv"][:2] == ["pr", "create"]]
    assert "MEASURED|verify_passed" in pr_calls[0]["body"], "the PR must say how it was verified"


def test_commit_and_pr_references_issue_without_closing_word(tick_run):
    message = subprocess.run(
        ["git", "--git-dir", str(tick_run["remote"]), "log", "-1", "--format=%B", HEAD],
        capture_output=True, text=True, check=True,
    ).stdout
    assert f"Parte de #{ISSUE_NUMBER}" in message and "Closes" not in message
    pr_calls = [c for c in tick_run["calls"] if c["argv"][:2] == ["pr", "create"]]
    assert len(pr_calls) == 1, "gh pr create was not called exactly once"
    assert pr_calls[0]["base"] == "main"
    assert pr_calls[0]["head"] == HEAD
    assert f"Parte de #{ISSUE_NUMBER}" in pr_calls[0]["body"] and "Closes" not in pr_calls[0]["body"]


def test_one_canonical_status_comment_updated_across_phases(tick_run):
    writes = _canonical_calls(tick_run)
    assert len({c["comment_id"] for c in writes}) == 1, "expected exactly one status comment"
    assert [c["method"] for c in writes][0] == "POST"
    assert all(c["method"] == "PATCH" for c in writes[1:]), "later phases must edit the comment, not add one"
    states = [STATE_ROW.search(c["body"]).group(1) for c in writes]
    assert states == ["CLAIMED", "PLANNED", "IN_PROGRESS", "VERIFYING", "PR_OPEN"]


def _entered_phases(run) -> list[str]:
    runs = _run_dirs(run)
    assert len(runs) == 1, f"expected one run directory, got {len(runs)}"
    events = read_events(runs[0]["run_dir"])
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "events.jsonl seq must be strictly increasing"
    return [e["phase"] for e in events if e["kind"] == "phase_entered"]


def test_events_jsonl_covers_the_whole_pipeline(tick_run):
    assert _entered_phases(tick_run) == PIPELINE_STAGES


def test_pipeline_events_open_and_close_the_run_once_without_issue_text(tick_run):
    events = read_events(_run_dirs(tick_run)[0]["run_dir"])
    assert [e["kind"] for e in events].count("run_started") == 1
    assert [e["kind"] for e in events][-1] == "run_finished" and [e["kind"] for e in events].count("run_finished") == 1
    pr = next(e for e in events if e["kind"] == "phase_entered" and e["phase"] == "pr")
    assert pr["payload"]["pr_number"] is not None and pr["payload"]["from"] == "verify"
    intake = next(e for e in events if e["kind"] == "phase_entered" and e["phase"] == "intake")
    assert intake["payload"]["repo"] == REPO_NAME and intake["payload"]["issue"] == ISSUE_NUMBER
    assert ISSUE_TITLE not in json.dumps(events), "event payloads carry ids and numbers, never the issue text"


def test_events_parseable_by_dashboard_runs(tick_run):
    runs = dashboard_runs.list_runs(tick_run["item_state"])
    assert len(runs) == 1, f"dashboard sees {len(runs)} runs"
    assert runs[0]["last_seq"] >= len(PIPELINE_STAGES)
    assert runs[0]["status"] == "done"


def test_execution_report_written(tick_run):
    report = execution_report.load_latest(tick_run["item_state"])
    assert report is not None, "no execution report was written"
    assert report["schema"] == "simplicio.execution-report/v1"
    assert report["status"] == "COMPLETE"
    # Host mode: turbo's task for the run plus the watcher's role receipt, one task per planner step, in one report.
    steps = [t for t in report["tasks"] if "role" in t]
    assert len(steps) == 1 and len(report["tasks"]) == 2
    step = steps[0]
    assert (step["step"], step["role"], step["family"], step["planner"]) == (1, "execution", "claude", "ok")
    assert step["outcome"] == "COMPLETE"
    assert step["model"] and step["effort"], "the receipt names the model and effort the step ran with"
    tokens = step["tokens"]
    assert (tokens["tokens_in"], tokens["tokens_out"]) == (None, None), "an exec CLI reports no usage: UNVERIFIED, never invented"
    assert "tokens_*" in report["unverified_fields"]


def test_kanban_run_has_its_own_complete_report(tick_run):
    """The `turbo --apply -` run the kanban shows keeps the execution report turbo wrote for it."""
    run = _run_dirs(tick_run)[0]
    path = tick_run["item_state"] / _turbo_document(tick_run)["execution_report"]
    report = json.loads(path.read_text())
    assert report["schema"] == "simplicio.execution-report/v1"
    assert report["run_id"] == run["run_id"]
    assert report["status"] == "COMPLETE"


def test_execution_report_belongs_to_the_kanban_run(tick_run):
    report = execution_report.load_latest(tick_run["item_state"])
    assert report["run_id"] == _run_dirs(tick_run)[0]["run_id"], "the report belongs to the run the kanban shows"

