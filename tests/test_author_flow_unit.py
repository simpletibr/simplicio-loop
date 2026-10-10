"""Unit tests for the author flow: a fake claude CLI writes files, the loop checks the diff, runs verify and corrects.

No network and no real CLI: the injected runner swaps the `claude` argv for a fake script (scenario.json lists what each round does).
"""
import asyncio
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from simplicio_loop import author_cli, author_flow, cli_impl
from simplicio_loop.watcher247 import proc, sandbox

SESSION = "11111111-2222-3333-4444-555555555555"
ENVELOPE = {"type": "result", "is_error": False, "result": "done", "session_id": SESSION,
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3}}

FAKE = """\
import json, os, pathlib, sys
here = pathlib.Path(__file__).parent
steps = json.loads((here / "scenario.json").read_text())
log = here / "calls.jsonl"
n = len(log.read_text().splitlines()) if log.exists() else 0
step = steps[min(n, len(steps) - 1)]
with log.open("a") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "env": sorted(os.environ), "cwd": os.getcwd()}) + "\\n")
for name, text in step.get("write", {}).items():
    path = pathlib.Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
for name in step.get("delete", []):
    pathlib.Path(name).unlink()
sys.stdout.write(step["raw"] if "raw" in step else json.dumps(step.get("envelope", %r)))
sys.exit(step.get("exit", 0))
""" % (ENVELOPE,)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    (root / "a.txt").write_text("a\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    return root


@pytest.fixture
def fake(tmp_path, monkeypatch):
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
    assert flag_values(argv, "--setting-sources") == ["project"]
    assert "--disable-slash-commands" in argv and "--strict-mcp-config" in argv
    assert flag_values(argv, "--disallowedTools") == ["WebFetch,WebSearch"]
    assert flag_values(argv, "--allowedTools") == [
        "Read", "Grep", "Glob", "Edit", "Write", "Bash(python -m pytest:*)", "Bash(python3 -m pytest:*)",
        "Bash(git status:*)", "Bash(git diff:*)", "Bash(git add:*)", "Bash(git commit:*)"]


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


def test_garbage_output_is_judged_by_the_diff_and_reports_no_usage(repo, fake):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}, "raw": "\x00not json{{{"})
    result = go(repo, runner, verify="test -f done.txt")
    assert (result.status, result.usage) == ("ok", None)


@pytest.mark.parametrize("step", [{"exit": 1, "raw": "boom"}, {"envelope": {"is_error": True, "result": "Not logged in"}}])
def test_a_cli_error_stops_before_verify(repo, fake, step):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}, **step})
    result = go(repo, runner, verify="touch ran.marker", rounds=3)
    assert (result.status, result.reason_code, result.rounds) == ("failed", "cli_error", 1)
    assert not (repo / "ran.marker").exists() and len(calls()) == 1


def test_no_sandbox_refuses_unless_the_caller_allows_it(repo, fake, monkeypatch):
    scenario, calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: None)
    result = go(repo, runner, verify="true", allow_unsandboxed=False)
    assert (result.status, result.reason_code, result.rounds) == ("failed", "sandbox_unavailable", 0)
    assert runner.seen == [] and calls() == []


def test_the_cli_and_verify_run_inside_the_sandbox(repo, fake, monkeypatch):
    scenario, _calls, runner = fake
    scenario({"write": {"done.txt": "ok\n"}})
    wrapped = []
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: "bwrap")
    monkeypatch.setattr(sandbox, "wrap", lambda argv, **kwargs: wrapped.append((list(argv), kwargs)) or list(argv))
    result = go(repo, runner, verify="test -f done.txt", allow_unsandboxed=False)
    assert result.status == "ok"
    assert [argv[0] for argv, _ in wrapped] == ["claude", "sh"]
    assert all(kwargs["clone"] == repo for _, kwargs in wrapped) and wrapped[0][1]["home"] is not None


def test_a_cli_that_does_not_answer_in_time_fails_the_run(repo, monkeypatch):
    async def stuck(argv, **kwargs):
        if argv[0] == "claude":
            raise TimeoutError("claude timed out")
        return await proc.run(argv, **kwargs)

    result = go(repo, stuck, verify="true")
    assert (result.status, result.reason_code) == ("failed", "timeout")


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
    assert cli_impl.main(["author", "--repo", str(tmp_path), "--task-file", str(tmp_path / "missing.md")]) == 2
    assert cli_impl.main(["author", "--repo", str(tmp_path)]) == 2
    capsys.readouterr()
