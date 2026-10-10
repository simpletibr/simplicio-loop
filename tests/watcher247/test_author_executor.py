"""The author flow as the second executor of the 24/7 watcher (SIMPLICIO_247_EXECUTOR=author, #1669).

No real CLI: run_author is a spy, or (token test) the real run_author over a fake `claude` runner.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from simplicio_loop import author_flow, execution_report
from simplicio_loop.watcher247 import author_executor, config, host_mode, points, proc, state
from simplicio_loop.watcher247.__main__ import main as watcher_main

from .fakes import FIXED, PR_URL, FakeRun, baseline, issue, read_json, run_tick, write_json

OK = author_flow.AuthorResult("ok", 2, "sid", ["app.py"], [], {"input_tokens": 10, "output_tokens": 5, "measured_rounds": 2}, "ok")


def failed(reason="verify_failed", rounds=3, usage=None, kinds=("verify_failed",)):
    return author_flow.AuthorResult("failed", rounds, "sid", ["app.py"], [{"kind": k, "detail": "x"} for k in kinds], usage, reason)


def pick(*families):
    async def choose(environ=None):
        return host_mode.Executor("exec", families)
    return choose


class Spy:
    """Stands for author_flow.run_author: records the call and what the delivery had done by then."""

    def __init__(self):
        self.answer = OK
        self.calls = []
        self.progress = []  # (commits, pushes, PRs) seen while the author ran
        self.fake = None

    async def __call__(self, task_text, worktree, **kwargs):
        self.calls.append((task_text, Path(worktree), kwargs))
        if self.fake is not None:
            self.progress.append(tuple(len(self.fake.ran(*prefix)) for prefix in (("git", "commit"), ("git", "push"), ("gh", "pr", "create"))))
        return self.answer


@pytest.fixture
def author(env, monkeypatch):
    """The author executor on, claude the usable family, run_author replaced by a spy."""
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "author")
    monkeypatch.delenv(author_executor.ROUNDS_ENV, raising=False)
    monkeypatch.setattr(host_mode, "choose", pick("claude"))
    spy = Spy()
    monkeypatch.setattr(author_flow, "run_author", spy)

    def use(fake):
        spy.fake = env(fake)
        return spy.fake

    spy.use = use
    return spy


def test_author_ok_opens_the_pr_with_the_same_delivery_path(author, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_PR_DRAFT", "1")
    fake = author.use(FakeRun({"simplicio-a": [issue(7, "Add x")]}))
    baseline()
    run_tick()
    assert fake.turbo_argv == [], "the plan flow (turbo) does not run"
    assert len(author.calls) == 1
    task_text, worktree, kwargs = author.calls[0]
    assert worktree == config.WORK / "simplicio-a.wt" / "7" and worktree != config.WORK / "simplicio-a"
    assert "Issue #7: Add x" in task_text
    assert kwargs["family"] == "claude" and kwargs["verify"] == "python3 -m pytest -q" and kwargs["rounds"] == 3
    assert fake.ran("git", "commit")[0][3] == "loop: #7 Add x\n\nParte de #7\n"
    assert fake.ran("git", "push", "-u", "origin", "loop/issue-7")
    pr = fake.ran("gh", "pr", "create")[0]
    assert pr[pr.index("--body") + 1].endswith("Parte de #7\n") and "--draft" in pr
    assert "executor author" in pr[pr.index("--body") + 1]
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "done" and claim["pr"] == PR_URL
    assert claim["verify"] == "MEASURED|verify_passed: `python3 -m pytest -q`" and claim["executor"] == "author"
    assert claim["rounds"] == 2 and claim["usage"] == OK.usage
    assert [s["role"] for s in claim["steps"]] == ["coordination"] and claim["steps"][0]["outcome"] == "ok"
    assert claim["steps"][0]["family"] == "claude" and claim["steps"][0]["model"] and claim["steps"][0]["effort"]
    assert read_json(config.BUDGET)["prs"] == 1 and read_json(config.BUDGET)["model_calls"] == 2


def test_nothing_is_committed_or_pushed_before_author_returns(author):
    fake = author.use(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    assert author.progress == [(0, 0, 0)]
    assert len(fake.ran("git", "commit")) == 1


def test_the_report_tokens_are_measured_or_absent(tmp_path):
    steps, report = author_executor.report_of(tmp_path, {"number": 7}, "simplicio-a", author_flow.AuthorResult("ok", 2, "s", ["a"], [], {"input_tokens": 10, "output_tokens": 5, "measured_rounds": 2}, "ok"),
                                              "claude", 12, None)
    task = report["tasks"][-1]
    assert task["tokens"]["tokens_in"] == 10 and task["tokens"]["tokens_out"] == 5 and task["tokens"]["source"] == "cli_measured"
    assert task["role"] == "coordination" and task["rounds"] == 2 and report["status"] == "COMPLETE"
    assert steps[0]["outcome"] == "ok" and "reason" not in steps[0]
    steps, report = author_executor.report_of(tmp_path, {"number": 7}, "simplicio-a", failed("cli_error", 1, None, ("cli_error",)), "claude", 12, "run-1")
    task = report["tasks"][-1]
    assert task["tokens"]["tokens_in"] is None and task["tokens"]["source"] == "absent"
    assert report["status"] == "FAILED" and report["run_id"] == "run-1"
    assert steps[0]["outcome"] == "failed" and steps[0]["reason"] == "cli_error"


def test_author_failed_releases_the_claim_with_the_reason_and_opens_no_pr(author, capsys):
    author.answer = failed("verify_failed", rounds=3, usage={"input_tokens": 7, "measured_rounds": 3}, kinds=("verify_failed", "protected_path"))
    fake = author.use(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#5"]
    assert claim["status"] == "retry" and claim["attempts"] == 1 and claim["reason_code"] == "verify_failed"
    assert "rounds=3" in claim["error"] and "protected_path" in claim["error"]
    assert fake.ran("git", "commit") == [] and fake.ran("git", "push") == [] and fake.ran("gh", "pr", "create") == []
    log = capsys.readouterr().out
    assert "verify_failed" in log and "rounds=3" in log and "protected_path" in log and "input_tokens" in log
    assert read_json(config.BUDGET)["model_calls"] == 3 and read_json(config.BUDGET)["prs"] == 0


def test_author_failure_without_usage_logs_no_invented_number(author, capsys):
    author.answer = failed("cli_error", rounds=1, usage=None, kinds=("cli_error",))
    author.use(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()
    line = next(row for row in capsys.readouterr().out.splitlines() if "reason_code=cli_error" in row)
    assert "usage=none" in line and "tokens" not in line


def test_second_author_failure_is_dead_like_the_plan_flow(author):
    author.answer = failed()
    author.use(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    write_json(config.CLAIMS, {"simplicio-a#5": {"attempts": 1, "status": "retry", "next_try_at": state.iso(FIXED)}})
    run_tick()
    assert read_json(config.CLAIMS)["simplicio-a#5"]["status"] == "dead"


def test_unsupported_family_fails_with_unsupported_family_and_gives_the_attempt_back(env, monkeypatch):
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "author")
    monkeypatch.setattr(host_mode, "choose", pick("codex"))
    fake = env(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()  # the real run_author refuses a family it has no argv for, before any process
    claim = read_json(config.CLAIMS)["simplicio-a#5"]
    assert claim["status"] == "retry" and claim["reason_code"] == "unsupported_family" and claim["attempts"] == 0
    assert fake.ran("git", "commit") == [] and fake.ran("gh", "pr", "create") == []


CONFIGURATION = ["unsupported_family", "sandbox_unavailable", "claude_login_missing", "cli_unavailable", "home_unavailable"]


@pytest.mark.parametrize("reason", CONFIGURATION)
def test_a_configuration_failure_gives_the_attempt_back_and_backs_off(author, reason, capsys):
    author.answer = failed(reason, rounds=0, kinds=(reason,))
    author.use(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#5"]
    assert claim["status"] == "retry" and claim["attempts"] == 0 and claim["reason_code"] == reason
    assert claim["next_try_at"] == state.iso(FIXED + config.RETRY_AFTER)
    assert f"reason_code={reason}" in capsys.readouterr().out


@pytest.mark.parametrize("reason", CONFIGURATION)
def test_a_configuration_failure_never_makes_the_item_dead(author, reason):
    author.answer = failed(reason, rounds=0, kinds=(reason,))
    author.use(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    write_json(config.CLAIMS, {"simplicio-a#5": {"attempts": 1, "status": "retry", "next_try_at": state.iso(FIXED)}})
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#5"]
    assert claim["status"] == "retry" and claim["attempts"] == 1


def test_a_real_failure_still_counts_the_attempt(author):
    author.answer = failed("cli_error", rounds=1, kinds=("cli_error",))
    author.use(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()
    assert read_json(config.CLAIMS)["simplicio-a#5"]["attempts"] == 1


def test_the_first_supported_family_is_the_author(author, monkeypatch):
    monkeypatch.setattr(host_mode, "choose", pick("codex", "claude"))
    author.use(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()
    assert author.calls[0][2]["family"] == "claude"


@pytest.mark.parametrize("value", ["plans", "AUTHOR", " ", " author", "author,plan"])
def test_an_invalid_executor_value_is_a_startup_error(env, monkeypatch, value, capsys):
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, value)
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    assert asyncio.run(watcher_main(once=True)) == 1
    out = capsys.readouterr().out
    assert author_executor.EXECUTOR_ENV in out and "author" in out and "plan" in out
    assert read_json(config.STATUS)["reason_code"] == "executor_env_invalid"
    assert fake.calls == []


def test_an_empty_executor_value_is_the_same_as_unset(env, monkeypatch):
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "")
    assert author_executor.selected(os.environ) == "plan" and author_executor.refusal(os.environ) is None

    async def boom(*args, **kwargs):
        raise AssertionError("the author flow must not run")

    monkeypatch.setattr(author_flow, "run_author", boom)
    fake = env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    assert len(fake.turbo_argv) == 1 and read_json(config.CLAIMS)["simplicio-a#7"]["status"] == "done"


@pytest.mark.parametrize("value", ["plan", "author"])
def test_a_valid_executor_value_starts(monkeypatch, value):
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, value)
    assert author_executor.refusal(os.environ) is None


def test_the_tick_itself_refuses_an_invalid_value(env, monkeypatch):
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "nope")
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    run_tick()
    assert read_json(config.STATUS)["phase"] == "blocked" and read_json(config.STATUS)["reason_code"] == "executor_env_invalid"
    assert fake.calls == []


def test_author_needs_the_exec_executor(env, monkeypatch):
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "author")  # the env fixture sets SIMPLICIO_EXECUTOR=openrouter
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    baseline()
    run_tick()
    assert read_json(config.STATUS)["reason_code"] == "author_needs_exec" and fake.calls == []


@pytest.mark.parametrize("value,expected", [(None, 3), ("1", 1), ("10", 10), ("5", 5)])
def test_rounds_come_from_the_environment(author, monkeypatch, value, expected):
    if value is not None:
        monkeypatch.setenv(author_executor.ROUNDS_ENV, value)
    author.use(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()
    assert author.calls[0][2]["rounds"] == expected


@pytest.mark.parametrize("value,expected", [(None, 900), ("60", 60), ("3600", 3600), ("1200", 1200),
                                            ("59", 900), ("3601", 900), ("0", 900), ("100000", 900), ("x", 900), ("", 900), ("2.5", 900)])
def test_the_round_time_limit_comes_from_the_environment(author, monkeypatch, value, expected):
    monkeypatch.delenv(author_flow.TIMEOUT_ENV, raising=False)
    if value is not None:
        monkeypatch.setenv(author_flow.TIMEOUT_ENV, value)
    author.use(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()
    assert author.calls[0][2]["timeout_s"] == expected


def test_a_bad_time_limit_never_stops_the_service(monkeypatch):
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "author")
    monkeypatch.setenv(author_flow.TIMEOUT_ENV, "nope")
    assert author_executor.refusal() is None


@pytest.mark.parametrize("value", ["0", "11", "-1", "x", "", "2.5"])
def test_invalid_rounds_are_a_startup_error(monkeypatch, value):
    monkeypatch.setenv(author_executor.ROUNDS_ENV, value)
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "author")
    message = author_executor.refusal(os.environ)
    assert message and author_executor.ROUNDS_ENV in message and "10" in message


def test_rounds_are_not_checked_when_the_plan_flow_runs(monkeypatch):
    monkeypatch.delenv(author_executor.EXECUTOR_ENV, raising=False)
    monkeypatch.setenv(author_executor.ROUNDS_ENV, "x")
    assert author_executor.refusal(os.environ) is None


def test_the_plan_flow_is_unchanged_when_the_variable_is_unset(env, monkeypatch):
    monkeypatch.delenv(author_executor.EXECUTOR_ENV, raising=False)

    async def boom(*args, **kwargs):
        raise AssertionError("the author flow must not run")

    monkeypatch.setattr(author_flow, "run_author", boom)
    fake = env(FakeRun({"simplicio-a": [issue(7, "Add x")]}))
    baseline()
    run_tick()
    assert len(fake.turbo_argv) == 1
    assert read_json(config.CLAIMS)["simplicio-a#7"]["status"] == "done"


def test_the_plan_value_runs_the_plan_flow(env, monkeypatch):
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "plan")
    fake = env(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    assert len(fake.turbo_argv) == 1


@pytest.mark.parametrize("where", [("simplicio-a",), ("simplicio-a.wt", "6"), ("elsewhere",)])
def test_a_worktree_that_is_not_the_items_own_is_refused(author, where):
    dest = config.WORK.joinpath(*where)
    with pytest.raises(author_executor.AuthorFailed) as raised:
        asyncio.run(author_executor.run(dest, "simplicio-a", issue(5), "task", "pytest", host_mode.Executor("exec", ("claude",)), "loop/issue-5"))
    assert raised.value.reason_code == "worktree_mismatch" and author.calls == []


# --- the token ---------------------------------------------------------------------------------------------------------------

ENVELOPE = {"type": "result", "is_error": False, "result": "done", "usage": {"input_tokens": 4, "output_tokens": 2}}


class TokenRun(FakeRun):
    """FakeRun that also answers the author's `claude` and the verify `sh -c`, and records the env each got."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.author_envs = []

    async def __call__(self, argv, timeout=120, cwd=None, stdin=None, env=None):
        argv = list(argv)
        if argv[0] == "claude":
            self.author_envs.append(dict(env or {}))
            (Path(cwd) / "app.py").write_text("x = 2\n")
            return proc.Result(0, json.dumps(ENVELOPE))
        if argv[0] == "sh":
            self.author_envs.append(dict(env or {}))
            return proc.Result(0, "ok")
        return await super().__call__(argv, timeout, cwd, stdin, env)


def test_the_watcher_gives_the_author_and_verify_no_github_token(env, monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text('{"token": "t"}')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "author")
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, "ghp_SECRETSECRETSECRET")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-secret")
    monkeypatch.setattr(host_mode, "choose", pick("claude"))
    fake = env(TokenRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    assert len(fake.author_envs) == 2, "the author and the verify command both ran"
    for seen in fake.author_envs:
        assert "GH_TOKEN" not in seen and "GITHUB_TOKEN" not in seen and "OPENROUTER_API_KEY" not in seen
        assert "ghp_SECRETSECRETSECRET" not in json.dumps(seen)
    assert read_json(config.CLAIMS)["simplicio-a#7"]["status"] == "done"
    assert fake.ran("gh", "pr", "create")


def test_the_watcher_passes_the_author_no_token_argument(author):
    author.use(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    task_text, _worktree, kwargs = author.calls[0]
    assert set(kwargs) <= {"family", "verify", "rounds", "runner", "allow_unsandboxed", "run_tests", "timeout_s"}
    assert "ghp_FAKEconftest" not in json.dumps({k: v for k, v in kwargs.items() if k != "runner"}) + task_text


# --- the CLI does not run the author's tests unless the operator says so (MAJOR 3) -------------------------------------------------

def test_the_watcher_does_not_let_the_cli_run_tests_by_default(author, monkeypatch):
    monkeypatch.delenv(author_executor.RUN_TESTS_ENV, raising=False)
    author.use(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    assert author.calls[0][2]["run_tests"] is False


@pytest.mark.parametrize("value,expected", [("1", True), ("0", False), ("", False), ("true", False), ("yes", False), (" 1", False)])
def test_only_the_value_one_lets_the_cli_run_tests(author, monkeypatch, value, expected):
    monkeypatch.setenv(author_executor.RUN_TESTS_ENV, value)
    author.use(FakeRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    assert author.calls[0][2]["run_tests"] is expected


# --- the sandbox opt-out is the operator's, never the default (MINOR 6) ---------------------------------------------------------

def call_run(head="loop/issue-5", number=5):
    dest = worktrees_item(number)
    return asyncio.run(author_executor.run(dest, "simplicio-a", issue(number), "task", "pytest", host_mode.Executor("exec", ("claude",)), head))


def test_the_author_is_sandboxed_unless_the_operator_opted_out(author, env, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_247_ALLOW_UNSANDBOXED", raising=False)  # the tick itself would stop here without bwrap: call the executor
    heads(monkeypatch)
    call_run()
    assert author.calls[0][2]["allow_unsandboxed"] is False


@pytest.mark.parametrize("value,expected", [("1", True), ("0", False), ("", False), ("true", False)])
def test_allow_unsandboxed_follows_the_environment(author, env, monkeypatch, value, expected):
    monkeypatch.setenv("SIMPLICIO_247_ALLOW_UNSANDBOXED", value)
    heads(monkeypatch)
    call_run()
    assert author.calls[0][2]["allow_unsandboxed"] is expected


# --- failed tasks count in the metrics, a lost report hides nothing (MINOR 7) ----------------------------------------------------


def worktrees_item(number):
    from simplicio_loop.watcher247 import worktrees
    return worktrees.item_path("simplicio-a", number)


def heads(monkeypatch, ref="refs/heads/loop/issue-5", code=0):
    """proc.run answers `git symbolic-ref HEAD` with `ref`; every call is recorded."""
    seen = []

    async def run(argv, **kwargs):
        seen.append((list(argv), kwargs.get("cwd")))
        return proc.Result(code, ref + "\n" if code == 0 else "", "" if code == 0 else "fatal: ref HEAD is not a symbolic ref")

    monkeypatch.setattr(proc, "run", run)
    return seen


def test_a_failed_author_run_carries_the_failed_step_for_the_metrics(author, env, monkeypatch):
    author.answer = failed("verify_failed", rounds=2)
    heads(monkeypatch)
    with pytest.raises(author_executor.AuthorFailed) as raised:
        call_run()
    steps = raised.value.exec_steps
    assert [(s["role"], s["family"], s["outcome"], s["reason"]) for s in steps] == [("coordination", "claude", "failed", "verify_failed")]
    assert host_mode.steps_of(raised.value) == steps


def test_a_report_that_cannot_be_written_does_not_hide_a_failed_result(author, env, monkeypatch):
    author.answer = failed("verify_failed", rounds=2)
    heads(monkeypatch)

    def broken(dest, report):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(execution_report, "write_report", broken)
    with pytest.raises(author_executor.AuthorFailed) as raised:
        call_run()
    assert raised.value.reason_code == "verify_failed" and "rounds=2" in str(raised.value)


@pytest.mark.parametrize("error", [OSError(28, "No space left on device"), RuntimeError("bad report"), ValueError("bad value")])
def test_a_report_that_cannot_be_written_does_not_hide_an_ok_result(author, env, monkeypatch, error):
    heads(monkeypatch)

    def broken(dest, report):
        raise error

    monkeypatch.setattr(execution_report, "write_report", broken)
    claim = call_run()
    assert claim["turbo_status"] == "ok" and claim["executor"] == "author" and claim["rounds"] == 2


def test_the_report_has_the_measured_cache_read_tokens_next_to_input_and_output(tmp_path):
    usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 3, "measured_rounds": 2}
    result = author_flow.AuthorResult("ok", 2, "s", ["a"], [], usage, "ok")
    _steps, report = author_executor.report_of(tmp_path, {"number": 7}, "simplicio-a", result, "claude", 12, None)
    tokens = report["tasks"][-1]["tokens"]
    assert (tokens["tokens_in"], tokens["tokens_out"], tokens["tokens_cached"]) == (10, 5, 3)


def test_the_report_has_no_cache_number_when_the_cli_gave_none(tmp_path):
    usage = {"input_tokens": 10, "output_tokens": 5, "measured_rounds": 1}
    result = author_flow.AuthorResult("ok", 1, "s", ["a"], [], usage, "ok")
    _steps, report = author_executor.report_of(tmp_path, {"number": 7}, "simplicio-a", result, "claude", 12, None)
    assert report["tasks"][-1]["tokens"]["tokens_cached"] is None


# --- the host commits only to the item's branch (MINOR 4) -----------------------------------------------------------------------

def test_a_head_that_moved_off_the_items_branch_fails_the_run_before_any_commit(author):
    fake = author.use(FakeRun({"simplicio-a": [issue(9)]}))
    fake.moved_head = "refs/heads/loop/issue-1"
    baseline()
    run_tick()
    claim = read_json(config.CLAIMS)["simplicio-a#9"]
    assert claim["status"] == "retry" and claim["reason_code"] == "head_moved" and claim["attempts"] == 1
    assert "refs/heads/loop/issue-1" in claim["error"] and "refs/heads/loop/issue-9" in claim["error"]
    assert fake.ran("git", "add") == [] and fake.ran("git", "commit") == [] and fake.ran("git", "push") == [] and fake.ran("gh", "pr", "create") == []


def test_the_run_checks_the_head_with_symbolic_ref_in_the_items_worktree(author, env, monkeypatch):
    seen = heads(monkeypatch)
    call_run()
    assert seen == [(["git", "symbolic-ref", "HEAD"], worktrees_item(5))]


@pytest.mark.parametrize("ref,code", [("refs/heads/loop/issue-9", 0), ("refs/heads/loop/issue-5x", 0), ("loop/issue-5", 0), ("", 0), ("", 128)])
def test_any_head_but_the_items_branch_is_head_moved(author, env, monkeypatch, ref, code):
    heads(monkeypatch, ref=ref, code=code)
    with pytest.raises(author_executor.AuthorFailed) as raised:
        call_run()
    assert raised.value.reason_code == "head_moved" and raised.value.exec_steps[0]["reason"] == "head_moved"


def test_the_head_of_the_items_branch_passes(author, env, monkeypatch):
    heads(monkeypatch)
    assert call_run()["executor"] == "author"


def test_a_failed_author_result_is_not_hidden_by_the_head_check(author, env, monkeypatch):
    author.answer = failed("verify_failed")
    seen = heads(monkeypatch, ref="refs/heads/other")
    with pytest.raises(author_executor.AuthorFailed) as raised:
        call_run()
    assert raised.value.reason_code == "verify_failed" and seen == []


# --- the family in the point context is the one the author used (MINOR 7) -------------------------------------------------------

def test_the_point_context_family_is_the_family_the_author_used(author, monkeypatch):
    monkeypatch.setattr(host_mode, "choose", pick("codex", "claude"))
    seen = []
    real = points.run

    async def spy(stage, ctx):
        seen.append((stage, ctx.family))
        return await real(stage, ctx)

    monkeypatch.setattr(points, "run", spy)
    author.use(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()
    assert author.calls[0][2]["family"] == "claude"
    assert seen and {family for stage, family in seen if stage in ("apply", "verify", "pr", "done")} == {"claude"}


def test_the_point_context_family_of_the_plan_flow_is_the_first_family(env, monkeypatch):
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "plan")
    monkeypatch.setattr(host_mode, "choose", pick("codex", "claude"))
    seen = []
    real = points.run

    async def spy(stage, ctx):
        seen.append(ctx.family)
        return await real(stage, ctx)

    monkeypatch.setattr(points, "run", spy)
    env(FakeRun({"simplicio-a": [issue(5)]}))
    baseline()
    run_tick()
    assert seen and set(seen) == {"codex"}


# --- the lease heartbeat writes telemetry in the worktree and must not fail the run (BLOCKER 1) ----------------------------------

class SlowRun(TokenRun):
    """TokenRun whose `claude` takes `nap` seconds and notes the telemetry files the heartbeat had written by then."""

    nap = 0.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.telemetry = []
        self.author_argvs = []

    async def __call__(self, argv, timeout=120, cwd=None, stdin=None, env=None):
        if argv[0] == "claude":
            self.author_argvs.append(list(argv))
            await asyncio.sleep(self.nap)
            self.telemetry.append(sorted(str(p.relative_to(cwd)) for p in Path(cwd).glob(".simplicio-loop/orchestrator/runs/*/events.jsonl")))
        return await super().__call__(argv, timeout, cwd, stdin, env)


@pytest.fixture
def logged_in(env, monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text('{"token": "t"}')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("SIMPLICIO_247_AUTHOR_HOME_BASE", raising=False)
    monkeypatch.setenv(author_executor.EXECUTOR_ENV, "author")
    monkeypatch.setattr(host_mode, "choose", pick("claude"))
    return home


def test_a_round_longer_than_the_heartbeat_still_ends_ok(logged_in, env, monkeypatch):
    monkeypatch.setattr(config, "HEARTBEAT_S", 0.05)
    SlowRun.nap = 0.6
    fake = env(SlowRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    assert fake.telemetry and fake.telemetry[0], "the heartbeat wrote its events inside the worktree while the CLI ran"
    claim = read_json(config.CLAIMS)["simplicio-a#7"]
    assert claim["status"] == "done" and claim["pr"] == PR_URL, claim
    assert fake.ran("git", "commit") and fake.ran("gh", "pr", "create")


def test_the_cli_of_the_watcher_gets_no_bash_tool_by_default(logged_in, env, monkeypatch):
    monkeypatch.delenv(author_executor.RUN_TESTS_ENV, raising=False)
    SlowRun.nap = 0.0
    fake = env(SlowRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    argv = fake.author_argvs[0]
    start = argv.index("--allowedTools") + 1
    tools = argv[start:argv.index("--disallowedTools")]
    assert tools == ["Read", "Grep", "Glob", "Edit", "Write"]


def test_run_tests_one_gives_the_cli_the_pytest_entries(logged_in, env, monkeypatch):
    monkeypatch.setenv(author_executor.RUN_TESTS_ENV, "1")
    SlowRun.nap = 0.0
    fake = env(SlowRun({"simplicio-a": [issue(7)]}))
    baseline()
    run_tick()
    assert "Bash(python3 -m pytest:*)" in fake.author_argvs[0]
