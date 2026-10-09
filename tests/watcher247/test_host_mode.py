"""Host mode of the 24/7 watcher (#1429): an exec CLI plans, `turbo --apply -` applies, openrouter is opt-in.

No real model CLI runs: `claude` is a stub script on PATH, and proc.run is the FakeRun of fakes.py.
"""
from __future__ import annotations

import json
import os
import stat
import textwrap

import pytest

from simplicio_loop import escalation, executor_select, model_roles
from simplicio_loop.watcher247 import config, host_mode, proc, sandbox

from .fakes import FakeRun, baseline, issue, pr_row, read_json, run_tick

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


class HostRun(FakeRun):
    """FakeRun whose `turbo --apply -` answers the given documents in order (the last one repeats)."""

    def __init__(self, issues, applies=(OK,), **kwargs):
        super().__init__(issues, **kwargs)
        self.applies = list(applies)
        self.turbo_stdin = []
        self.turbo_env = []

    async def __call__(self, argv, timeout=120, cwd=None, stdin=None, env=None):
        if list(argv[:2]) == ["simplicio-loop", "turbo"]:
            await super().__call__(argv, timeout, cwd, stdin, env)
            self.turbo_stdin.append(stdin)
            self.turbo_env.append(env)
            document = self.applies.pop(0) if len(self.applies) > 1 else self.applies[0]
            return proc.Result(0 if document["status"] == "ok" else 1, json.dumps(document))
        return await super().__call__(argv, timeout, cwd, stdin, env)


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
    """A pre-cloned target repo with a pytest marker, so turbo gets --verify."""
    dest = config.WORK / REPO
    (dest / ".git").mkdir(parents=True)
    (dest / "pytest.ini").write_text("[pytest]\n")
    return dest


def step_roles(dest):
    """(role, model, effort) of every step in the execution-report the watcher wrote."""
    report = read_json(dest / REPORTS)
    assert report["schema"] == "simplicio.execution-report/v1"
    return [(t["role"], t["model"], t["effort"]) for t in report["tasks"]]


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
    assert len(planner) == 1 and planner[0][1] == dest and planner[0][2] == config.ROOT
    assert env_values_has_sandboxed(cli_dir)  # the CLI really ran under the wrapper
    assert [w[0][0] for w in wrapped] == ["claude", "simplicio-loop"]  # planner, then the apply
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


def test_plan_goes_to_turbo_stdin_and_dev_cli_applies(env, cli_dir):
    fake = env(HostRun({REPO: [issue(3, "Add x")]}))
    baseline()
    dest = checkout()
    run_tick()
    assert fake.turbo_argv[0] == ["simplicio-loop", "turbo", "--repo", str(dest), "--apply", "-",
                                  "--verify", "python3 -m pytest -q"]
    assert json.loads(fake.turbo_stdin[0]) == PLAN
    (call,) = planner_calls(cli_dir)
    assert flag(call, "--model") == resolved("planning")["model"]
    assert flag(call, "--permission-mode") == "plan"  # the planner cannot write
    assert "Issue #3: Add x" in call[1]
    assert "MEASURED|verify_passed" in fake.ran("gh", "pr", "create")[0][-1]
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
    assert [r for r, _, _ in step_roles(dest)] == ["planning", "planning"]  # planning is the top of the ladder


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
    assert fake.ran("git", "checkout", "-B", "loop/issue-7", "origin/loop/issue-7")
    pushes = fake.ran("git", "push")
    assert pushes == [["git", "push", "-u", "origin", "loop/issue-7"]]  # same branch, never forced
    assert fake.ran("gh", "pr", "create") == [] and fake.ran("gh", "pr", "merge") == []
    assert fake.ran("gh", "pr", "close") == []
    assert [r for r, _, _ in step_roles(dest)] == ["coordination", "planning"]


def test_execution_report_has_role_model_and_effort_per_step(env, cli_dir):
    env(review_fixture([BAD, OK]))
    baseline(f"{REPO}#7")
    dest = checkout()
    run_tick()
    assert step_roles(dest) == [
        ("coordination", resolved("coordination")["model"], resolved("coordination")["effort"]),
        ("planning", resolved("planning")["model"], resolved("planning")["effort"]),
    ]
    report = read_json(dest / REPORTS)
    assert [t["outcome"] for t in report["tasks"]] == ["FAIL", "COMPLETE"]
    assert all(t["tokens"]["source"] == "absent" for t in report["tasks"])  # UNVERIFIED, never invented
