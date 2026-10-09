"""Escalation rate and dependency wait recorded by the squads tick (#1549): MEASURED values only.

The escalation comes from the worker's real steps (exec mode, a stub planner CLI and the FakeRun of turbo); the dependency
wait comes from two instants the flow observes (the squad approves the PR, the dependency's merge succeeds), read from a
fake clock so the expected number is exact.
"""
from __future__ import annotations

import json

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
    return {"files": [{"path": f"src/m{number}/app.py"}], "headRefOid": f"oid{number}",
            "commits": [{"oid": f"oid{number}", "committedDate": "2026-10-01T00:00:00Z", "messageHeadline": "loop: x"}],
            "comments": [{"id": number, "createdAt": "2026-10-02T00:00:00Z", "body": "APROVADO PELO SQUAD\n",
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
    env(FakeRun({REPO: [issue(1)]}, verify_pass=True, distinct_prs=True, pr_views={101: _view(1)}))
    baseline()
    run_tick()
    record = _worker_metrics(1)
    assert record["escalations"] is None and record["initial_role"] is None and record["final_role"] is None
    assert record["proof_kind"]["escalations"] == "UNVERIFIED" and record["unverified"]["escalations"] == "no_steps_recorded"
    metrics = read_json(config.STATUS)["squads"][REPO]["metrics"]
    assert (metrics["escalation_n"], metrics["escalation_unverified"], metrics["escalation_rate"]) == (0, 1, None)


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
    """Two issues of one repo, #2 depends on #1; a pre-cloned repo with tests; PRs 101 and 102; a fake clock."""
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    clock = FakeClock()
    monkeypatch.setattr(squad_flow, "clock", clock)
    clone = config.WORK / REPO
    (clone / ".git").mkdir(parents=True)
    (clone / "pytest.ini").write_text("[pytest]\n")

    def make(auto_merge: bool):
        if auto_merge:
            monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
        else:
            monkeypatch.delenv("SIMPLICIO_247_AUTO_MERGE", raising=False)
        rows = [issue(1, "Task 1", body="Ajustar `src/m1/app.py` para o fluxo do watcher seguir o contrato descrito abaixo."),
                issue(2, "Task 2", body="Ajustar `src/m2/app.py` para o fluxo do watcher seguir o contrato descrito abaixo."
                                        " Depende de #1.")]
        fake = env(TimedRun(clock, {REPO: rows}, verify_pass=True, distinct_prs=True,
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
        assert record["proof_kind"] == {"escalations": "UNVERIFIED", "dependency_wait": "UNVERIFIED"}
        assert record["unverified"] == {"escalations": "metrics_error", "dependency_wait_s": "metrics_error"}
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
