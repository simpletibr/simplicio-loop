"""Escalation rate and dependency wait recorded by the squads tick (#1549): MEASURED values only.

The escalation comes from the worker's real steps (exec mode, a stub planner CLI and the FakeRun of turbo); the dependency
wait comes from two instants the flow observes (the squad approves the PR, the dependency's merge succeeds), read from a
fake clock so the expected number is exact.
"""
from __future__ import annotations

import json
import re

import pytest

from simplicio_loop import cli_impl, squad_metrics
from simplicio_loop.watcher247 import config, host_mode, squad_flow

from .fakes import FakeRun, baseline, issue, read_json, run_tick
from .test_host_mode import BAD, OK, HostRun, checkout, cli_dir  # noqa: F401  (cli_dir is a fixture)

REPO = "simplicio-a"


def _squads_report() -> dict:
    return json.loads((config.ROOT / "squads" / ".simplicio-loop" / "runtime" / "execution-reports" / "latest.json").read_text())


def _worker_metrics(number: int) -> dict:
    (task,) = [t for t in _squads_report()["tasks"] if t.get("issue") == f"{REPO}#{number}"]
    return task["squad_metrics"]


def _view(number: int) -> dict:
    # Hermetic: use proper 40-character SHAs for squad_gate and include OID marker in approval comment
    oid = f"abc123def456789012345678901234567890{number:04d}"[:40]
    approval_body = f"REVISÃO AUTOMÁTICA: APROVADA (nível 1)\n<!-- simplicio-loop:squad-approval:{oid} -->"
    return {"files": [{"path": f"src/m{number}/app.py"}], "headRefOid": oid,
            "commits": [{"oid": oid, "committedDate": "2026-10-01T00:00:00Z", "messageHeadline": "loop: x"}],
            "comments": [{"id": number, "createdAt": "2026-10-02T00:00:00Z", "body": approval_body,
                          "author": {"login": "squad-bot"}, "authorAssociation": "MEMBER"}]}


# --- escalation: the real ladder, a planner stub, turbo's apply failing twice ---


def test_a_task_that_climbs_a_role_records_where_it_started_where_it_ended_and_why(env, cli_dir):
    env(HostRun({REPO: [issue(1)]}, [BAD, BAD, OK], distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    checkout()
    run_tick()
    record = _worker_metrics(1)
    assert record["initial_role"] == "execution" and record["final_role"] == "coordination"
    assert record["escalations"] == [{"from": "execution", "to": "coordination", "reason": "verify_failed", "attempt": 3}]
    assert record["proof_kind"]["escalations"] == "measured" and "escalations" not in record["unverified"]


def test_the_status_block_of_the_repo_carries_the_same_record_and_the_rate(env, cli_dir):
    env(HostRun({REPO: [issue(1)]}, [BAD, BAD, OK], distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    checkout()
    run_tick()
    entry = read_json(config.STATUS)["squads"][REPO]
    (row,) = entry["task_metrics"]
    assert row["issue"] == f"{REPO}#1" and row["escalations"] == _worker_metrics(1)["escalations"]
    metrics = entry["metrics"]
    assert (metrics["tasks"], metrics["escalation_n"], metrics["escalated"], metrics["escalation_rate"]) == (1, 1, 1, 1.0)
    assert metrics["by_initial_role"] == {"execution": {"n": 1, "escalated": 1, "escalation_rate": 1.0}}
    assert metrics["escalations_by_transition"] == {"execution->coordination": 1}


def test_a_task_that_never_climbs_is_a_measured_zero_not_a_missing_value(env, cli_dir):
    env(HostRun({REPO: [issue(1)]}, [OK], distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    checkout()
    run_tick()
    record = _worker_metrics(1)
    assert (record["initial_role"], record["final_role"], record["escalations"]) == ("execution", "execution", [])
    assert record["proof_kind"]["escalations"] == "measured"


def test_an_executor_that_records_no_steps_is_unverified_with_a_reason(env):
    """The opt-in openrouter executor has no ladder: nothing was observed, so nothing is claimed (not a zero)."""
    env(FakeRun({REPO: [issue(1)]}, distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    run_tick()
    record = _worker_metrics(1)
    assert record["escalations"] is None and record["initial_role"] is None and record["final_role"] is None
    assert record["proof_kind"]["escalations"] == "UNVERIFIED" and record["unverified"]["escalations"] == "no_steps_recorded"
    metrics = read_json(config.STATUS)["squads"][REPO]["metrics"]
    assert (metrics["escalation_n"], metrics["escalation_unverified"], metrics["escalation_rate"]) == (0, 1, None)


# --- #1565: a task that climbed and then failed, or finished with no PR, is recorded too (no survivorship bias) ---


def _worker_task(number: int) -> dict:
    (task,) = [t for t in _squads_report()["tasks"] if t.get("issue") == f"{REPO}#{number}"]
    return task


def test_a_task_that_climbs_and_then_fails_is_a_measured_escalation_with_outcome_failed(env, cli_dir):
    """Every apply fails: execution, execution, coordination, planning, then the step limit. Before #1565 this task was invisible."""
    env(HostRun({REPO: [issue(1)]}, [BAD], distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    checkout()
    run_tick()
    assert read_json(config.CLAIMS)[f"{REPO}#1"]["status"] == "retry"  # the worker really failed
    record = _worker_metrics(1)
    assert (record["initial_role"], record["final_role"]) == ("execution", "planning")
    assert record["escalations"] == [{"from": "execution", "to": "coordination", "reason": "verify_failed", "attempt": 3},
                                     {"from": "coordination", "to": "planning", "reason": "verify_failed", "attempt": 4}]
    assert record["final_outcome"] == "failed" and record["proof_kind"]["final_outcome"] == "measured"
    assert record["proof_kind"]["escalations"] == "measured" and "escalations" not in record["unverified"]
    task = _worker_task(1)
    assert task["outcome"] == "FAIL" and task["agent"]["role"] == "planning"  # the report shows the failure and where it ended


def test_a_failed_task_counts_in_the_escalation_rate_and_in_its_own_outcome_row(env, cli_dir):
    env(HostRun({REPO: [issue(1)]}, [BAD], distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    checkout()
    run_tick()
    entry = read_json(config.STATUS)["squads"][REPO]
    assert entry["approved"] == [] and entry["merge"] == "disabled"  # a failed worker has no PR to review or merge
    metrics = entry["metrics"]
    assert (metrics["tasks"], metrics["escalation_n"], metrics["escalated"], metrics["escalation_rate"]) == (1, 1, 1, 1.0)
    assert metrics["by_final_outcome"]["failed"] == {"n": 1, "escalated": 1, "escalation_rate": 1.0}
    assert metrics["by_final_outcome"]["ok"]["n"] == 0
    (row,) = entry["task_metrics"]
    assert row["final_outcome"] == "failed"


def test_a_task_that_stops_at_the_ceiling_without_climbing_is_a_measured_zero_with_outcome_failed(env, cli_dir, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_ATTEMPT_CEILING_ISSUE", "2")
    env(HostRun({REPO: [issue(1)]}, [BAD], distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    checkout()
    run_tick()
    record = _worker_metrics(1)
    assert (record["initial_role"], record["final_role"], record["escalations"]) == ("execution", "execution", [])
    assert record["final_outcome"] == "failed" and record["proof_kind"]["escalations"] == "measured"


def test_a_task_that_climbs_and_finishes_with_no_diff_is_escalated_with_outcome_no_pr(env, cli_dir):
    env(HostRun({REPO: [issue(1)]}, [BAD, BAD, OK], diff=False, distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    checkout()
    run_tick()
    assert read_json(config.CLAIMS)[f"{REPO}#1"]["status"] == "done_no_diff"
    record = _worker_metrics(1)
    assert record["escalations"] == [{"from": "execution", "to": "coordination", "reason": "verify_failed", "attempt": 3}]
    assert record["final_outcome"] == "no_pr" and record["proof_kind"]["final_outcome"] == "measured"
    assert _worker_task(1)["outcome"] == "FAIL"  # no PR: the worker did not deliver
    by_outcome = read_json(config.STATUS)["squads"][REPO]["metrics"]["by_final_outcome"]
    assert by_outcome["no_pr"] == {"n": 1, "escalated": 1, "escalation_rate": 1.0}


def test_a_task_that_finishes_with_a_pr_is_outcome_ok(env, cli_dir):
    env(HostRun({REPO: [issue(1)]}, [BAD, BAD, OK], distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    checkout()
    run_tick()
    assert _worker_metrics(1)["final_outcome"] == "ok" and _worker_task(1)["outcome"] == "COMPLETE"
    by_outcome = read_json(config.STATUS)["squads"][REPO]["metrics"]["by_final_outcome"]
    assert by_outcome["ok"] == {"n": 1, "escalated": 1, "escalation_rate": 1.0}


def test_a_task_that_failed_before_any_step_keeps_the_no_steps_unverified_path(env, cli_dir):
    """turbo cannot even build the request: no step ran, so nothing about escalation is claimed (not a zero)."""
    env(HostRun({REPO: [issue(1)]}, request={"status": "failed", "detail": "no map"}, distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    checkout()
    run_tick()
    record = _worker_metrics(1)
    assert record["escalations"] is None and record["unverified"]["escalations"] == "no_steps_recorded"
    assert record["final_outcome"] is None and record["unverified"]["final_outcome"] == "outcome_not_observed"
    metrics = read_json(config.STATUS)["squads"][REPO]["metrics"]
    assert (metrics["escalation_n"], metrics["escalation_unverified"], metrics["escalation_rate"]) == (0, 1, None)


def test_the_executor_without_a_ladder_knows_the_outcome_but_not_the_escalation(env):
    env(FakeRun({REPO: [issue(1)]}, distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    run_tick()
    record = _worker_metrics(1)
    assert record["final_outcome"] == "ok" and record["proof_kind"]["final_outcome"] == "measured"
    assert record["unverified"] == {"escalations": "no_steps_recorded"}


class PerIssueRun(HostRun):
    """HostRun whose applies fail for the given issues and pass for the others (the request step names the issue; the repo lock keeps
    the request and its apply together). With worktrees, the issue is extracted from the cwd path."""

    def __init__(self, *args, failing=(), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.failing = set(failing)

    async def __call__(self, argv, timeout=120, cwd=None, stdin=None, env=None):
        argv = list(argv)
        # Extract issue number from worktree path: .../simplicio-a.wt/N or base clone path
        issue_num = None
        if cwd and ".wt/" in str(cwd):
            # Extract from worktree path: /path/repo.wt/N
            match = re.search(r'\.wt/(\d+)(?:/|$)', str(cwd))
            if match:
                issue_num = int(match.group(1))
        if "--apply" in argv and issue_num:
            self.applies = [BAD] if issue_num in self.failing else [OK]
        return await super().__call__(argv, timeout, cwd, stdin, env)


def test_a_failed_worker_does_not_change_which_other_pr_is_approved_and_merged_and_the_split_shows_both(env, cli_dir, monkeypatch):
    """Issue 1 climbs all the way and fails; issue 2 passes at once. The completed-only rate would say 0.0, the overall says 0.5."""
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    rows = [issue(n, f"Task {n}", body="Ajustar `app.py` para o fluxo do watcher seguir o contrato descrito abaixo.") for n in (1, 2)]
    fake = env(PerIssueRun({REPO: rows}, [OK], failing={1}, distinct_prs=True,
                           pr_views={101: _view(1), 102: _view(2)}))
    baseline()
    checkout()
    run_tick()
    entry = read_json(config.STATUS)["squads"][REPO]
    claims = read_json(config.CLAIMS)
    assert claims[f"{REPO}#1"]["status"] == "retry" and claims[f"{REPO}#2"]["status"] == "done"
    assert fake.merges == [102] and entry["approved"] == [102] and entry["merged"] == [102]
    assert (_worker_metrics(1)["final_outcome"], _worker_metrics(2)["final_outcome"]) == ("failed", "ok")
    metrics = entry["metrics"]
    assert (metrics["escalation_n"], metrics["escalated"], metrics["escalation_rate"]) == (2, 1, 0.5)
    assert metrics["by_final_outcome"]["ok"] == {"n": 1, "escalated": 0, "escalation_rate": 0.0}
    assert metrics["by_final_outcome"]["failed"] == {"n": 1, "escalated": 1, "escalation_rate": 1.0}


@pytest.mark.parametrize("attached,expected", [
    (None, []), ([], []), ("verify_failed", []), ({"role": "execution"}, []), (7, []),
    ([{"role": "execution", "outcome": "failed"}], [{"role": "execution", "outcome": "failed"}])])
def test_steps_of_an_exception_is_the_list_run_exec_attached_and_nothing_else(attached, expected):
    exc = RuntimeError("no verified plan")
    if attached is not None:
        exc.exec_steps = attached
    assert host_mode.steps_of(exc) == expected


def test_steps_of_returns_a_copy_the_caller_can_keep():
    exc = RuntimeError("x")
    exc.exec_steps = [{"role": "execution"}]
    got = host_mode.steps_of(exc)
    got.append({"role": "planning"})
    assert exc.exec_steps == [{"role": "execution"}]


# --- dependency wait: squad B depends on A; the wait is the gap between two observed instants ---


class FakeClock:
    """The flow's monotonic clock, moved by the fake gh at the two events that matter."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TimedRun(FakeRun):
    """FakeRun that sets the clock at the events: the approval comment of PR 102, and the merge of each PR."""

    def __init__(self, clock: FakeClock, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.clock = clock

    async def __call__(self, argv, timeout=120, cwd=None, stdin=None, env=None):
        result = await super().__call__(argv, timeout, cwd, stdin, env)
        argv = list(argv)
        if argv[:2] == ["gh", "api"] and "-X" in argv and argv[argv.index("-X") + 1] == "POST" \
                and any(a.endswith("/issues/102/comments") for a in argv):
            self.clock.now = 100.0  # B's PR is approved: B is ready to merge
        if argv[:3] == ["gh", "pr", "merge"]:
            self.clock.now = {"101": 112.5, "102": 130.0}[argv[3]]  # A merges 12.5 s after B was ready
        return result


@pytest.fixture
def dependent(env, monkeypatch):
    """Two issues of one repo, #2 depends on #1; a pre-cloned repo; PRs 101 and 102; a fake clock."""
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    clock = FakeClock()
    monkeypatch.setattr(squad_flow, "clock", clock)
    clone = config.WORK / REPO
    (clone / ".git").mkdir(parents=True)

    def make(auto_merge: bool):
        if auto_merge:
            monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
        else:
            monkeypatch.delenv("SIMPLICIO_247_AUTO_MERGE", raising=False)
        rows = [issue(1, "Task 1", body="Ajustar `src/m1/app.py` para o fluxo do watcher seguir o contrato descrito abaixo."),
                issue(2, "Task 2", body="Ajustar `src/m2/app.py` para o fluxo do watcher seguir o contrato descrito abaixo."
                                        " Depende de #1.")]
        fake = env(TimedRun(clock, {REPO: rows}, distinct_prs=True,
                            pr_views={101: _view(1), 102: _view(2)}))
        baseline()
        return fake
    return make


def test_a_dependent_task_waits_exactly_the_gap_between_its_approval_and_its_dependencys_merge(dependent):
    fake = dependent(auto_merge=True)
    run_tick()
    assert fake.merges == [101, 102]
    waiting = _worker_metrics(2)
    assert waiting["depends_on"] == [1] and waiting["dependency_wait_s"] == 12.5  # 112.5 - 100.0
    assert waiting["proof_kind"]["dependency_wait"] == "measured" and "dependency_wait_s" not in waiting["unverified"]
    free = _worker_metrics(1)
    assert free["depends_on"] == [] and free["dependency_wait_s"] == 0.0 and free["proof_kind"]["dependency_wait"] == "measured"


def test_the_status_block_summarizes_the_wait_with_n(dependent):
    dependent(auto_merge=True)
    run_tick()
    metrics = read_json(config.STATUS)["squads"][REPO]["metrics"]
    assert (metrics["dependency_wait_n"], metrics["no_dependency_tasks"], metrics["dependency_wait_unverified"]) == (1, 1, 0)
    assert metrics["dependency_wait_p50_s"] == metrics["dependency_wait_p95_s"] == metrics["dependency_wait_max_s"] == 12.5


def test_without_a_merge_the_dependency_wait_is_unverified_never_estimated(dependent):
    fake = dependent(auto_merge=False)
    run_tick()
    assert fake.merges == []
    waiting = _worker_metrics(2)
    assert waiting["dependency_wait_s"] is None and waiting["proof_kind"]["dependency_wait"] == "UNVERIFIED"
    assert waiting["unverified"]["dependency_wait_s"] == "dependency_merge_not_observed: #1"
    assert _worker_metrics(1)["dependency_wait_s"] == 0.0  # no dependency: a measured zero even without a merge
    metrics = read_json(config.STATUS)["squads"][REPO]["metrics"]
    assert (metrics["dependency_wait_n"], metrics["dependency_wait_unverified"], metrics["dependency_wait_p50_s"]) == (0, 1, None)


def test_a_dependent_whose_pr_was_never_approved_is_unverified_with_a_reason(dependent):
    fake = dependent(auto_merge=True)
    fake.pr_views[102] = {}  # `gh pr view` answers nothing: the squad cannot review B's PR
    run_tick()
    waiting = _worker_metrics(2)
    assert waiting["dependency_wait_s"] is None and waiting["unverified"]["dependency_wait_s"] == "task_never_ready"


def test_the_cli_aggregates_the_report_the_tick_wrote_to_the_same_numbers_as_the_status_block(dependent, capsys):
    dependent(auto_merge=True)
    run_tick()
    reports = config.ROOT / "squads" / ".simplicio-loop" / "runtime" / "execution-reports"
    capsys.readouterr()
    assert cli_impl.main(["squads", "metrics", "--reports", str(reports), "--json"]) == 0  # latest.json is not counted twice
    summary = json.loads(capsys.readouterr().out)
    status = read_json(config.STATUS)["squads"][REPO]["metrics"]
    assert summary["reports"] == 1 and summary["tasks"] == 2
    for key in ("tasks", "issues", "escalation_n", "escalation_unverified", "dependency_wait_n", "no_dependency_tasks",
                "dependency_wait_p50_s", "dependency_wait_p95_s", "dependency_wait_max_s"):
        assert summary[key] == status[key], key


# --- the recorder is fail-open: whatever goes wrong in it never changes which PR merges, or whether the tick finishes ---


def _boom(*_args, **_kwargs):
    raise RuntimeError("metrics broke")


def test_a_clock_that_raises_does_not_stop_the_merge_and_leaves_the_wait_unverified(dependent, monkeypatch):
    fake = dependent(auto_merge=True)
    monkeypatch.setattr(squad_flow, "clock", _boom)
    run_tick()
    assert fake.merges == [101, 102]  # both approved, both merged, in order
    waiting = _worker_metrics(2)
    assert waiting["dependency_wait_s"] is None and waiting["proof_kind"]["dependency_wait"] == "UNVERIFIED"
    entry = read_json(config.STATUS)["squads"][REPO]
    assert entry["merged"] == [101, 102] and entry["approved"] == [101, 102]


def test_a_clock_that_raises_only_at_the_merge_still_records_the_merge(dependent, monkeypatch):
    fake = dependent(auto_merge=True)
    ticks = iter([100.0, 100.0])  # the two approvals read the clock; every later read (the merges) raises

    def clock():
        try:
            return next(ticks)
        except StopIteration:
            raise RuntimeError("clock gone") from None
    monkeypatch.setattr(squad_flow, "clock", clock)
    run_tick()
    assert fake.merges == [101, 102]
    assert read_json(config.STATUS)["squads"][REPO]["merged"] == [101, 102]  # the merge was not lost for want of an instant
    assert _worker_metrics(2)["unverified"]["dependency_wait_s"] == "dependency_merge_not_observed: #1"


def test_a_task_record_that_raises_is_unverified_and_the_tick_still_finishes_every_repo(dependent, monkeypatch):
    fake = dependent(auto_merge=True)
    monkeypatch.setattr(squad_metrics, "task_record", _boom)
    run_tick()
    assert fake.merges == [101, 102]
    for number in (1, 2):
        record = _worker_metrics(number)
        assert record["proof_kind"] == {"escalations": "UNVERIFIED", "dependency_wait": "UNVERIFIED", "final_outcome": "UNVERIFIED"}
        assert record["unverified"] == {"escalations": "metrics_error", "dependency_wait_s": "metrics_error",
                                        "final_outcome": "metrics_error"}
    metrics = read_json(config.STATUS)["squads"][REPO]["metrics"]
    assert (metrics["tasks"], metrics["escalation_n"], metrics["escalation_unverified"]) == (2, 0, 2)


def test_a_summary_that_raises_leaves_a_marked_block_and_the_status_is_still_written(dependent, monkeypatch):
    fake = dependent(auto_merge=True)
    monkeypatch.setattr(squad_metrics, "summarize_records", _boom)
    run_tick()
    assert fake.merges == [101, 102]
    entry = read_json(config.STATUS)["squads"][REPO]
    assert entry["metrics"]["unverified"] == "metrics_error" and len(entry["task_metrics"]) == 2


# --- the reason of a failed step is a short code, whatever turbo printed ---


class _Planned:
    def __init__(self, ok=True, reason_code="ok"):
        self._ok, self.reason_code = ok, reason_code

    def is_ok(self):
        return self._ok


@pytest.mark.parametrize("planned,label,status,expected", [
    (_Planned(False, "bad_plan"), "", "failed", "bad_plan"),
    (_Planned(False, "quota_exhausted"), "", "failed", "quota_exhausted"),
    (_Planned(), "MEASURED|verify_failed: `pytest`", "failed", "verify_failed"),
    (_Planned(), "UNVERIFIED", "blocked", "apply_blocked"),
    (_Planned(), "UNVERIFIED", "failed", "apply_failed"),
    (_Planned(), "UNVERIFIED", "ok", "verify_not_reported"),  # turbo applied, but no passing verify came back
    (_Planned(), "UNVERIFIED", "/home/me/secret token=abc", "apply_unknown"),
    (_Planned(), "UNVERIFIED", "x" * 500, "apply_unknown"),
    (_Planned(), "UNVERIFIED", ["failed"], "apply_unknown"),
    (_Planned(), "UNVERIFIED", None, "apply_unknown"),
])
def test_the_failure_reason_is_an_enum_like_code(planned, label, status, expected):
    assert host_mode._failure_reason(planned, label, status) == expected
