"""Unit tests for the author flow: a fake claude CLI writes files, the loop checks the diff, runs verify and corrects.

No network and no real CLI: the injected runner swaps the `claude` argv for a fake script (scenario.json lists what each round does).
"""
import asyncio
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
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


@pytest.mark.parametrize("step", [{"exit": 1, "raw": "boom"}, {"envelope": {"is_error": True, "result": "Not logged in"}}])
def test_a_cli_error_stops_before_verify_and_still_reports_what_changed(repo, fake, step):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}, **step})
    result = go(repo, runner, verify="touch ran.marker", rounds=3)
    assert (result.status, result.reason_code, result.rounds) == ("failed", "cli_error", 1)
    assert not (repo / "ran.marker").exists() and len(calls()) == 1
    assert result.changed == ["done.txt"]


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


def test_the_caches_python_leaves_are_not_changes_unless_they_shadow_a_protected_module(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}, "run": [["sh", "-c", "mkdir -p __pycache__ .pytest_cache pkg/__pycache__ && echo x > __pycache__/a.pyc "
                                                                   "&& echo y > .pytest_cache/b && echo z > pkg/__pycache__/m.cpython-314.pyc"]]})
    assert go(repo, runner, verify="true").changed == ["done.txt"]


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


def test_a_snapshot_over_its_time_budget_raises_instead_of_hanging(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    with pytest.raises(author_isolation.SnapshotTimeout):
        author_isolation.snapshot(tmp_path, budget_s=0)


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
    for name, pid in (("dead", gone.pid), ("live", os.getpid()), ("junk", "not a pid")):
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
