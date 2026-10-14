"""The author flow sends no request above the input-token ceiling (#1608, part C).

The real ``run_author`` runs with a fake runner in place of the CLI. The tests count the argv built and the processes
started, so a run the ceiling refuses shows zero of both.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplicio_loop import author_flow, author_isolation, input_ceiling
from simplicio_loop.input_ceiling import ENV_NAME, TOML_KEY

ENVELOPE = {"type": "result", "is_error": False, "result": "done", "session_id": "11111111-2222-3333-4444-555555555555"}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """The worktree being authored. The process cwd is ANOTHER directory, so a cwd fallback cannot pass by accident."""
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    (root / "a.txt").write_text("a\n")
    (root / ".gitignore").write_text(".simplicio-loop/\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv(ENV_NAME, raising=False)
    return root


@pytest.fixture
def home(tmp_path, monkeypatch):
    """The service user's HOME with a login, so a run reaches the ceiling check."""
    real = tmp_path / "home"
    (real / ".claude").mkdir(parents=True)
    (real / author_isolation.LOGIN).write_text('{"token": "login-secret"}')
    monkeypatch.setenv("HOME", str(real))
    monkeypatch.delenv(author_isolation.HOME_BASE_ENV, raising=False)
    return real


@pytest.fixture
def cli(monkeypatch):
    """Records each argv built and each process started. A run that starts the CLI writes a new file in its worktree."""
    built, started = [], []
    real_argv = author_flow.author_argv

    def argv_spy(family, prompt, **kwargs):
        built.append(prompt)
        return real_argv(family, prompt, **kwargs)

    async def runner(argv, *, cwd, **_):
        started.append(list(argv))
        (Path(cwd) / f"done-{len(started)}.txt").write_text("ok\n")
        return SimpleNamespace(returncode=0, stdout=json.dumps(ENVELOPE), stderr="")

    monkeypatch.setattr(author_flow, "author_argv", argv_spy)
    return SimpleNamespace(built=built, started=started, runner=runner)


def run(repo, cli, task="fix it"):
    return asyncio.run(author_flow.run_author(task, repo, runner=cli.runner, allow_unsandboxed=True, rounds=1))


def _write_toml(root, body):
    """The ceiling comes from the DEFAULT BRANCH: commit the file on `main` and point origin/HEAD at it."""
    root.mkdir(parents=True, exist_ok=True)
    git = ["git", "-C", str(root)]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True, capture_output=True)
    (root / ".simplicio-loop").mkdir(exist_ok=True)
    (root / ".simplicio-loop" / "loop.toml").write_text(body, encoding="utf-8")
    subprocess.run([*git, "add", "-f", ".simplicio-loop/loop.toml"], check=True, capture_output=True)
    subprocess.run([*git, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty",
                    "-m", "config"], check=True, capture_output=True)
    subprocess.run([*git, "update-ref", "refs/remotes/origin/main", "HEAD"], check=True, capture_output=True)
    subprocess.run([*git, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"], check=True,
                   capture_output=True)


def _write_working_toml(root, body):
    """A loop.toml in the working tree only: the ceiling never reads it."""
    (root / ".simplicio-loop").mkdir(exist_ok=True)
    (root / ".simplicio-loop" / "loop.toml").write_text(body, encoding="utf-8")


def test_a_prompt_under_the_default_ceiling_starts_the_cli(repo, home, cli):
    result = run(repo, cli)
    assert result.status == "ok"
    assert len(cli.built) == 1 and len(cli.started) == 1


def test_a_prompt_above_the_env_ceiling_builds_no_argv_and_starts_no_process(repo, home, cli, monkeypatch):
    monkeypatch.setenv(ENV_NAME, "1")
    result = run(repo, cli)
    assert (result.status, result.reason_code) == ("failed", "input_ceiling_exceeded")
    assert cli.built == [] and cli.started == []


def test_a_prompt_above_the_loop_toml_ceiling_builds_no_argv_and_starts_no_process(repo, home, cli):
    _write_toml(repo, f"{TOML_KEY} = 1\n")
    result = run(repo, cli)
    assert (result.status, result.reason_code) == ("failed", "input_ceiling_exceeded")
    assert cli.built == [] and cli.started == []


def test_the_ceiling_is_inclusive_at_the_projected_size(repo, home, cli, monkeypatch):
    run(repo, cli)
    (prompt,) = cli.built
    size = input_ceiling.Projection.estimated(prompt).tokens
    cli.built.clear()
    cli.started.clear()

    monkeypatch.setenv(ENV_NAME, str(size - 1))
    refused = run(repo, cli)
    assert refused.reason_code == "input_ceiling_exceeded"
    assert cli.built == [] and cli.started == []

    monkeypatch.setenv(ENV_NAME, str(size))
    sent = run(repo, cli)
    assert sent.reason_code != "input_ceiling_exceeded"
    assert len(cli.built) == 1 and len(cli.started) == 1


@pytest.mark.parametrize("value", ["abc", "0", "1000000000"])
def test_a_bad_env_ceiling_fails_loud_before_any_process(repo, home, cli, monkeypatch, value):
    monkeypatch.setenv(ENV_NAME, value)
    result = run(repo, cli)
    assert (result.status, result.reason_code) == ("failed", "ceiling_invalid")
    assert cli.built == [] and cli.started == []


def test_a_bad_loop_toml_ceiling_fails_loud_before_any_process(repo, home, cli):
    _write_toml(repo, f'{TOML_KEY} = "lots"\n')
    result = run(repo, cli)
    assert (result.status, result.reason_code) == ("failed", "ceiling_invalid")
    assert cli.built == [] and cli.started == []


def test_the_loop_toml_of_the_cwd_is_not_read(repo, home, cli):
    _write_working_toml(Path.cwd(), f"{TOML_KEY} = 1\n")
    result = run(repo, cli)
    assert result.status == "ok"
    assert len(cli.started) == 1


def test_a_correction_above_the_ceiling_starts_no_further_round(repo, home, cli, monkeypatch):
    """Verify keeps failing with a long output, so round 2 would resume with a correction prompt above the ceiling."""
    async def red_verify(argv, *, cwd, **_):
        if argv[0] == "sh":
            return SimpleNamespace(returncode=1, stdout="7 " * 3000, stderr="")  # digits are dear: the correction outweighs the prompt
        cli.started.append(list(argv))
        (Path(cwd) / f"edit-{uuid.uuid4().hex}.txt").write_text("ok\n")
        return SimpleNamespace(returncode=0, stdout=json.dumps(ENVELOPE), stderr="")

    def author():
        return asyncio.run(author_flow.run_author("fix it", repo, runner=red_verify, allow_unsandboxed=True, rounds=2,
                                                  verify="make test"))

    assert author().status == "failed" and len(cli.started) == 2
    size = input_ceiling.Projection.estimated(cli.built[0]).tokens
    cli.built.clear()
    cli.started.clear()

    monkeypatch.setenv(ENV_NAME, str(size))
    refused = author()
    assert (refused.status, refused.reason_code) == ("failed", "input_ceiling_exceeded")
    assert len(cli.built) == 1 and len(cli.started) == 1


def test_the_refusal_names_the_env_ceiling_source(repo, home, cli, monkeypatch):
    """A refused prompt says where its ceiling came from: the env var, with no reason (Parte de #1608)."""
    monkeypatch.setenv(ENV_NAME, "100")
    result = run(repo, cli, task="word " * 5000)
    assert result.reason_code == "input_ceiling_exceeded"
    failure = result.failures[0]
    assert failure["ceiling_source"] == "env " + ENV_NAME and failure["ceiling_reason"] == ""
    assert cli.built == [] and cli.started == []


def test_the_refusal_names_the_built_in_default_and_its_reason(repo, home, cli):
    """No remote, no env: the built-in 98,000 applies and the refusal says why (Parte de #1608)."""
    result = run(repo, cli, task="word " * 150_000)
    assert result.reason_code == "input_ceiling_exceeded"
    failure = result.failures[0]
    assert failure["ceiling_source"] == "built-in default"
    assert "origin/HEAD" in failure["ceiling_reason"]
    assert cli.built == [] and cli.started == []
