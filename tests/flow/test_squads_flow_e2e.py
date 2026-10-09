"""The 24/7 watcher in squads, end to end (#1505): two admitted issues, one squad, review, opt-in batch merge.

The watcher, turbo, Mapper, Dev CLI, git and the merge train's test run are real. GitHub (`gh`) and the planner CLI
(`claude`) are the fakes of conftest; the fake `gh pr view` answers with the approval comment the squad coordinator
posted, so the real `squads.squad_gate` decides the merge.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import model_roles
from simplicio_loop.watcher247 import config, subscription, tick
from tests.flow.conftest import ISSUE_BODY, REPO_NAME, make_remote

NUMBERS = (7, 8)


def _issue(number: int) -> dict:
    return {"number": number, "title": f"Trocar a saudacao para hi ({number})", "body": ISSUE_BODY,
            "createdAt": "2026-10-08T12:00:00Z", "labels": [{"name": "loop:auto"}],
            "author": {"login": "wesleysimplicio"}, "authorAssociation": "MEMBER"}


def _run(flow_env, flow_base: Path, name: str, auto_merge: bool) -> dict:
    """One tick on a fresh remote and state dir; the fake gh fixtures point at that remote."""
    remote = make_remote(flow_base / name)
    fixtures_path = Path(flow_env["FAKE_GH_FIXTURES"])
    fixtures = json.loads(fixtures_path.read_text())
    fixtures.update(remotes={REPO_NAME: str(remote)}, distinct_prs=True)
    fixtures["issues"] = {f"simpletibr/{REPO_NAME}": [_issue(n) for n in NUMBERS]}
    fixtures_path.write_text(json.dumps(fixtures))
    log = Path(flow_env["FAKE_GH_LOG"])
    log.unlink(missing_ok=True)
    state_dir = flow_base / f"{name}-state"
    state_dir.mkdir(parents=True)
    (state_dir / "baseline.json").write_text(json.dumps({"created_at": "2026-10-08T00:00:00Z", "issues": []}))
    previous, original = config.ROOT, subscription.mcp_subscription

    async def active() -> dict:
        return {"active": True, "reason": "ok"}

    config.set_state_dir(state_dir)
    subscription.mcp_subscription = active
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
        if auto_merge:
            patch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
        else:
            patch.delenv("SIMPLICIO_247_AUTO_MERGE", raising=False)
        try:
            asyncio.run(tick.tick())
        finally:
            subscription.mcp_subscription = original
            config.set_state_dir(previous)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return {"state": state_dir, "clone": state_dir / "work" / REPO_NAME, "calls": calls,
            "status": json.loads((state_dir / "status.json").read_text())}


@pytest.fixture(scope="module")
def merged(flow_env, flow_base):
    return _run(flow_env, flow_base, "merged", auto_merge=True)


@pytest.fixture(scope="module")
def unmerged(flow_env, flow_base):
    return _run(flow_env, flow_base, "unmerged", auto_merge=False)


def _approvals(run) -> list[dict]:
    return [c for c in run["calls"] if c.get("method") == "POST" and "APROVADO PELO SQUAD" in c.get("body", "")]


def _merges(run) -> list[int]:
    return [c["merge"] for c in run["calls"] if "merge" in c]


def test_two_issues_form_one_squad_with_a_coordinator_and_two_workers(merged):
    (squad,) = merged["status"]["squads"][REPO_NAME]["squads"]
    assert squad["issues"] == list(NUMBERS) and len(squad["workers"]) == 2 and squad["coordinator"].endswith("-coord")
    assert sorted(json.loads((merged["state"] / "claims.json").read_text())) == [f"{REPO_NAME}#{n}" for n in NUMBERS]


def test_the_squad_coordinator_approves_each_pr_through_pr_evidence(merged):
    assert sorted(c["path"].split("/")[-2] for c in _approvals(merged)) == ["107", "108"]
    assert merged["status"]["squads"][REPO_NAME]["approved"] == [107, 108]


def test_auto_merge_tests_the_batch_once_and_merges_in_order(merged):
    entry = merged["status"]["squads"][REPO_NAME]
    assert entry["merge"] == "enabled" and entry["merged"] == [107, 108] and entry["failed"] == []
    assert _merges(merged) == [107, 108]
    merges = subprocess.run(["git", "log", "--format=%s", "loop/merge-train"], cwd=merged["clone"],
                            check=True, capture_output=True, text=True).stdout  # the temporary train branch
    assert all(f"({issue})" in merges for issue in NUMBERS)


def test_without_auto_merge_the_squad_approves_and_nothing_merges(unmerged):
    assert len(_approvals(unmerged)) == 2
    assert unmerged["status"]["squads"][REPO_NAME]["merge"] == "disabled"
    assert _merges(unmerged) == []


def test_role_model_and_effort_of_every_agent_are_in_the_execution_report(merged):
    path = merged["state"] / "squads" / ".simplicio-loop" / "runtime" / "execution-reports" / "latest.json"
    report = json.loads(path.read_text())
    assert report["consolidated"]["tasks_by_role"] == {"coordination": 1, "execution": 2, "planning": 1}
    for task in report["tasks"]:
        agent = task["agent"]
        assert agent["model"] == model_roles.resolve("claude", agent["role"])["model"]
        assert agent["effort"] == model_roles.resolve("claude", agent["role"])["effort"]
