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


def _run(flow_env, flow_base: Path, name: str, auto_merge: bool, approval_author: str = "", baseline: bool = False) -> dict:
    """One tick on a fresh remote and state dir; the fake gh fixtures point at that remote."""
    remote = make_remote(flow_base / name)
    fixtures_path = Path(flow_env["FAKE_GH_FIXTURES"])
    fixtures = json.loads(fixtures_path.read_text())
    fixtures.update(remotes={REPO_NAME: str(remote)}, distinct_prs=True, approval_author=approval_author)  # approval_author: who the fake PR shows as the approval's author
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
        if baseline:
            patch.setenv("SIMPLICIO_247_SQUADS_BASELINE", "1")
        else:
            patch.delenv("SIMPLICIO_247_SQUADS_BASELINE", raising=False)
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


@pytest.fixture(scope="module")
def outsider(flow_env, flow_base):
    return _run(flow_env, flow_base, "outsider", auto_merge=True, approval_author="outsider")


@pytest.fixture(scope="module")
def baseline_merged(flow_env, flow_base):
    return _run(flow_env, flow_base, "baseline-merged", auto_merge=True, baseline=True)


@pytest.fixture(scope="module")
def baseline_unmerged(flow_env, flow_base):
    return _run(flow_env, flow_base, "baseline-unmerged", auto_merge=False, baseline=True)


@pytest.fixture(scope="module")
def baseline_outsider(flow_env, flow_base):
    return _run(flow_env, flow_base, "baseline-outsider", auto_merge=True, approval_author="outsider", baseline=True)


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


def test_an_approval_written_by_an_outsider_never_merges_even_with_auto_merge(outsider):
    """#1534: the real gate rejects the approval phrase when its author is not the watcher's gh login."""
    entry = outsider["status"]["squads"][REPO_NAME]
    assert entry["merge"] == "enabled" and entry["merged"] == [] and entry["gate_blocked"] == [107, 108]
    assert _merges(outsider) == []


def test_each_worker_task_records_its_escalation_and_dependency_wait_from_the_real_run(merged):
    """#1549: the real ladder ran (no failure here), so the zero escalations are measured; no dependency, so the wait is a measured 0."""
    path = merged["state"] / "squads" / ".simplicio-loop" / "runtime" / "execution-reports" / "latest.json"
    workers = [t for t in json.loads(path.read_text())["tasks"] if t.get("issue")]
    assert len(workers) == 2
    for task in workers:
        record = task["squad_metrics"]
        assert (record["initial_role"], record["final_role"], record["escalations"]) == ("execution", "execution", [])
        assert record["dependency_wait_s"] == 0.0 and record["final_outcome"] == "ok"
        assert record["proof_kind"] == {"escalations": "measured", "dependency_wait": "measured", "final_outcome": "measured"}
    metrics = merged["status"]["squads"][REPO_NAME]["metrics"]
    assert (metrics["tasks"], metrics["escalation_n"], metrics["escalated"], metrics["escalation_rate"]) == (2, 2, 0, 0.0)


# --- #1565: baseline mode (SIMPLICIO_247_SQUADS_BASELINE=1) is recorded, and it never loosens a merge rule ---


def _report(run) -> dict:
    return json.loads((run["state"] / "squads" / ".simplicio-loop" / "runtime" / "execution-reports" / "latest.json").read_text())


def _trains(run) -> int:
    """How many times the merge train rebuilt its temporary branch: one per batch."""
    reflog = subprocess.run(["git", "reflog", "show", "--format=%gs", "loop/merge-train"], cwd=run["clone"],
                            check=True, capture_output=True, text=True).stdout
    return sum(1 for line in reflog.splitlines() if line.startswith(("branch: Created from", "branch: Reset to")))


def test_the_default_run_is_v2_in_the_status_and_the_report(merged):
    assert merged["status"]["squads"][REPO_NAME]["mode"] == "v2" and _report(merged)["mode"] == "v2"


def test_baseline_mode_is_recorded_in_the_status_and_the_report(baseline_merged):
    assert baseline_merged["status"]["squads"][REPO_NAME]["mode"] == "baseline" and _report(baseline_merged)["mode"] == "baseline"


def test_baseline_merges_the_same_prs_in_the_same_order_one_train_per_pr(merged, baseline_merged):
    assert _merges(baseline_merged) == _merges(merged) == [107, 108]
    entry = baseline_merged["status"]["squads"][REPO_NAME]
    assert entry["merge"] == "enabled" and entry["merged"] == [107, 108] and entry["failed"] == []
    assert (_trains(merged), _trains(baseline_merged)) == (1, 2)  # v2 tests the batch once; baseline tests each PR alone


def test_baseline_without_auto_merge_approves_and_never_merges(baseline_unmerged):
    assert len(_approvals(baseline_unmerged)) == 2 and _merges(baseline_unmerged) == []
    assert baseline_unmerged["status"]["squads"][REPO_NAME]["merge"] == "disabled"


def test_baseline_never_merges_an_approval_written_by_an_outsider(baseline_outsider):
    entry = baseline_outsider["status"]["squads"][REPO_NAME]
    assert entry["merge"] == "enabled" and entry["merged"] == [] and entry["gate_blocked"] == [107, 108]
    assert _merges(baseline_outsider) == []


def test_baseline_records_its_metrics_and_the_cli_labels_baseline_against_v2(merged, baseline_merged, tmp_path, capsys):
    from simplicio_loop import cli_impl
    sides = {}
    for label, run in (("before", baseline_merged), ("after", merged)):
        folder = run["state"] / "squads" / ".simplicio-loop" / "runtime" / "execution-reports"
        assert cli_impl.main(["squads", "metrics", "--reports", str(folder), "--json"]) == 0
        sides[label] = tmp_path / f"{label}.json"
        sides[label].write_text(capsys.readouterr().out)
        assert json.loads(sides[label].read_text())["mode"] == ("baseline" if label == "before" else "v2")
    assert cli_impl.main(["squads", "metrics", "--compare", str(sides["before"]), str(sides["after"]), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert (result["before_mode"], result["after_mode"]) == ("baseline", "v2")
    assert cli_impl.main(["squads", "metrics", "--compare", str(sides["after"]), str(sides["after"]), "--json"]) == 2  # two runs of one mode
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
