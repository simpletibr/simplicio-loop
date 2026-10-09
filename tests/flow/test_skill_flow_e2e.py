"""The /simplicio-loop skill path: turbo in host mode, the plan written by the host and piped on stdin.

No provider and no key: the host model is the planner. Same stage vocabulary and report as the
service flow.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import execution_report
from simplicio_loop.dashboard import runs as dashboard_runs
from simplicio_loop.dashboard_events import read_events
from tests.flow.conftest import (
    ISSUE_BODY,
    ISSUE_TITLE,
    PLAN,
    REPO_NAME,
    git,
    last_json,
    run_cli,
)

STAGES = ["orient", "plan", "apply", "verify", "done"]  # what turbo writes to events.jsonl (turbo_run)
VERIFY = f"{sys.executable} -m py_compile src/app.py"


@pytest.fixture(scope="module")
def host_repo(tmp_path_factory, flow_base: Path, remote_bare: Path) -> Path:
    """A working copy of the seed project, the way a host session sees its checkout."""
    work = tmp_path_factory.mktemp("host") / REPO_NAME
    subprocess.run(["git", "clone", "-q", "file://" + str(remote_bare), str(work)], check=True)
    git(work, "checkout", "-q", "-b", "feat/host-flow")
    return work


@pytest.fixture(scope="module")
def host_env(flow_env):
    """Host mode needs no provider and no key: unset the key so the flow cannot silently call a model."""
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("OPENROUTER_API_KEY", raising=False)
        yield {k: v for k, v in flow_env.items() if k != "OPENROUTER_API_KEY"}


@pytest.fixture(scope="module")
def host_applied(host_repo: Path, host_env):
    """Step 1 asks for the plan; step 2 applies the host's plan from stdin and verifies it."""
    task = f"{ISSUE_TITLE}. {ISSUE_BODY}"
    request = run_cli(["turbo", "--repo", str(host_repo), "--task", task], host_repo, host_env)
    assert request.returncode == 0, request.stderr
    asked = last_json(request.stdout)
    # The request prints the run id its `apply` command continues: one run, request then apply.
    apply = run_cli(
        ["turbo", "--repo", str(host_repo), "--apply", "-", "--run-id", asked["run_id"], "--verify", VERIFY],
        host_repo, host_env, stdin=json.dumps(PLAN),
    )
    return {"request": asked, "apply": last_json(apply.stdout), "returncode": apply.returncode}


def test_host_turbo_asks_the_host_for_a_plan(host_applied):
    assert host_applied["request"]["schema"] == "simplicio.turbo-request/v1"
    assert host_applied["request"]["status"] == "needs_plan"
    assert host_applied["request"]["map"], "the request carries the mapper slice"


def test_host_plan_applied_from_stdin(host_applied, host_repo: Path):
    assert host_applied["apply"]["status"] == "ok", host_applied["apply"]
    assert host_applied["returncode"] == 0
    assert 'return "hi"' in (host_repo / "src" / "app.py").read_text()


def test_host_verify_ran_and_passed(host_applied):
    verify = host_applied["apply"]["verify"]
    assert verify is not None, "verify did not run"
    assert verify["passed"] is True


def test_host_events_stages_in_order(host_applied, host_repo: Path):
    runs = dashboard_runs.discover_runs(host_repo)
    assert len(runs) == 1, f"expected one run directory, got {len(runs)}"
    events = read_events(runs[0]["run_dir"])
    phases = [e["phase"] for e in events if e["kind"] == "phase_entered"]
    assert phases == STAGES


def test_host_events_parseable_by_dashboard_runs(host_applied, host_repo: Path):
    runs = dashboard_runs.list_runs(host_repo)
    assert len(runs) == 1, f"dashboard sees {len(runs)} runs"
    assert runs[0]["last_seq"] >= len(STAGES)
    assert runs[0]["status"] == "done"


def test_host_execution_report_written(host_applied, host_repo: Path):
    report = execution_report.load_latest(host_repo)
    assert report is not None, "no execution report was written"
    assert report["schema"] == "simplicio.execution-report/v1"
    assert report["status"] == "COMPLETE"
    assert report["run_id"] == dashboard_runs.discover_runs(host_repo)[0]["run_id"]
    assert report["execution_profile"] == "turbo-host"
