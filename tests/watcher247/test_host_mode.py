"""Host mode of the 24/7 watcher (#1429): an exec CLI plans, `turbo --apply -` applies, openrouter is opt-in.

No real model CLI runs: `claude` is a stub script on PATH, and proc.run is the FakeRun of fakes.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
import textwrap
from pathlib import Path

import pytest

from simplicio_loop import escalation, execution_report, executor_select, model_roles
from simplicio_loop.watcher247 import config, host_mode, proc, sandbox

from .fakes import FakeRun, baseline, issue, pr_row, read_json, run_tick
from simplicio_loop.watcher247.worktrees import state_home

REPO = "simplicio-a"
PLAN = {"operations": [{"path": "app.py", "find": "", "replace": "print('x')\n"}]}
OK = {"schema": "simplicio.turbo-run/v1", "status": "ok", "verify": {"passed": True}}
BAD = {"schema": "simplicio.turbo-run/v1", "status": "failed",
       "verify": {"passed": False, "output_tail": "FAILED test_x - assert 0"}}
REPORTS = ".simplicio-loop/runtime/execution-reports/latest.json"

STUB = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    d = os.path.dirname(os.path.abspath(__file__))
    if sys.argv[1:2] == ["auth"]:
        sys.exit(1 if os.environ.get("FAKE_CLI_LOGGED_OUT") else 0)
    with open(d + "/calls.jsonl", "a") as handle:
        handle.write(json.dumps(sys.argv[1:]) + "\\n")
    with open(d + "/env.jsonl", "a") as handle:
        handle.write(json.dumps(sorted(os.environ)) + "\\n")
    print(json.dumps({"result": json.dumps(%s)}))
''') % repr(PLAN)


RUN_ID = "turbo-20261008T000000-abc123"
MAP_SLICE = "MAP-SLICE-for-app.py"


class HostRun(FakeRun):
    """FakeRun for turbo's two host steps.

    Step 1 (`turbo --task T`) answers a needs_plan request; step 2 (`turbo --apply -`) answers the given documents in
    order (the last one repeats). With ``reports`` the apply writes its execution-report as turbo does.
    """

    def __init__(self, issues, applies=(OK,), request=None, reports=False, **kwargs):
        super().__init__(issues, **kwargs)
        self.applies = list(applies)
        self.request = request
        self.reports = reports
        self.requests = []  # (argv, env, planner calls already made when it ran)
        self.turbo_stdin = []
        self.turbo_env = []

    def _planner_calls_so_far(self):
        path = Path(os.environ["FAKE_CLI_DIR"]) / "calls.jsonl"
        return len(path.read_text().splitlines()) if path.exists() else 0

    async def __call__(self, argv, timeout=120, cwd=None, stdin=None, env=None):
        if list(argv[:2]) != ["simplicio-loop", "turbo"]:
            return await super().__call__(argv, timeout, cwd, stdin, env)
        if "--apply" not in argv and "--provider" not in argv:
            self.calls.append(list(argv))
            self.requests.append((list(argv), env, self._planner_calls_so_far()))
            if self.request is not None:
                return proc.Result(2, json.dumps(self.request))
            task = argv[argv.index("--task") + 1]
            document = {"schema": "simplicio.turbo-request/v1", "status": "needs_plan", "mode": "host",
                        "run_id": RUN_ID, "tasks": [task], "map": {"slice": MAP_SLICE},
                        "files": {"app.py": "x = 1\n"}, "format": {"operations": []}, "rules": "rules",
                        "apply": f"simplicio-loop turbo --apply - --run-id {RUN_ID}"}
            return proc.Result(0, json.dumps(document))
        await super().__call__(argv, timeout, cwd, stdin, env)
        self.turbo_stdin.append(stdin)
        self.turbo_env.append(env)
        document = dict(self.applies.pop(0) if len(self.applies) > 1 else self.applies[0])
        if self.reports and "--run-id" in argv:
            document["execution_report"] = self._write_turbo_report(Path(cwd), argv[argv.index("--run-id") + 1])
        return proc.Result(0 if document["status"] == "ok" else 1, json.dumps(document))

    @staticmethod
    def _write_turbo_report(dest, run_id):
        """What turbo's TurboRun.finish leaves: one report named after the run, with a single turbo task."""
        report = execution_report.new_report(dest, execution_profile="turbo-host")
        report["run_id"] = run_id
        execution_report.record_task(report, task_id=run_id, title="turbo host: 1 task(s)", outcome="COMPLETE",
                                     operators=["simplicio-mapper", "simplicio-dev-cli"])
        return execution_report.write_report(dest, report).relative_to(dest).as_posix()


@pytest.fixture
def cli_dir(env, monkeypatch, tmp_path):
    """The default executor: no SIMPLICIO_EXECUTOR, an OPENROUTER_API_KEY in the env, a stub `claude` on PATH."""
    monkeypatch.delenv("SIMPLICIO_EXECUTOR", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-be-used")
    monkeypatch.setenv("SIMPLICIO_EXEC_FAMILIES", "claude")
    monkeypatch.delenv("SIMPLICIO_247_ATTEMPT_CEILING_ISSUE", raising=False)
    monkeypatch.delenv("FAKE_CLI_LOGGED_OUT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # no real credential file
    (tmp_path / "home").mkdir()
    path = tmp_path / "fake-cli"
    path.mkdir()
    claude = path / "claude"
    claude.write_text(STUB)
    claude.chmod(claude.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("FAKE_CLI_DIR", str(path))
    monkeypatch.setenv("PATH", f"{path}:{os.environ['PATH']}")
    # env patches shutil.which to None (no bwrap); only the stub CLI is found here
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary, *a, **k: str(claude) if binary == "claude" else None)
    return path


def planner_calls(cli_dir):
    path = cli_dir / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def flag(call, name):
    return call[call.index(name) + 1]


def resolved(role):
    return model_roles.resolve("claude", role)


def checkout():
    """A pre-cloned target repo (so ensure_clone does not clone)."""
    dest = config.WORK / REPO
    (dest / ".git").mkdir(parents=True)
    return dest


def step_roles(dest, issue_num=7):
    """(role, model, effort) of every step in the execution-report the watcher wrote."""
    state_path = state_home(REPO, issue_num)
    report = read_json(state_path / REPORTS)
    assert report["schema"] == "simplicio.execution-report/v1"
    return [(t["role"], t["model"], t["effort"]) for t in report["tasks"] if "role" in t]


def review_fixture(applies):
    review = {"author": {"login": "reviewer"}, "state": "CHANGES_REQUESTED", "body": "troque o retorno para dict"}
    return HostRun(
        {REPO: [issue(7)]}, applies,
        prs=[pr_row(9, "loop/issue-7", review="CHANGES_REQUESTED")],
        pr_views={9: {"reviews": [review], "files": [{"path": "app.py"}], "statusCheckRollup": []}},
    )


def test_default_executor_is_exec_never_openrouter(env, cli_dir):
    assert executor_select.select_mode({}) == "exec"
    assert executor_select.select_mode({"OPENROUTER_API_KEY": "k"}) == "exec"  # a key alone selects nothing
    fake = env(HostRun({REPO: [issue(1)]}))
    baseline()
    run_tick()
    argv = fake.turbo_argv[0]
    assert "--provider" not in argv and "openrouter" not in " ".join(argv)
    assert "OPENROUTER_API_KEY" not in (fake.turbo_env[0] or {})
    assert len(planner_calls(cli_dir)) == 1


def test_openrouter_only_when_explicitly_selected_with_a_key(env, cli_dir, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTOR", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    fake = env(HostRun({REPO: [issue(1)]}))
    baseline()
    run_tick()
    assert fake.turbo_argv == []
    assert read_json(config.STATUS)["reason_code"] == "executor_invalid"
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    run_tick()
    assert fake.turbo_argv[0][fake.turbo_argv[0].index("--provider") + 1] == "openrouter"
    assert planner_calls(cli_dir) == []


def test_planner_runs_through_the_sandbox_wrapper(env, cli_dir, monkeypatch):
    wrapped = []

    def fake_wrap(argv, *, clone, state_dir, **_):
        wrapped.append((list(argv), clone, state_dir))
        return ["/usr/bin/env", "SANDBOXED=1", *argv] if argv[0] == "claude" else list(argv)

    monkeypatch.setattr(sandbox, "wrap", fake_wrap)
    fake = env(HostRun({REPO: [issue(1)]}))
    baseline()
    dest = checkout()
    run_tick()
    planner = [w for w in wrapped if w[0][0] == "claude"]
    worktree = config.WORK / f"{REPO}.wt" / "1"
    assert len(planner) == 1 and planner[0][1] == worktree and planner[0][2] == config.ROOT
    assert env_values_has_sandboxed(cli_dir)  # the CLI really ran under the wrapper
    assert [w[0][0] for w in wrapped] == ["simplicio-loop", "claude", "simplicio-loop"]  # request, planner, apply
    assert fake.turbo_argv


def test_watcher_keeps_the_planner_config_in_the_bound_state_dir(env, cli_dir, monkeypatch):
    seen = []
    real = host_mode.exec_planner.run_planner_with_fallback

    async def spy(*args, **kwargs):
        seen.append(kwargs.get("config_dir"))
        return await real(*args, **kwargs)

    monkeypatch.setattr(host_mode.exec_planner, "run_planner_with_fallback", spy)
    env(HostRun({REPO: [issue(1)]}))
    baseline()
    checkout()
    run_tick()
    assert seen == [config.ROOT / "opencode"]  # sandbox.wrap binds state_dir; /tmp is a tmpfs inside it


def env_keys(cli_dir):
    path = cli_dir / "env.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def env_values_has_sandboxed(cli_dir):
    return any("SANDBOXED" in keys for keys in env_keys(cli_dir))


def test_planner_env_is_scrubbed(env, cli_dir, monkeypatch):
    for name in ("AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "DATABASE_URL"):
        monkeypatch.setenv(name, "secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-needs-this")
    env(HostRun({REPO: [issue(1)]}))
    baseline()
    checkout()
    run_tick()
    (keys,) = env_keys(cli_dir)
    for name in ("OPENROUTER_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "DATABASE_URL", "FAKE_CLI_DIR"):
        assert name not in keys
    assert "ANTHROPIC_API_KEY" in keys and "HOME" in keys and "PATH" in keys  # what that CLI needs


def test_the_github_token_reaches_no_sandboxed_step(env, cli_dir, monkeypatch):
    """GH_TOKEN stays in the service env for gh and git (outside the sandbox). The planner CLI, `turbo` (request) and
    `turbo --apply` run inside sandbox.wrap with scrubbed_env, which never carries it."""
    secret = "ghp_FAKEmustnotleak000000000000000000"
    monkeypatch.setenv("GH_TOKEN", secret)
    monkeypatch.setenv("GITHUB_TOKEN", secret)
    fake = env(HostRun({REPO: [issue(1)]}))
    baseline()
    checkout()
    run_tick()
    (planner_keys,) = env_keys(cli_dir)
    assert "GH_TOKEN" not in planner_keys and "GITHUB_TOKEN" not in planner_keys
    turbo_envs = [request[1] for request in fake.requests] + fake.turbo_env
    assert len(turbo_envs) == 2  # the request step and the apply step both ran
    for turbo_env in turbo_envs:
        assert turbo_env is not None  # an explicit env, never the inherited one
        assert "GH_TOKEN" not in turbo_env and "GITHUB_TOKEN" not in turbo_env
        assert secret not in turbo_env.values()


def test_plan_goes_to_turbo_stdin_and_dev_cli_applies(env, cli_dir):
    targeted = "python3 -m pytest -q tests/x.py"  # the `verify` of the repo's loop.toml, exactly
    fake = env(HostRun({REPO: [issue(3, "Add x")]}, loop_toml={REPO: f'enabled = true\nverify = "{targeted}"\n'}))
    baseline()
    dest = checkout()
    run_tick()
    worktree = config.WORK / f"{REPO}.wt" / "3"
    assert fake.turbo_argv[0] == ["simplicio-loop", "turbo", "--repo", str(worktree), "--apply", "-",
                                  "--run-id", RUN_ID, "--leave-open", "--verify", targeted]
    assert json.loads(fake.turbo_stdin[0]) == PLAN
    (call,) = planner_calls(cli_dir)
    assert flag(call, "--model") == resolved("execution")["model"]
    assert flag(call, "--permission-mode") == "plan"  # the planner cannot write
    assert "Issue #3: Add x" in call[1]
    assert f"MEASURED|verify_passed: `{targeted}`" in fake.ran("gh", "pr", "create")[0][-1]
    assert read_json(config.CLAIMS)[f"{REPO}#3"]["status"] == "done"


def test_verify_failure_replans_with_the_failure_output(env, cli_dir):
    fake = env(HostRun({REPO: [issue(1)]}, [BAD, OK]))
    baseline()
    dest = checkout()
    run_tick()
    first, second = planner_calls(cli_dir)
    assert "FAILED test_x" not in first[1] and "FAILED test_x - assert 0" in second[1]
    assert len(fake.turbo_argv) == 2
    assert fake.ran("git", "reset", "-q", "--hard", "HEAD")  # the failed edits are dropped before the replan
    assert read_json(config.CLAIMS)[f"{REPO}#1"]["status"] == "done"
    assert [r for r, _, _ in step_roles(dest, 1)] == ["execution", "execution"]  # a squad worker starts at execution (#1505)


def test_next_role_order_is_execution_twice_then_up(tmp_path):
    ladder = escalation.load_escalation_state(tmp_path, 5, "claude")
    roles = []
    for _ in range(5):
        roles.append(ladder.current_role())
        ladder.record_attempt("failed")
        host_mode.next_role(ladder)
    assert roles == ["execution", "execution", "coordination", "planning", "planning"]


def test_ceiling_stops_the_escalation(env, cli_dir, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_ATTEMPT_CEILING_ISSUE", "2")
    fake = env(HostRun({REPO: [issue(1)]}, [BAD]))
    baseline()
    checkout()
    run_tick()
    assert len(planner_calls(cli_dir)) == 2 and len(fake.turbo_argv) == 2
    claim = read_json(config.CLAIMS)[f"{REPO}#1"]
    assert claim["status"] == "retry" and "convergence stop" in claim["error"]  # the policy stops it at the ceiling
    assert fake.ran("gh", "pr", "create") == []


def test_login_missing_skips_the_tick(env, cli_dir, monkeypatch):
    monkeypatch.setenv("FAKE_CLI_LOGGED_OUT", "1")
    fake = env(HostRun({REPO: [issue(1)]}))
    baseline()
    run_tick()
    status = read_json(config.STATUS)
    assert status["phase"] == "blocked" and status["reason_code"] == "login_missing:claude"
    assert fake.calls == [] and planner_calls(cli_dir) == []
    assert not config.CLAIMS.exists()


def test_review_fix_is_pushed_to_the_same_branch_with_role_coordination(env, cli_dir):
    fake = env(review_fixture([BAD, OK]))
    baseline(f"{REPO}#7")  # the issue is old; the review is new work for it
    dest = checkout()
    run_tick()
    first, second = planner_calls(cli_dir)
    assert flag(first, "--model") == resolved("coordination")["model"]
    assert flag(second, "--model") == resolved("planning")["model"]  # coordination failed once: up the ladder
    assert "troque o retorno para dict" in first[1]
    # the fix starts from the open PR head, on the same branch, in the item's own worktree: the whole argv
    assert fake.ran("git", "worktree", "add") == [
        ["git", "worktree", "add", "-q", "-B", "loop/issue-7", str(config.WORK / f"{REPO}.wt" / "7"), "origin/loop/issue-7"]]
    pushes = fake.ran("git", "push")
    assert pushes == [["git", "push", "-u", "origin", "loop/issue-7"]]  # same branch, never forced
    assert fake.ran("gh", "pr", "create") == [] and fake.ran("gh", "pr", "merge") == []
    assert fake.ran("gh", "pr", "close") == []
    assert [r for r, _, _ in step_roles(dest, 7)] == ["coordination", "planning"]


def test_execution_report_has_role_model_and_effort_per_step(env, cli_dir):
    env(review_fixture([BAD, OK]))
    baseline(f"{REPO}#7")
    dest = checkout()
    run_tick()
    assert step_roles(dest, 7) == [
        ("coordination", resolved("coordination")["model"], resolved("coordination")["effort"]),
        ("planning", resolved("planning")["model"], resolved("planning")["effort"]),
    ]
    report = read_json(state_home(REPO, 7) / REPORTS)
    assert [t["outcome"] for t in report["tasks"]] == ["FAIL", "COMPLETE"]
    assert all(t["tokens"]["source"] == "absent" for t in report["tasks"])  # UNVERIFIED, never invented


# --- turbo's two host steps (#1469): the request (map) first, then the apply that continues the same run ---


def test_step_1_runs_before_the_planner_in_the_sandbox_with_the_scrubbed_env(env, cli_dir):
    fake = env(HostRun({REPO: [issue(3, "Add x")]}))
    baseline()
    dest = checkout()
    run_tick()
    ((argv, step_env, planner_calls_before),) = fake.requests
    worktree_path = config.WORK / f"{REPO}.wt" / "3"
    assert argv[:6] == ["simplicio-loop", "turbo", "--repo", str(worktree_path), "--task", argv[5]] and len(argv) == 8
    assert argv[6] == "--run-id" and argv[7].startswith("turbo-"), "turbo continues the run the watcher opened at intake"
    assert "Issue #3: Add x" in argv[5]  # the guarded task, not a bare title
    assert planner_calls_before == 0, "turbo's request (mapper orient) must run before the planner"
    assert "OPENROUTER_API_KEY" not in step_env and "ANTHROPIC_API_KEY" not in step_env
    assert fake.calls.index(argv) < fake.calls.index(fake.turbo_argv[0])  # step 1 before step 2


def test_planner_prompt_is_the_turbo_request_with_the_map_slice(env, cli_dir):
    env(HostRun({REPO: [issue(3, "Add x")]}))
    baseline()
    checkout()
    run_tick()
    (call,) = planner_calls(cli_dir)
    assert MAP_SLICE in call[1] and "Issue #3: Add x" in call[1]
    assert RUN_ID in call[1] and "x = 1" in call[1]  # the request: run, current file text
    assert flag(call, "--permission-mode") == "plan"


def test_step_2_continues_the_run_and_one_report_carries_run_id_and_roles(env, cli_dir):
    fake = env(review_fixture([BAD, OK]))
    fake.reports = True
    baseline(f"{REPO}#7")
    dest = checkout()
    run_tick()
    assert len(fake.requests) == 1  # one orient per work item, whatever the retries
    for argv in fake.turbo_argv:
        assert argv[argv.index("--run-id") + 1] == RUN_ID
    report = read_json(state_home(REPO, 7) / REPORTS)
    assert report["run_id"] == RUN_ID
    assert read_json(state_home(REPO, 7) / ".simplicio-loop/runtime/execution-reports" / f"{RUN_ID}.json") == report
    roles = [t for t in report["tasks"] if "role" in t]
    assert [t["role"] for t in roles] == ["coordination", "planning"]
    assert [t["outcome"] for t in roles] == ["FAIL", "COMPLETE"]
    assert [t["task_id"] for t in report["tasks"] if "role" not in t] == [RUN_ID, RUN_ID]  # turbo's own tasks
    assert "simplicio-mapper" in report["operators_used"] and "exec-planner" in report["operators_used"]


def test_escalation_retry_reuses_the_request_plus_the_failure_output(env, cli_dir):
    fake = env(HostRun({REPO: [issue(1)]}, [BAD, OK]))
    baseline()
    checkout()
    run_tick()
    first, second = planner_calls(cli_dir)
    assert len(fake.requests) == 1
    assert MAP_SLICE in first[1] and MAP_SLICE in second[1]  # the same request both times
    assert "FAILED test_x" not in first[1] and "FAILED test_x - assert 0" in second[1]
    assert [a[a.index("--run-id") + 1] for a in fake.turbo_argv] == [RUN_ID, RUN_ID]


def test_blocked_request_stops_before_any_planner_call(env, cli_dir):
    blocked = {"schema": "simplicio.turbo-run/v1", "status": "blocked", "reason_code": "turbo_engine_error",
               "detail": "mapper unavailable"}
    fake = env(HostRun({REPO: [issue(1)]}, request=blocked))
    baseline()
    checkout()
    run_tick()
    assert planner_calls(cli_dir) == [] and fake.turbo_argv == []
    claim = read_json(config.CLAIMS)[f"{REPO}#1"]
    assert claim["status"] == "retry" and "mapper unavailable" in claim["error"]


# --- the kanban run the watcher opened at intake is always closed (#1469) --------------------------------------

def _closed_runs(monkeypatch):
    from simplicio_loop.watcher247 import events
    seen, real = [], events.close_run

    def record(dest, run_id, status, pr_url=None):
        seen.append((status, pr_url))
        return real(dest, run_id, status, pr_url=pr_url)

    monkeypatch.setattr(events, "close_run", record)
    return seen


def _executor_raises(monkeypatch, exc):
    async def boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr(host_mode, "run_exec", boom)


def test_a_pr_closes_the_run_ok_with_the_pr_url(env, cli_dir, monkeypatch):
    seen = _closed_runs(monkeypatch)
    env(HostRun({REPO: [issue(3)]}))
    baseline()
    checkout()
    run_tick()
    assert seen == [("ok", "https://github.com/simpletibr/simplicio-a/pull/9")]


def test_no_diff_closes_the_run_blocked_never_done(env, cli_dir, monkeypatch):
    seen = _closed_runs(monkeypatch)
    env(HostRun({REPO: [issue(3)]}, diff=False))
    baseline()
    checkout()
    run_tick()
    assert seen == [("blocked", None)], "no PR was opened: the run must not claim done"


def test_a_failed_attempt_closes_the_run_failed(env, cli_dir, monkeypatch):
    seen = _closed_runs(monkeypatch)
    _executor_raises(monkeypatch, RuntimeError("boom"))
    env(HostRun({REPO: [issue(3)]}))
    baseline()
    checkout()
    run_tick()
    assert seen == [("failed", None)]


def test_a_blocked_point_closes_the_run_blocked(env, cli_dir, monkeypatch):
    from simplicio_loop.watcher247.points import registry
    seen = _closed_runs(monkeypatch)
    _executor_raises(monkeypatch, registry.PointBlocked("pr", "gate", "why", []))
    env(HostRun({REPO: [issue(3)]}))
    baseline()
    checkout()
    run_tick()
    assert seen == [("blocked", None)]


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit, asyncio.CancelledError])
def test_the_run_is_closed_and_the_interrupt_is_not_swallowed(env, cli_dir, monkeypatch, exc):
    seen = _closed_runs(monkeypatch)
    _executor_raises(monkeypatch, exc())
    env(HostRun({REPO: [issue(3)]}))
    baseline()
    checkout()
    with pytest.raises(exc):
        run_tick()
    assert seen == [("failed", None)]


def test_a_writer_that_raises_never_breaks_the_tick(env, cli_dir, monkeypatch):
    from simplicio_loop.watcher247 import events

    class Broken:
        def __init__(self, *args, **kwargs):
            raise OSError("disk full")

    monkeypatch.setattr(events, "TurboRun", Broken)
    fake = env(HostRun({REPO: [issue(3)]}))
    baseline()
    checkout()
    run_tick()
    assert read_json(config.CLAIMS)[f"{REPO}#3"]["status"] == "done"
    assert fake.ran("gh", "pr", "create")
