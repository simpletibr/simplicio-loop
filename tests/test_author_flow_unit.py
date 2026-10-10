"""Unit tests for the author flow: a fake claude CLI writes files, the loop checks the diff, runs verify and corrects.

No network and no real CLI: the injected runner swaps the `claude` argv for a fake script (scenario.json lists what each round does).
"""
import asyncio
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import types
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from simplicio_loop import author_cli, author_flow, author_isolation, cli_impl
from simplicio_loop.watcher247 import proc, sandbox

SESSION = "11111111-2222-3333-4444-555555555555"
ENVELOPE = {"type": "result", "is_error": False, "result": "done", "session_id": SESSION,
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3}}

FAKE = """\
import json, os, pathlib, subprocess, sys
here = pathlib.Path(__file__).parent
steps = json.loads((here / "scenario.json").read_text())
log = here / "calls.jsonl"
n = len(log.read_text().splitlines()) if log.exists() else 0
step = steps[min(n, len(steps) - 1)]
home = pathlib.Path(os.environ["HOME"])
home_files = sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file())
with log.open("a") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "env": sorted(os.environ), "cwd": os.getcwd(), "home": str(home),
                             "home_files": home_files, "bytecode": os.environ.get("PYTHONDONTWRITEBYTECODE"),
                             "api_key": os.environ.get("ANTHROPIC_API_KEY")}) + "\\n")
for command in step.get("run", []):
    subprocess.run(command, check=True)
for name, text in step.get("home_write", {}).items():
    (home / name).parent.mkdir(parents=True, exist_ok=True)
    (home / name).write_text(text)
for name, text in step.get("write", {}).items():
    path = pathlib.Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
for name in step.get("delete", []):
    pathlib.Path(name).unlink()
sys.stdout.write(step["raw"] if "raw" in step else json.dumps(step.get("envelope", %r)))
sys.exit(step.get("exit", 0))
""" % (ENVELOPE,)


def make_repo(root):
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    (root / "a.txt").write_text("a\n")
    (root / ".gitignore").write_text(".simplicio-loop/\n")  # as in this repo: the loop's own folder is ignored
    (root / "hooks").mkdir()
    (root / "hooks" / "guard.py").write_text("print('guard')\n")  # a tracked protected file
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    return root


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo")


@pytest.fixture
def linked(repo, tmp_path):
    """A linked worktree of `repo`, whose `.git` is a file that points at an admin dir."""
    path = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "-q", str(path), "-b", "linked"], cwd=repo, check=True)
    return path


@pytest.fixture
def real_home(tmp_path, monkeypatch):
    """The service user's HOME, with a login and things that must never reach the CLI or the verify command."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text('{"token": "login-secret"}')
    (home / ".claude" / "settings.json").write_text('{"hooks": "real"}')
    (home / ".ssh").mkdir()
    (home / ".ssh" / "id_rsa").write_text("ssh-secret")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(author_isolation.HOME_BASE_ENV, raising=False)
    return home


@pytest.fixture
def fake(tmp_path, monkeypatch, real_home):
    """(scenario setter, calls reader, runner) around a fake claude; the fake's own directory holds the scenario and the call log."""
    folder = tmp_path / "fake"
    folder.mkdir()
    (folder / "claude.py").write_text(FAKE)
    monkeypatch.setenv("GH_TOKEN", "ghp_secretsecretsecret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secretsecretsecret")
    seen = []

    async def runner(argv, **kwargs):
        seen.append(list(argv))
        if argv[0] == "claude":
            argv = [sys.executable, str(folder / "claude.py"), *argv[1:]]
        return await proc.run(argv, **kwargs)

    def scenario(*steps):
        (folder / "scenario.json").write_text(json.dumps(list(steps)))

    def calls():
        log = folder / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    runner.seen = seen
    return scenario, calls, runner


def go(repo, runner, task="fix it", **kwargs):
    kwargs.setdefault("family", "claude")
    kwargs.setdefault("allow_unsandboxed", True)
    return asyncio.run(author_flow.run_author(task, repo, runner=runner, **kwargs))


def prompt_of(call):
    return call["argv"][call["argv"].index("-p") + 1]


def flag_values(argv, flag):
    """The arguments after `flag` up to the next `--flag`."""
    start = argv.index(flag) + 1
    end = next((i for i in range(start, len(argv)) if argv[i].startswith("--")), len(argv))
    return argv[start:end]


# --- argv -----------------------------------------------------------------------------------------------------------------

def test_first_round_argv_creates_the_session_with_every_verified_flag():
    argv = author_flow.author_argv("claude", "do it", session=SESSION, resume=False, model="opus", effort="high")
    assert argv[:3] == ["claude", "-p", "do it"]
    assert flag_values(argv, "--session-id") == [SESSION] and "--resume" not in argv
    assert flag_values(argv, "--model") == ["opus"] and flag_values(argv, "--effort") == ["high"]
    assert flag_values(argv, "--permission-mode") == ["acceptEdits"]
    assert flag_values(argv, "--output-format") == ["json"]
    assert flag_values(argv, "--setting-sources") == ["user"]  # never `project`: the author writes .claude/settings.json there
    assert "--disable-slash-commands" in argv and "--strict-mcp-config" in argv
    assert flag_values(argv, "--disallowedTools") == ["WebFetch,WebSearch"]
    assert flag_values(argv, "--allowedTools") == [
        "Read", "Grep", "Glob", "Edit", "Write", "Bash(python -m pytest:*)", "Bash(python3 -m pytest:*)",
        "Bash(git status:*)", "Bash(git diff:*)"]  # no add/commit: in the sandbox a commit never finishes (read-only .git)


def test_correction_argv_resumes_the_same_session():
    argv = author_flow.author_argv("claude", "fix", session=SESSION, resume=True, model="", effort="")
    assert flag_values(argv, "--resume") == [SESSION] and "--session-id" not in argv
    assert "--model" not in argv and "--effort" not in argv


@pytest.mark.parametrize("family", ["codex", "grok", "agy", "opencode", "gemini", ""])
def test_other_families_are_unsupported(family):
    with pytest.raises(author_flow.AuthorUnsupported) as caught:
        author_flow.author_argv(family, "x", session=SESSION, resume=False, model="", effort="")
    assert caught.value.family == family and "claude" in str(caught.value)


def test_correction_prompt_lists_each_failure_without_secrets_and_is_capped():
    failures = [
        {"kind": "verify_failed", "detail": "x" * 20000 + " AssertionError token=abcdefghijklmnop1234 end"},
        {"kind": "protected_path", "detail": "hooks/evil.py"},
        {"kind": "empty_diff", "detail": ""},
    ]
    text = author_flow.correction_prompt(failures)
    assert "AssertionError" in text and "hooks/evil.py" in text and "no change" in text.lower()
    assert "abcdefghijklmnop1234" not in text
    assert len(text) <= author_flow.PROMPT_CAP


# --- run_author -----------------------------------------------------------------------------------------------------------

def test_unsupported_family_never_starts_a_process(repo, fake):
    _scenario, calls, runner = fake
    result = go(repo, runner, family="codex")
    assert (result.status, result.reason_code, result.rounds) == ("unsupported", "unsupported_family", 0)
    assert runner.seen == [] and calls() == []


def test_happy_path_in_one_round(repo, fake):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify="test -f done.txt")
    assert (result.status, result.reason_code, result.rounds) == ("ok", "ok", 1)
    assert result.changed == ["done.txt"] and result.failures == []
    (call,) = calls()
    assert flag_values(call["argv"], "--session-id") == [result.session_id]
    assert "fix it" in prompt_of(call) and "test -f done.txt" in prompt_of(call)
    assert call["cwd"] == str(repo.resolve())
    assert result.usage == {"input_tokens": 10, "output_tokens": 5, "cache_read_tokens": 3, "measured_rounds": 1}


def test_without_verify_the_result_says_it_was_not_verified(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    result = go(repo, runner)
    assert (result.status, result.reason_code) == ("ok", "ok_unverified")


def test_verify_failure_is_corrected_in_the_same_session(repo, fake):
    scenario, calls, runner = fake
    scenario({"write": {"wrong.txt": "x\n"}}, {"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify="test -f done.txt || { echo MISSING_DONE_FILE; exit 1; }")
    assert (result.status, result.rounds) == ("ok", 2)
    first, second = calls()
    assert flag_values(first["argv"], "--session-id") == [result.session_id] and "--resume" not in first["argv"]
    assert flag_values(second["argv"], "--resume") == [result.session_id] and "--session-id" not in second["argv"]
    assert "MISSING_DONE_FILE" in prompt_of(second) and "fix it" not in prompt_of(second)
    assert result.usage["measured_rounds"] == 2 and result.usage["input_tokens"] == 20


def test_rounds_run_out(repo, fake):
    scenario, calls, runner = fake
    scenario({"write": {"wrong.txt": "x\n"}})
    result = go(repo, runner, verify="echo STILL_RED; exit 1", rounds=3)
    assert (result.status, result.rounds, result.reason_code) == ("failed", 3, "verify_failed")
    assert len(calls()) == 3
    assert result.failures[-1]["kind"] == "verify_failed" and "STILL_RED" in result.failures[-1]["detail"]


def test_empty_diff_is_a_failure_even_when_verify_passes(repo, fake):
    scenario, _calls, runner = fake
    scenario({})
    result = go(repo, runner, verify="true", rounds=1)
    assert (result.status, result.reason_code, result.changed) == ("failed", "empty_diff", [])


def test_a_changed_protected_file_fails_the_round_even_when_verify_passes(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"hooks/evil.py": "x\n", "done.txt": "ok\n"}})
    result = go(repo, runner, verify="test -f done.txt", rounds=1)
    assert (result.status, result.reason_code) == ("failed", "protected_path")
    assert "hooks/evil.py" in result.failures[0]["detail"]


def test_protected_file_is_corrected_in_the_next_round(repo, fake):
    scenario, calls, runner = fake
    scenario({"write": {"hooks/evil.py": "x\n", "done.txt": "ok\n"}}, {"delete": ["hooks/evil.py"]})
    result = go(repo, runner, verify="test -f done.txt", rounds=2)
    assert (result.status, result.rounds, result.changed) == ("ok", 2, ["done.txt"])
    assert "hooks/evil.py" in prompt_of(calls()[1])


def test_the_loop_state_dir_is_protected_too(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {".simplicio-loop/loop.toml": "x\n"}})
    result = go(repo, runner, verify="true", rounds=1)
    assert result.reason_code == "protected_path"


def test_no_github_token_reaches_the_cli_or_the_verify_command(repo, fake):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify='test -z "$GH_TOKEN$GITHUB_TOKEN" && test -f done.txt')
    assert result.status == "ok"
    (call,) = calls()
    assert "GH_TOKEN" not in call["env"] and "GITHUB_TOKEN" not in call["env"]


def test_usage_is_absent_when_the_cli_reports_none(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}, "envelope": {"type": "result", "is_error": False, "result": "done"}})
    assert go(repo, runner, verify="true").usage is None


def test_usage_keeps_only_the_counters_the_cli_reports(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}, "envelope": {"is_error": False, "usage": {"input_tokens": 7, "output_tokens": "many"}}})
    assert go(repo, runner, verify="true").usage == {"input_tokens": 7, "measured_rounds": 1}


@pytest.mark.parametrize("raw", ["\x00not json{{{", "", "[1, 2]", "null"])
def test_output_that_is_not_a_json_envelope_is_a_bad_envelope_not_ok(repo, fake, raw):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}, "raw": raw})
    result = go(repo, runner, verify="touch ran.marker", rounds=3)
    assert (result.status, result.reason_code, result.rounds, result.usage) == ("failed", "bad_envelope", 1, None)
    assert result.changed == ["done.txt"] and not (repo / "ran.marker").exists() and len(calls()) == 1


@pytest.mark.parametrize("error", [TimeoutError("late"), FileNotFoundError(2, "gone"), OSError(7, "Argument list too long")])
def test_a_cli_that_edits_and_then_fails_to_finish_still_reports_what_changed(repo, fake, error):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})

    async def edits_then_fails(argv, **kwargs):
        await runner(argv, **kwargs)
        raise error

    result = go(repo, edits_then_fails, verify="touch ran.marker", rounds=3)
    assert (result.status, result.rounds, result.changed) == ("failed", 1, ["done.txt"]) and not (repo / "ran.marker").exists()


@pytest.mark.parametrize("step", [{"exit": 1, "raw": "boom"}, {"envelope": {"is_error": True, "result": "Not logged in"}}])
def test_a_cli_error_stops_before_verify_and_still_reports_what_changed(repo, fake, step):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}, **step})
    result = go(repo, runner, verify="touch ran.marker", rounds=3)
    assert (result.status, result.reason_code, result.rounds) == ("failed", "cli_error", 1)
    assert not (repo / "ran.marker").exists() and len(calls()) == 1
    assert result.changed == ["done.txt"]  # doc rule 6: also after a CLI error


def test_no_sandbox_refuses_unless_the_caller_allows_it(repo, fake, monkeypatch):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: None)
    result = go(repo, runner, verify="true", allow_unsandboxed=False)
    assert (result.status, result.reason_code, result.rounds) == ("failed", "sandbox_unavailable", 0)
    assert runner.seen == [] and calls() == []


def test_the_cli_sees_only_its_private_home_and_verify_sees_an_empty_one(repo, fake, real_home, monkeypatch):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    wrapped = []
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: "bwrap")
    monkeypatch.setattr(author_flow.shutil, "which", lambda name, path=None: "/bin/claude")
    monkeypatch.setattr(sandbox, "wrap", lambda argv, **kwargs: wrapped.append((list(argv), kwargs)) or list(argv))
    result = go(repo, runner, verify="test -f done.txt", allow_unsandboxed=False)
    assert result.status == "ok"
    assert [argv[0] for argv, _ in wrapped] == ["claude", "sh"]
    assert all(kwargs["clone"] == repo for _, kwargs in wrapped)
    (_, cli), (_, check) = wrapped
    private = Path(calls()[0]["home"])
    assert cli["home"].home == real_home and cli["home"].rw == (str(private.relative_to(real_home)),)  # the private home, nothing else
    assert cli["home"].hide == () and cli["home"].ro == (".local/share/claude", ".local/bin/claude")  # the binary only
    assert check["home"] == sandbox.HomeView(real_home)  # an empty tmpfs: no private home, no ~/.ssh, no ~/.config/gh


def test_the_cli_home_is_private_with_only_a_copy_of_the_login_and_is_deleted_after(repo, fake, real_home):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    assert go(repo, runner, verify="true").status == "ok"
    (call,) = calls()
    private = Path(call["home"])
    assert private != real_home and private.is_relative_to(real_home)
    assert call["home_files"] == [".claude/.credentials.json", ".owner"]  # the login and the pid of this run; not settings.json or ~/.ssh
    assert (call["bytecode"], call["api_key"]) == ("1", None)
    assert not private.exists()


def test_the_private_home_is_deleted_when_the_run_raises_or_times_out(repo, fake, real_home):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    homes = []

    async def boom(argv, **kwargs):
        homes.append(kwargs["env"]["HOME"])
        raise RuntimeError("boom")

    async def stuck(argv, **kwargs):
        homes.append(kwargs["env"]["HOME"])
        raise TimeoutError("stuck")

    with pytest.raises(RuntimeError):
        go(repo, boom)
    assert go(repo, stuck).reason_code == "timeout"
    assert len(homes) == 2 and not any(Path(h).exists() for h in homes)
    assert list((real_home / ".cache").glob("*/*")) == []


def test_a_missing_login_fails_closed_before_any_process(repo, fake, real_home):
    scenario, calls, runner = fake
    (real_home / ".claude" / ".credentials.json").unlink()
    result = go(repo, runner, verify="true")
    assert (result.status, result.reason_code, result.rounds) == ("failed", "claude_login_missing", 0)
    assert runner.seen == []


def test_the_login_copy_is_private_to_the_user(repo, fake, real_home):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}, "run": [["sh", "-c", "stat -c %a $HOME $HOME/.claude $HOME/.claude/.credentials.json > $HOME/modes"]]})
    modes = []

    async def spy(argv, **kwargs):
        out = await runner(argv, **kwargs)
        home = Path(kwargs["env"]["HOME"])
        if argv[0] == "claude":
            modes.extend((home / "modes").read_text().split())
        return out

    go(repo, spy, verify="true")
    assert modes == ["700", "700", "600"]


def test_settings_the_author_writes_in_its_home_do_not_survive_to_the_next_round(repo, fake):
    scenario, calls, runner = fake
    scenario({"write": {"wrong.txt": "x\n"}, "home_write": {".claude/settings.json": '{"hooks": 1}', ".claude/hooks/h.sh": "x"}},
             {"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify="test -f done.txt")
    assert result.rounds == 2
    assert calls()[1]["home_files"] == [".claude/.credentials.json", ".owner"]


def test_a_cli_that_does_not_answer_in_time_fails_the_run(repo, real_home, monkeypatch):
    async def stuck(argv, **kwargs):
        if argv[0] == "claude":
            raise TimeoutError("claude timed out")
        return await proc.run(argv, **kwargs)

    result = go(repo, stuck, verify="true")
    assert (result.status, result.reason_code) == ("failed", "timeout")


# --- the author cannot hide a change from the loop (it trusts the file system, never git) ---------------------------------------

def test_a_gitignore_the_author_writes_does_not_hide_a_protected_file(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {".gitignore": "hooks/evil.py\n", "hooks/evil.py": "x\n", "done.txt": "ok\n"}})
    result = go(repo, runner, verify="test -f done.txt", rounds=1)
    assert (result.status, result.reason_code) == ("failed", "protected_path")
    assert "hooks/evil.py" in result.failures[0]["detail"] and "hooks/evil.py" in result.changed


def test_the_loop_folder_is_seen_even_when_the_repo_ignores_it(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {".simplicio-loop/loop.toml": "x\n", "done.txt": "ok\n"}})
    assert go(repo, runner, verify="true", rounds=1).reason_code == "protected_path"


def test_assume_unchanged_does_not_hide_an_edit_of_a_tracked_protected_file(repo, fake):
    scenario, _calls, runner = fake
    scenario({"run": [["git", "update-index", "--assume-unchanged", "hooks/guard.py"]],
              "write": {"hooks/guard.py": "tampered\n", "done.txt": "ok\n"}})
    result = go(repo, runner, verify="test -f done.txt", rounds=1)
    assert (result.status, result.reason_code) == ("failed", "protected_path")


def test_skip_worktree_does_not_hide_the_edit_either(repo, fake):
    scenario, _calls, runner = fake
    scenario({"run": [["git", "update-index", "--skip-worktree", "hooks/guard.py"]],
              "write": {"hooks/guard.py": "tampered\n", "done.txt": "ok\n"}})
    assert go(repo, runner, verify="true", rounds=1).reason_code == "protected_path"


def test_repointing_the_git_file_of_a_linked_worktree_is_a_protected_change(linked, fake):
    scenario, _calls, runner = fake
    scenario({"write": {".git": "gitdir: /nowhere/attacker\n", "done.txt": "ok\n"}})
    result = go(linked, runner, verify="test -f done.txt", rounds=1)
    assert (result.status, result.reason_code) == ("failed", "protected_path")


@pytest.mark.parametrize("path", [".git/hooks/pre-commit", ".git/config"])
def test_a_hook_or_config_planted_in_the_git_dir_is_a_protected_change(repo, fake, path):
    scenario, _calls, runner = fake
    scenario({"write": {path: "[core]\n", "done.txt": "ok\n"}})
    assert go(repo, runner, verify="true", rounds=1).reason_code == "protected_path"


def test_git_state_churn_of_the_cli_is_not_a_change(repo, fake):
    scenario, _calls, runner = fake
    scenario({"run": [["sh", "-c", "echo ok > done.txt && git add done.txt && git commit -qm wip"]]})
    result = go(repo, runner, verify="test -f done.txt")
    assert (result.status, result.changed) == ("ok", ["done.txt"])


def test_a_change_that_keeps_the_size_and_the_mtime_is_still_seen(repo, fake):
    scenario, _calls, runner = fake
    scenario({"run": [["sh", "-c", "touch -r a.txt keep && printf 'b\\n' > a.txt && touch -r keep a.txt"]]})
    assert go(repo, runner, verify="true", rounds=1).changed == ["a.txt", "keep"]


def test_a_new_symlink_is_a_change(repo, fake):
    scenario, _calls, runner = fake
    scenario({"run": [["ln", "-s", "a.txt", "link"]]})
    assert go(repo, runner, verify="true").changed == ["link"]


def test_a_symlink_that_points_into_git_is_refused(repo, fake):
    scenario, _calls, runner = fake
    scenario({"run": [["ln", "-s", ".git", "link"]]})
    assert go(repo, runner, verify="true", rounds=1).reason_code == "protected_path"


def test_a_mode_change_alone_of_a_protected_file_is_a_change(repo, fake):
    scenario, _calls, runner = fake
    scenario({"run": [["chmod", "+x", "hooks/guard.py"]]})
    result = go(repo, runner, verify="true", rounds=1)
    assert (result.reason_code, result.changed) == ("protected_path", ["hooks/guard.py"])


def test_a_file_the_author_creates_and_deletes_in_the_same_round_is_no_change(repo, fake):
    scenario, _calls, runner = fake
    scenario({"run": [["sh", "-c", "echo x > tmp.txt && rm tmp.txt"]]})
    assert go(repo, runner, verify="true", rounds=1).reason_code == "empty_diff"


def test_the_pytest_cache_folder_is_noise_at_any_depth(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}, "run": [["sh", "-c", "mkdir -p .pytest_cache/v/cache sub/.pytest_cache && echo y > .pytest_cache/v/cache/lastfailed "
                                                                   "&& echo z > sub/.pytest_cache/CACHEDIR.TAG"]]})
    assert go(repo, runner, verify="true").changed == ["done.txt"]


@pytest.mark.parametrize("pyc", ["pkg/__pycache__/guard.cpython-314.pyc", "simplicio_loop/__pycache__/runner.cpython-314.pyc",
                                 "pkg/__pycache__/guard.cpython-314.opt-1.pyo", "__pycache__/a.pyc", "legacy/old.pyc", "legacy/old.pyo",
                                 "pkg/deep/er/__pycache__/m.cpython-314.pyc", "pkg/GUARD.PYC"])
def test_any_bytecode_file_the_author_makes_fails_the_round_even_beside_an_unprotected_module(repo, fake, pyc):
    """The CLI and verify run without bytecode, so a .pyc that changes is the author's, and python imports it in place of the .py."""
    scenario, _calls, runner = fake
    scenario({"write": {pyc: "hostile\n", "done.txt": "ok\n"}})
    result = go(repo, runner, verify="touch ran.marker", rounds=1)
    assert (result.status, result.reason_code, pyc in result.changed) == ("failed", "protected_path", True)
    assert pyc in result.failures[0]["detail"] and not (repo / "ran.marker").exists()


def test_a_bytecode_file_that_verify_makes_fails_the_round_too(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify="mkdir -p pkg/__pycache__ && echo x > pkg/__pycache__/guard.cpython-314.pyc", rounds=1)
    assert (result.reason_code, "pkg/__pycache__/guard.cpython-314.pyc" in result.changed) == ("protected_path", True)


def test_deleting_a_bytecode_file_that_existed_before_fails_the_round(repo, fake):
    (repo / "pkg" / "__pycache__").mkdir(parents=True)
    (repo / "pkg" / "__pycache__" / "guard.cpython-314.pyc").write_text("old")
    scenario, _calls, runner = fake
    scenario({"delete": ["pkg/__pycache__/guard.cpython-314.pyc"], "write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify="true", rounds=1)
    assert (result.reason_code, result.changed) == ("protected_path", ["done.txt", "pkg/__pycache__/guard.cpython-314.pyc"])


def test_a_bytecode_file_that_does_not_change_is_not_a_change(repo, fake):
    (repo / "pkg" / "__pycache__").mkdir(parents=True)
    (repo / "pkg" / "__pycache__" / "guard.cpython-314.pyc").write_text("old")
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    assert go(repo, runner, verify="true").changed == ["done.txt"]


def test_another_file_in_a_pycache_folder_is_an_ordinary_change(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"src/__pycache__/payload.sh": "echo hostile\n", "done.txt": "ok\n"}})
    result = go(repo, runner, verify="true")
    assert (result.status, result.changed) == ("ok", ["done.txt", "src/__pycache__/payload.sh"])


def test_the_correction_for_bytecode_says_to_delete_it_and_not_to_make_more():
    text = author_flow.correction_prompt([{"kind": "protected_path", "detail": "pkg/__pycache__/m.pyc"}])
    assert ".pyc" in text and ".pyo" in text and "delete" in text.lower() and "PYTHONDONTWRITEBYTECODE" in text


def test_a_real_pytest_run_as_verify_leaves_no_false_positive(repo, fake):
    """pytest writes .pytest_cache; with bytecode off it writes no .pyc. The round must stay ok."""
    scenario, _calls, runner = fake
    scenario({"write": {"test_ok.py": "def test_a():\n    assert 1 + 1 == 2\n"}})
    result = go(repo, runner, verify="python3 -m pytest -q -p no:cacheprovider test_ok.py && python3 -m pytest -q test_ok.py")
    assert (result.status, result.reason_code, result.changed) == ("ok", "ok", ["test_ok.py"])
    assert (repo / ".pytest_cache").is_dir()  # it was written, and it was not a change


@pytest.mark.parametrize("pyc", ["simplicio_loop/__pycache__/plan_paths.cpython-314.pyc", "hooks/__pycache__/guard.cpython-314.pyc",
                                 "simplicio_loop/watcher247/__pycache__/verify.cpython-314.pyc"])
def test_a_pyc_beside_a_protected_module_is_a_protected_change(repo, fake, pyc):
    """python imports an UNCHECKED_HASH .pyc without reading the .py: the cache folder is not blind."""
    scenario, _calls, runner = fake
    scenario({"write": {pyc: "hostile\n", "done.txt": "ok\n"}})
    result = go(repo, runner, verify="touch ran.marker", rounds=1)
    assert (result.reason_code, pyc in result.changed) == ("protected_path", True)
    assert not (repo / "ran.marker").exists()  # a protected change found before verify: verify does not run


def test_a_protected_pyc_written_by_the_verify_command_is_caught_too(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify="mkdir -p hooks/__pycache__ && echo x > hooks/__pycache__/guard.cpython-314.pyc", rounds=1)
    assert result.reason_code == "protected_path"


def test_the_cli_and_verify_run_with_bytecode_writing_off_and_without_the_api_key(repo, fake, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secretsecret")
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify='test "$PYTHONDONTWRITEBYTECODE" = 1 && test -z "$ANTHROPIC_API_KEY" && test -f done.txt')
    assert result.status == "ok"
    assert (calls()[0]["bytecode"], calls()[0]["api_key"]) == ("1", None)  # the login is the file; an API key is not accepted yet


def test_a_deleted_protected_file_is_a_change(repo, fake):
    scenario, _calls, runner = fake
    scenario({"delete": ["hooks/guard.py"], "write": {"done.txt": "ok\n"}})
    assert go(repo, runner, verify="true", rounds=1).reason_code == "protected_path"


def test_nothing_in_the_flow_asks_git_for_a_security_decision(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"wrong.txt": "x\n"}}, {"write": {"done.txt": "ok\n"}})
    go(repo, runner, verify="test -f done.txt")
    assert [argv for argv in runner.seen if argv[0] == "git"] == []


def test_the_verify_command_cannot_plant_a_protected_file_after_the_check(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify="mkdir -p .github/workflows && echo x > .github/workflows/x.yml && test -f done.txt", rounds=1)
    assert (result.status, result.reason_code) == ("failed", "protected_path")
    assert ".github/workflows/x.yml" in result.failures[0]["detail"]


def test_verify_can_fail_and_plant_a_file_and_both_are_reported(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify="echo x > hooks/new.py; exit 1", rounds=1)
    assert [f["kind"] for f in result.failures] == ["verify_failed", "protected_path"]


def test_a_file_the_verify_command_makes_in_an_ordinary_path_is_not_a_failure(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify="echo x > report.txt")
    assert (result.status, result.changed) == ("ok", ["done.txt", "report.txt"])  # changed: the original snapshot against the final one


# --- inputs the flow must survive -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("rounds", [0, -1, 11])
def test_rounds_outside_one_to_ten_is_a_failed_result_not_an_exception(repo, fake, rounds):
    _scenario, _calls, runner = fake
    result = go(repo, runner, rounds=rounds)
    assert (result.status, result.reason_code, result.rounds) == ("failed", "bad_rounds", 0) and runner.seen == []


@pytest.mark.parametrize("error, reason", [(FileNotFoundError(2, "claude"), "cli_unavailable"),
                                           (OSError(7, "Argument list too long"), "argv_too_long"),
                                           (PermissionError(13, "denied"), "cli_unavailable")])
def test_an_os_error_while_launching_the_cli_is_a_failed_result(repo, fake, error, reason):
    async def broken(argv, **kwargs):
        raise error

    result = go(repo, broken)
    assert (result.status, result.reason_code, result.rounds) == ("failed", reason, 1)


def test_a_verify_command_that_cannot_start_is_a_failed_verify(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})

    async def no_shell(argv, **kwargs):
        if argv[0] == "sh":
            raise FileNotFoundError(2, "sh")
        return await runner(argv, **kwargs)

    result = go(repo, no_shell, verify="true", rounds=1)
    assert (result.reason_code, result.failures[0]["kind"]) == ("verify_failed", "verify_failed")


# --- the snapshot has a size and a time limit --------------------------------------------------------------------------------

def test_a_huge_sparse_file_is_recorded_by_size_and_mtime_not_hashed(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    with open(root / "huge.bin", "wb") as handle:
        handle.truncate(8 << 30)  # 8 GiB of holes: hashing it would read all of it
    (root / "small.txt").write_text("x")
    started = time.monotonic()
    first = author_isolation.snapshot(root)
    assert time.monotonic() - started < 5
    assert first["huge.bin"].startswith("big:") and not first["small.txt"].startswith("big:")
    assert author_isolation.snapshot(root) == first
    os.utime(root / "huge.bin", ns=(1, 1))  # a touch is seen
    assert author_isolation.diff(first, author_isolation.snapshot(root)) == ["huge.bin"]


def test_the_threshold_is_the_size_above_which_a_file_is_not_hashed(tmp_path, monkeypatch):
    monkeypatch.setattr(author_isolation, "BIG_FILE", 10)
    (tmp_path / "edge.txt").write_text("0123456789")
    (tmp_path / "over.txt").write_text("0123456789a")
    snap = author_isolation.snapshot(tmp_path)
    assert not snap["edge.txt"].startswith("big:") and snap["over.txt"].startswith("big:")


def test_a_big_file_swapped_for_one_of_the_same_size_and_mtime_is_seen_by_its_inode(tmp_path, monkeypatch):
    monkeypatch.setattr(author_isolation, "BIG_FILE", 10)
    target = tmp_path / "big.bin"
    target.write_text("0123456789a")
    first = author_isolation.snapshot(tmp_path)
    stamp = target.stat().st_mtime_ns
    spare = tmp_path.parent / "spare.bin"
    spare.write_text("0123456789b")
    os.utime(spare, ns=(stamp, stamp))
    os.replace(spare, target)  # same name, size, mode and mtime; a new inode
    assert author_isolation.diff(first, author_isolation.snapshot(tmp_path)) == ["big.bin"]


def test_a_snapshot_over_its_time_budget_raises_instead_of_hanging_between_files(tmp_path):
    (tmp_path / "empty.txt").write_text("")  # no chunk to read: only the check between files can stop this
    (tmp_path / "link").symlink_to("empty.txt")
    with pytest.raises(author_isolation.SnapshotTimeout):
        author_isolation.snapshot(tmp_path, budget_s=0)


def test_a_snapshot_over_its_time_budget_raises_instead_of_hanging_inside_a_file(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("a")
    clock = iter([0.0, 0.5])  # the deadline, then the check between files: both in time; the next reading is late
    monkeypatch.setattr(author_isolation, "time", types.SimpleNamespace(monotonic=lambda: next(clock, 9.0), time=time.time))
    with pytest.raises(author_isolation.SnapshotTimeout, match="while reading"):
        author_isolation.snapshot(tmp_path, budget_s=1)


def test_a_snapshot_that_runs_out_of_time_is_a_failed_result(repo, fake, monkeypatch):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    monkeypatch.setattr(author_isolation, "SNAPSHOT_BUDGET_S", 0)
    result = go(repo, runner, verify="true")
    assert (result.status, result.reason_code) == ("failed", "snapshot_timeout")
    assert not list((Path.home() / author_isolation.HOMES).glob("*"))


def test_a_symlink_to_a_folder_is_recorded_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.txt").write_text("1")
    root = tmp_path / "tree"
    root.mkdir()
    (root / "link").symlink_to(outside)
    (root / "loop").symlink_to(".")  # a loop would never end if links were followed
    first = author_isolation.snapshot(root)
    assert sorted(first) == ["link", "loop"]
    (outside / "big.txt").write_text("2")
    assert author_isolation.diff(first, author_isolation.snapshot(root)) == []


def test_retargeting_a_symlink_is_a_change(tmp_path):
    (tmp_path / "link").symlink_to("a")
    first = author_isolation.snapshot(tmp_path)
    (tmp_path / "link").unlink()
    (tmp_path / "link").symlink_to("b")
    assert author_isolation.diff(first, author_isolation.snapshot(tmp_path)) == ["link"]


def test_a_folder_that_cannot_be_listed_is_an_entry_of_its_own(tmp_path, monkeypatch):
    (tmp_path / "locked").mkdir()
    (tmp_path / "a.txt").write_text("a")
    real = os.scandir

    def scandir(path="."):
        if str(path).endswith("locked"):
            raise PermissionError(13, "denied", str(path))
        return real(path)

    monkeypatch.setattr(os, "scandir", scandir)
    snap = author_isolation.snapshot(tmp_path)
    assert snap["locked"] == "special:40000" and "a.txt" in snap


# --- the private HOME survives kills, races and odd hosts ----------------------------------------------------------------------

def stale_homes(real_home):
    return sorted(p.name for p in (real_home / author_isolation.HOMES).glob("*"))


def test_a_home_left_by_a_killed_run_is_swept_at_the_next_start_and_a_live_one_is_kept(repo, fake, real_home):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    homes = real_home / author_isolation.HOMES
    gone = subprocess.Popen(["true"])
    gone.wait()
    for name, pid in (("dead", gone.pid), ("live", os.getpid()), ("junk", "not a pid"), ("zero", 0), ("negative", -5)):  # kill(0, 0) hits a group
        (homes / name / ".claude").mkdir(parents=True)
        (homes / name / ".claude" / ".credentials.json").write_text("{}")
        (homes / name / ".owner").write_text(str(pid))
    for name, age in (("nopid-old", 3600), ("nopid-new", 0)):
        (homes / name).mkdir()
        os.utime(homes / name, (time.time() - age, time.time() - age))
    os.utime(homes / "junk", (time.time() - 3600,) * 2)
    assert go(repo, runner, verify="true").status == "ok"
    assert stale_homes(real_home) == ["live", "nopid-new"]


def test_the_owner_file_holds_the_pid_of_this_process(repo, fake, real_home):
    scenario, calls, runner = fake
    seen = []

    async def spy(argv, **kwargs):
        if argv[0] == "claude":
            seen.append((Path(kwargs["env"]["HOME"]) / ".owner").read_text())
        return await runner(argv, **kwargs)

    scenario({"write": {"done.txt": "ok\n"}})
    go(repo, spy, verify="true")
    assert seen == [str(os.getpid())]


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP])
def test_a_termination_signal_still_deletes_the_private_home_and_restores_the_handler(repo, fake, real_home, sig):
    scenario, _calls, runner = fake
    before = signal.getsignal(sig)
    homes = []

    async def killed(argv, **kwargs):
        homes.append(kwargs["env"]["HOME"])
        os.kill(os.getpid(), sig)
        await asyncio.sleep(5)

    with pytest.raises(SystemExit):
        go(repo, killed)
    assert not Path(homes[0]).exists() and signal.getsignal(sig) == before


def test_no_handler_is_installed_off_the_main_thread(repo, fake, real_home):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    before = signal.getsignal(signal.SIGTERM)
    out = []
    worker = threading.Thread(target=lambda: out.append(go(repo, runner, verify="true")))
    worker.start()
    worker.join()
    assert out[0].status == "ok" and signal.getsignal(signal.SIGTERM) == before


def test_parallel_runs_never_trip_over_each_other_creating_and_dropping_homes(tmp_path, fake, real_home):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    repos = [make_repo(tmp_path / f"r{i}") for i in range(4)]
    out, errors = [], []

    def work(path):
        try:
            for _ in range(5):
                out.append(go(path, runner, verify="true", rounds=1).status)
                (path / "done.txt").unlink()
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever escaped
            errors.append(repr(exc))

    threads = [threading.Thread(target=work, args=(path,)) for path in repos]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == [] and out == ["ok"] * 20 and stale_homes(real_home) == []


def test_dropping_a_home_never_removes_the_folder_other_runs_share(real_home):
    first = author_isolation.make_home(real_home, "one")
    second = author_isolation.make_home(real_home, "two")
    author_isolation.drop_home(first)
    assert second.is_dir() and first.parent.is_dir()
    author_isolation.drop_home(second)
    assert first.parent.is_dir()  # a run that is about to mkdir inside it would otherwise fail
    author_isolation.make_home(real_home, "three")  # and the next run finds it, or makes it again


def test_the_folder_of_the_private_homes_and_each_home_are_private_to_the_user(real_home):
    home = author_isolation.make_home(real_home, "one")
    modes = [stat.S_IMODE(path.stat().st_mode) for path in (real_home / author_isolation.HOMES, home, home / ".claude", home / author_isolation.LOGIN)]
    assert modes == [0o700, 0o700, 0o700, 0o600]


def test_the_shared_folder_is_made_again_when_it_is_gone(real_home):
    author_isolation.drop_home(author_isolation.make_home(real_home, "one"))
    shutil.rmtree(real_home / author_isolation.HOMES)
    assert author_isolation.make_home(real_home, "two").is_dir()


def test_a_host_where_the_home_cannot_be_made_is_a_failed_result(repo, fake, real_home):
    _scenario, _calls, runner = fake
    (real_home / ".cache").write_text("a file where the folder should be")
    result = go(repo, runner, verify="true")
    assert (result.status, result.reason_code, result.rounds) == ("failed", "home_unavailable", 0) and runner.seen == []


def test_a_missing_claude_binary_in_the_sandbox_is_cli_unavailable_before_any_home(repo, fake, real_home, monkeypatch):
    scenario, calls, runner = fake
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: "bwrap")
    monkeypatch.setattr(author_flow.shutil, "which", lambda name, path=None: None)
    result = go(repo, runner, verify="true", allow_unsandboxed=False)
    assert (result.status, result.reason_code, result.rounds) == ("failed", "cli_unavailable", 0)
    assert runner.seen == [] and not (real_home / author_isolation.HOMES).exists()


# --- the CLI --------------------------------------------------------------------------------------------------------------

def run_cli(monkeypatch, tmp_path, result, *extra):
    task = tmp_path / "task.md"
    task.write_text("fix the loop")
    seen = {}

    async def fake_run_author(task_text, worktree, **kwargs):
        seen.update(task=task_text, worktree=worktree, **kwargs)
        return result

    monkeypatch.setattr(author_cli, "run_author", fake_run_author)
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli_impl.main(["author", "--repo", str(tmp_path), "--task-file", str(task), *extra])
    return code, out.getvalue(), seen


@pytest.mark.parametrize("status, reason, code", [("ok", "ok", 0), ("failed", "verify_failed", 3), ("unsupported", "unsupported_family", 69)])
def test_cli_routes_to_the_flow_and_maps_the_exit_code(monkeypatch, tmp_path, status, reason, code):
    result = author_flow.AuthorResult(status=status, rounds=1, session_id=SESSION, changed=["a.py"], failures=[], usage=None, reason_code=reason)
    got, out, seen = run_cli(monkeypatch, tmp_path, result, "--verify", "pytest -q", "--rounds", "2", "--family", "claude")
    assert got == code
    assert json.loads(out) == {"status": status, "rounds": 1, "session_id": SESSION, "changed": ["a.py"], "failures": [], "usage": None, "reason_code": reason}
    assert (seen["task"], seen["verify"], seen["rounds"], seen["family"]) == ("fix the loop", "pytest -q", 2, "claude")
    assert Path(seen["worktree"]) == tmp_path and seen["allow_unsandboxed"] is False


def test_cli_usage_errors_exit_2(monkeypatch, tmp_path, capsys):
    result = author_flow.AuthorResult(status="ok", rounds=1, session_id=SESSION, changed=[], failures=[], usage=None, reason_code="ok")
    assert run_cli(monkeypatch, tmp_path, result, "--rounds", "0")[0] == 2
    assert run_cli(monkeypatch, tmp_path, result, "--rounds", "11")[0] == 2
    assert run_cli(monkeypatch, tmp_path, result, "--rounds", "10")[0] == 0
    assert cli_impl.main(["author", "--repo", str(tmp_path), "--task-file", str(tmp_path / "missing.md")]) == 2
    assert cli_impl.main(["author", "--repo", str(tmp_path)]) == 2
    capsys.readouterr()


# --- the host-owned run telemetry is not the author's (BLOCKER 1) -----------------------------------------------------------------

RUNS = ".simplicio-loop/orchestrator/runs/run-1/events.jsonl"


def test_the_snapshot_leaves_out_the_run_telemetry_and_nothing_else_of_the_loop_folder(tmp_path):
    for name in (RUNS, ".simplicio-loop/loop.toml", ".simplicio-loop/orchestrator/other/x", ".simplicio-loop/orchestrator/runs.txt"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("1")
    first = author_isolation.snapshot(tmp_path)
    assert RUNS not in first
    assert {".simplicio-loop/loop.toml", ".simplicio-loop/orchestrator/other/x", ".simplicio-loop/orchestrator/runs.txt"} <= set(first)
    (tmp_path / RUNS).write_text("2")
    (tmp_path / ".simplicio-loop/orchestrator/runs/run-2").mkdir()
    (tmp_path / ".simplicio-loop/orchestrator/runs/run-2/new.jsonl").write_text("3")
    assert author_isolation.diff(first, author_isolation.snapshot(tmp_path)) == []


def test_a_runs_folder_elsewhere_is_still_in_the_snapshot(tmp_path):
    (tmp_path / "orchestrator/runs").mkdir(parents=True)
    (tmp_path / "orchestrator/runs/x").write_text("1")
    (tmp_path / ".simplicio-loop/runs").mkdir(parents=True)
    (tmp_path / ".simplicio-loop/runs/y").write_text("1")
    assert {"orchestrator/runs/x", ".simplicio-loop/runs/y"} <= set(author_isolation.snapshot(tmp_path))


def test_a_runs_link_in_place_of_the_folder_is_a_change(tmp_path):
    (tmp_path / ".simplicio-loop/orchestrator").mkdir(parents=True)
    first = author_isolation.snapshot(tmp_path)
    (tmp_path / ".simplicio-loop/orchestrator/runs").symlink_to("/etc")
    assert author_isolation.diff(first, author_isolation.snapshot(tmp_path)) == [".simplicio-loop/orchestrator/runs"]


def test_a_round_that_the_host_telemetry_grew_in_is_ok_with_the_authors_file(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n", RUNS: "{}\n"}})
    result = go(repo, runner, verify="test -f done.txt")
    assert (result.status, result.reason_code, result.changed) == ("ok", "ok", ["done.txt"])


def test_telemetry_alone_is_not_a_change(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {RUNS: "{}\n"}})
    result = go(repo, runner, rounds=1)
    assert (result.reason_code, result.changed) == ("empty_diff", [])


@pytest.mark.parametrize("path", [".simplicio-loop/loop.toml", ".simplicio-loop/orchestrator/other/x", ".simplicio-loop/orchestrator/runs.txt"])
def test_an_author_file_in_the_loop_folder_outside_the_telemetry_is_still_protected(repo, fake, path):
    scenario, _calls, runner = fake
    scenario({"write": {path: "x\n", "done.txt": "ok\n"}})
    result = go(repo, runner, rounds=1)
    assert (result.status, result.reason_code) == ("failed", "protected_path") and path in result.changed


def test_the_telemetry_the_host_writes_while_verify_runs_is_not_protected_path(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify=f"mkdir -p {Path(RUNS).parent} && echo x >> {RUNS}; test -f done.txt")
    assert (result.status, result.reason_code) == ("ok", "ok")


# --- run_tests: the CLI cannot run the author's code (MAJOR 3) ---------------------------------------------------------------------

def test_run_tests_defaults_to_true_and_keeps_every_bash_entry():
    argv = author_flow.author_argv("claude", "x", session=SESSION, resume=False, model="", effort="")
    assert flag_values(argv, "--allowedTools") == list(author_flow.ALLOWED_TOOLS)
    assert author_flow.author_argv("claude", "x", session=SESSION, resume=False, model="", effort="", run_tests=True) == argv


def test_without_run_tests_the_cli_can_only_read_and_edit_files():
    argv = author_flow.author_argv("claude", "x", session=SESSION, resume=False, model="", effort="", run_tests=False)
    tools = flag_values(argv, "--allowedTools")
    assert tools == ["Read", "Grep", "Glob", "Edit", "Write"]
    assert not any("Bash" in tool or "pytest" in tool or "python" in tool or "git" in tool for tool in tools)  # git runs a configured program too


def test_run_author_hands_run_tests_to_every_round(repo, fake):
    scenario, calls, runner = fake
    scenario({"write": {"wrong.txt": "x\n"}}, {"write": {"done.txt": "ok\n"}})
    result = go(repo, runner, verify="test -f done.txt", run_tests=False)
    assert result.status == "ok" and result.rounds == 2
    assert [flag_values(call["argv"], "--allowedTools") for call in calls()] == [["Read", "Grep", "Glob", "Edit", "Write"]] * 2
    assert "cannot run" in prompt_of(calls()[0]).lower()


def test_run_author_keeps_the_bash_entries_by_default(repo, fake):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    go(repo, runner)
    assert flag_values(calls()[0]["argv"], "--allowedTools") == list(author_flow.ALLOWED_TOOLS)
    assert "cannot run" not in prompt_of(calls()[0]).lower()


def test_verify_still_runs_with_the_real_home_view_when_the_cli_cannot_run_tests(repo, fake, real_home):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    checks = []

    async def spy(argv, **kwargs):
        if argv[0] == "sh":
            checks.append(kwargs["env"]["HOME"])
        return await runner(argv, **kwargs)

    assert go(repo, spy, verify="true", run_tests=False).status == "ok"
    assert checks == [str(real_home)]  # under the sandbox the real HOME is an empty tmpfs: the private one is not there


# --- the base of the private HOMEs (MAJOR 2) ----------------------------------------------------------------------------------------

def test_the_base_of_the_homes_comes_from_the_environment(real_home, monkeypatch):
    assert author_isolation.homes_dir(real_home) == real_home / author_isolation.HOMES
    monkeypatch.setenv(author_isolation.HOME_BASE_ENV, str(real_home / "state" / "authors"))
    assert author_isolation.homes_dir(real_home) == real_home / "state" / "authors"
    home = author_isolation.make_home(real_home, "one")
    assert home == real_home / "state" / "authors" / "one" and (home / author_isolation.LOGIN).is_file()
    assert not (real_home / author_isolation.HOMES).exists()


def test_the_sweep_works_on_the_configured_base(real_home, monkeypatch):
    monkeypatch.setenv(author_isolation.HOME_BASE_ENV, str(real_home / "base"))
    gone = subprocess.Popen(["true"])
    gone.wait()
    stale = real_home / "base" / "dead"
    stale.mkdir(parents=True)
    (stale / ".owner").write_text(str(gone.pid))
    other = real_home / author_isolation.HOMES / "dead"
    other.mkdir(parents=True)
    (other / ".owner").write_text(str(gone.pid))
    author_isolation.make_home(real_home, "one")
    assert not stale.exists() and other.exists()  # only the configured base is swept


@pytest.mark.parametrize("value", ["relative/dir", "~/x", "../up", "/etc", "/tmp/elsewhere"])
def test_a_base_that_is_not_an_absolute_path_inside_the_home_is_home_unavailable(repo, fake, real_home, monkeypatch, value):
    _scenario, _calls, runner = fake
    monkeypatch.setenv(author_isolation.HOME_BASE_ENV, value)
    result = go(repo, runner, verify="true")
    assert (result.status, result.reason_code, result.rounds) == ("failed", "home_unavailable", 0) and runner.seen == []
    assert author_isolation.HOME_BASE_ENV in result.failures[0]["detail"] and value in result.failures[0]["detail"]


def test_a_base_with_a_dotdot_that_leaves_the_home_is_refused(real_home, monkeypatch):
    monkeypatch.setenv(author_isolation.HOME_BASE_ENV, str(real_home / ".." / "out"))
    with pytest.raises(OSError):
        author_isolation.make_home(real_home, "one")


def test_the_empty_base_is_the_default(real_home, monkeypatch):
    monkeypatch.setenv(author_isolation.HOME_BASE_ENV, "")
    assert author_isolation.homes_dir(real_home) == real_home / author_isolation.HOMES


def test_a_read_only_base_is_home_unavailable_with_the_path_and_the_os_error(repo, fake, real_home, monkeypatch):
    _scenario, _calls, runner = fake
    base = real_home / "ro"
    base.mkdir()
    monkeypatch.setenv(author_isolation.HOME_BASE_ENV, str(base / "inner"))
    real_mkdir = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if self == base / "inner":
            raise OSError(30, "Read-only file system", str(self))
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    result = go(repo, runner, verify="true")
    detail = result.failures[0]["detail"]
    assert result.reason_code == "home_unavailable" and str(base / "inner") in detail and "Read-only file system" in detail


def test_the_cli_view_binds_the_private_home_of_the_configured_base(repo, fake, real_home, monkeypatch):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    monkeypatch.setenv(author_isolation.HOME_BASE_ENV, str(real_home / "state" / "authors"))
    views = []
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: "bwrap")
    monkeypatch.setattr(author_flow.shutil, "which", lambda name, path=None: "/bin/" + name)
    monkeypatch.setattr(sandbox, "wrap", lambda argv, **kwargs: (views.append(kwargs["home"]), argv)[1])
    result = go(repo, runner, verify="true", allow_unsandboxed=False)
    assert result.status == "ok"
    assert views[0].rw == (f"state/authors/{result.session_id}",)


# --- the login never reaches a file the host commits (MAJOR, round 3) ---------------------------------------------------------------

ACCESS = "sk-ant-oat01-ACCESSTOKENVALUE0123456789"
REFRESH = "sk-ant-ort01-REFRESHTOKENVALUE987654321"
LOGIN_JSON = json.dumps({"claudeAiOauth": {"accessToken": ACCESS, "refreshToken": REFRESH, "expiresAt": 1}})
FILE_TOOLS = ("Read", "Grep", "Glob", "Edit", "Write")


@pytest.fixture
def token_login(real_home):
    (real_home / ".claude" / ".credentials.json").write_text(LOGIN_JSON)
    return LOGIN_JSON


def test_deny_rules_pin_the_exact_strings_for_an_absolute_path():
    rules = author_flow.deny_rules(Path("/h/priv/run-1"), Path("/h/user"))
    paths = ("//h/priv/run-1/**", "//h/priv/run-1/.claude/**", "//h/priv/run-1/.claude/.credentials.json",
             "//h/user/.claude/**", "//h/user/.claude/.credentials.json")
    assert rules == [f"{tool}({path})" for tool in FILE_TOOLS for path in paths]


def test_the_credential_file_is_denied_by_its_own_path_for_every_file_tool():
    rules = author_flow.deny_rules(Path("/h/priv/run-1"), Path("/h/user"))
    for tool in FILE_TOOLS:
        assert f"{tool}(//h/priv/run-1/.claude/.credentials.json)" in rules
        assert f"{tool}(//h/user/.claude/.credentials.json)" in rules
        assert f"{tool}(//h/priv/run-1/**)" in rules  # the whole private home too


def test_author_argv_hands_the_deny_rules_to_disallowed_tools_one_argument_each():
    rules = author_flow.deny_rules(Path("/h/priv/run-1"), Path("/h/user"))
    argv = author_flow.author_argv("claude", "x", session=SESSION, resume=False, model="", effort="", deny=rules)
    assert flag_values(argv, "--disallowedTools") == ["WebFetch,WebSearch", *rules]
    assert flag_values(argv, "--allowedTools") == list(author_flow.ALLOWED_TOOLS)  # an allow entry does not beat a deny rule, and stays


def test_the_cli_of_a_run_is_denied_its_private_home_and_the_credential_file(repo, fake, real_home):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    assert go(repo, runner).status == "ok"
    argv = calls()[0]["argv"]
    private = calls()[0]["home"].lstrip("/")
    real = str(real_home).lstrip("/")
    denied = flag_values(argv, "--disallowedTools")
    for tool in FILE_TOOLS:
        assert f"{tool}(//{private}/**)" in denied
        assert f"{tool}(//{private}/.claude/.credentials.json)" in denied
        assert f"{tool}(//{real}/.claude/.credentials.json)" in denied
    assert "WebFetch,WebSearch" in denied


def test_every_round_keeps_the_deny_rules(repo, fake):
    scenario, calls, runner = fake
    scenario({"write": {"a.txt": "1\n"}}, {"write": {"done.txt": "ok\n"}})
    assert go(repo, runner, verify="test -f done.txt").rounds == 2
    first, second = (flag_values(call["argv"], "--disallowedTools") for call in calls())
    assert first == second and len(first) == 1 + 5 * len(FILE_TOOLS)


def test_a_cli_that_copies_the_login_file_fails_the_round_with_secret_in_diff(repo, fake, token_login, real_home):
    scenario, _calls, runner = fake
    scenario({"run": [["cp", str(real_home / ".claude/.credentials.json"), "notes.txt"]]})
    result = go(repo, runner, rounds=1)
    assert (result.status, result.reason_code) == ("failed", "secret_in_diff")
    assert result.changed == ["notes.txt"]
    assert "notes.txt" in result.failures[0]["detail"]
    assert ACCESS not in repr(result) and REFRESH not in repr(result) and "accessToken" not in repr(result)


@pytest.mark.parametrize("secret", [ACCESS, REFRESH])
def test_a_token_value_inside_other_text_is_a_leak_too(repo, fake, token_login, secret):
    scenario, _calls, runner = fake
    scenario({"write": {"docs/notes.md": f"# notes\ntoken = {secret}\n", "done.txt": "ok\n"}})
    result = go(repo, runner, verify="test -f done.txt", rounds=1)
    assert (result.status, result.reason_code) == ("failed", "secret_in_diff")
    assert "docs/notes.md" in result.failures[-1]["detail"] and secret not in repr(result)


def test_the_leak_stops_the_round_before_verify_runs(repo, fake, token_login, tmp_path):
    scenario, _calls, runner = fake
    marker = tmp_path / "verify-ran"
    scenario({"write": {"notes.txt": ACCESS, "done.txt": "ok\n"}})
    result = go(repo, runner, verify=f"touch {marker}", rounds=1)
    assert result.reason_code == "secret_in_diff" and not marker.exists()


def test_a_secret_that_verify_writes_into_the_tree_is_a_leak(repo, fake, token_login):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    verify = f"printf %s '{ACCESS}' > leaked.txt; test -f done.txt"
    result = go(repo, runner, verify=verify, rounds=1)
    assert result.reason_code == "secret_in_diff" and "leaked.txt" in result.failures[-1]["detail"]
    assert ACCESS not in repr(result)


def test_the_author_can_remove_the_leak_in_the_next_round_and_the_prompt_has_no_secret(repo, fake, token_login):
    scenario, calls, runner = fake
    scenario({"write": {"notes.txt": ACCESS, "done.txt": "ok\n"}}, {"delete": ["notes.txt"]})
    result = go(repo, runner, verify="test -f done.txt")
    assert (result.status, result.rounds) == ("ok", 2)
    second = prompt_of(calls()[1])
    assert "notes.txt" in second and "secret" in second.lower() and ACCESS not in second and REFRESH not in second


def test_a_token_the_cli_refreshed_in_its_home_during_the_round_is_a_leak_too(repo, fake, token_login):
    scenario, _calls, runner = fake
    fresh = "sk-ant-oat01-FRESHLYROTATEDTOKEN0000"
    new = json.dumps({"claudeAiOauth": {"accessToken": fresh, "refreshToken": "sk-ant-ort01-FRESHREFRESH000000"}})
    scenario({"home_write": {".claude/.credentials.json": new}, "write": {"notes.txt": fresh}})
    result = go(repo, runner, rounds=1)
    assert result.reason_code == "secret_in_diff" and fresh not in repr(result)


def test_nothing_the_run_prints_or_logs_holds_the_secret(repo, fake, token_login, capfd, caplog):
    scenario, _calls, runner = fake
    caplog.set_level("DEBUG")
    scenario({"write": {"notes.txt": f"{ACCESS}{REFRESH}"}})
    result = go(repo, runner, rounds=1)
    out = capfd.readouterr()
    for text in (out.out, out.err, caplog.text, json.dumps(result.failures), json.dumps(result.changed), repr(result)):
        assert ACCESS not in text and REFRESH not in text


def test_a_changed_file_without_the_secret_is_not_a_leak(repo, fake, token_login):
    scenario, _calls, runner = fake
    scenario({"write": {"notes.txt": "sk-ant-oat01-SOMEOTHERTOKEN\n", "done.txt": "ok\n"}})
    assert go(repo, runner, verify="test -f done.txt").status == "ok"


def test_a_login_file_of_a_short_or_odd_shape_never_flags_every_file(repo, fake, real_home):
    scenario, _calls, runner = fake
    (real_home / ".claude/.credentials.json").write_text('{"claudeAiOauth": {"accessToken": "ab", "refreshToken": 7}}')
    scenario({"write": {"notes.txt": "ab 7 abab\n", "done.txt": "ok\n"}})
    assert go(repo, runner, verify="test -f done.txt").status == "ok"


def test_login_secrets_are_the_whole_file_and_both_token_values_and_nothing_shorter(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(LOGIN_JSON)
    secrets = author_isolation.login_secrets(path, tmp_path / "missing.json")
    assert LOGIN_JSON.encode() in secrets and ACCESS.encode() in secrets and REFRESH.encode() in secrets
    assert all(len(secret) >= author_isolation.MIN_SECRET for secret in secrets)
    path.write_text("not json at all, but a long enough credential blob")
    assert author_isolation.login_secrets(path) == {b"not json at all, but a long enough credential blob"}


def test_the_scan_finds_a_secret_that_straddles_two_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(author_isolation, "SCAN_CHUNK", 16)
    (tmp_path / "big.txt").write_text("x" * 13 + ACCESS + "y" * 40)
    (tmp_path / "clean.txt").write_text("z" * 100)
    found = author_isolation.leaks(tmp_path, ["big.txt", "clean.txt", "gone.txt"], {ACCESS.encode()})
    assert found == ["big.txt"]


def test_the_scan_does_not_read_through_a_symlink(tmp_path):
    (tmp_path / "secret").write_text(ACCESS)
    (tmp_path / "link").symlink_to("secret")
    assert author_isolation.leaks(tmp_path, ["link"], {ACCESS.encode()}) == []


# --- inside the telemetry folder a link or a special file is still a change (MINOR 2) -----------------------------------------------

TELEMETRY = ".simplicio-loop/orchestrator/runs/run-1"


def test_a_symlink_in_the_telemetry_folder_is_a_change_and_a_regular_file_is_not(tmp_path):
    (tmp_path / TELEMETRY).mkdir(parents=True)
    (tmp_path / TELEMETRY / "events.jsonl").write_text("1\n")
    first = author_isolation.snapshot(tmp_path)
    assert f"{TELEMETRY}/events.jsonl" not in first
    (tmp_path / TELEMETRY / "events.jsonl").write_text("2\n")
    assert author_isolation.diff(first, author_isolation.snapshot(tmp_path)) == []
    (tmp_path / TELEMETRY / "events.jsonl").unlink()
    (tmp_path / TELEMETRY / "events.jsonl").symlink_to("../../../../.git/config")
    assert author_isolation.diff(first, author_isolation.snapshot(tmp_path)) == [f"{TELEMETRY}/events.jsonl"]


def test_a_link_to_a_folder_a_fifo_and_a_hard_link_in_the_telemetry_folder_are_changes(tmp_path):
    (tmp_path / TELEMETRY).mkdir(parents=True)
    (tmp_path / "target").write_text("t")
    first = author_isolation.snapshot(tmp_path)
    (tmp_path / TELEMETRY / "dirlink").symlink_to("/etc")
    os.mkfifo(tmp_path / TELEMETRY / "pipe")
    os.link(tmp_path / "target", tmp_path / TELEMETRY / "hard")
    assert author_isolation.diff(first, author_isolation.snapshot(tmp_path)) == sorted(
        [f"{TELEMETRY}/dirlink", f"{TELEMETRY}/pipe", f"{TELEMETRY}/hard"])


def test_a_symlink_a_conftest_plants_in_the_telemetry_folder_is_protected_path(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n", RUNS: "{}\n"}})
    plant = f"rm {RUNS} && ln -s ../../../../.git/config {RUNS}; test -f done.txt"
    result = go(repo, runner, verify=plant)
    assert (result.status, result.reason_code) == ("failed", "protected_path")
    assert RUNS in result.changed


def test_a_symlink_the_cli_plants_in_the_telemetry_folder_is_protected_path(repo, fake):
    scenario, _calls, runner = fake
    scenario({"run": [["mkdir", "-p", str(Path(RUNS).parent)], ["ln", "-s", "../../../../.git/config", RUNS]], "write": {"done.txt": "ok\n"}})
    result = go(repo, runner, rounds=1)
    assert (result.status, result.reason_code) == ("failed", "protected_path") and RUNS in result.changed
