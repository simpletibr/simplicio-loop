"""ensure_state_dir keeps `.simplicio-loop/` out of `git status` using `.git/info/exclude`.

The engine uses the info/exclude file (which is untracked) to keep the state
directory invisible to git, ensuring reused clones don't appear dirty on
subsequent runs. The `.gitignore` file is never modified.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import turbo_provider
from simplicio_loop.cli_impl import main as cli_main
from simplicio_loop.state_dir import ensure_state_dir


def _git(path: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=True).stdout


def _repo(path: Path, gitignore: bytes | None = None) -> Path:
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "a@b.c")
    _git(path, "config", "user.name", "a")
    (path / "app.py").write_text("x = 1\n", encoding="utf-8")
    if gitignore is not None:
        (path / ".gitignore").write_bytes(gitignore)
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "seed")
    return path


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def test_a_gitignore_without_the_entry_is_not_modified(tmp_path):
    repo = _repo(tmp_path, b"*.log\n__pycache__/\n")
    original = (repo / ".gitignore").read_bytes()
    ensure_state_dir(repo)
    ensure_state_dir(repo)
    # .gitignore should not be modified
    assert (repo / ".gitignore").read_bytes() == original
    # .git/info/exclude should have the line
    assert _lines(repo / ".git" / "info" / "exclude").count(".simplicio-loop/") == 1


def test_covering_lines_in_gitignore_are_still_respected(tmp_path):
    # Even though we don't modify .gitignore, we still check for covering lines
    # to be a good citizen
    repo = _repo(tmp_path, b"*.log\n.simplicio-loop/\nbuild/\n")
    original = (repo / ".gitignore").read_bytes()
    ensure_state_dir(repo)
    # .gitignore should not be modified
    assert (repo / ".gitignore").read_bytes() == original


def test_a_gitignore_that_is_not_utf8_is_left_alone(tmp_path):
    original = b"caf\xe9/\n"
    repo = _repo(tmp_path, original)
    ensure_state_dir(repo)
    assert (repo / ".gitignore").read_bytes() == original and (repo / ".simplicio-loop").is_dir()


def test_without_a_gitignore_none_is_created_and_info_exclude_still_gets_the_line(tmp_path):
    repo = _repo(tmp_path)
    ensure_state_dir(repo)
    ensure_state_dir(repo)
    assert not (repo / ".gitignore").exists()
    assert _lines(repo / ".git" / "info" / "exclude").count(".simplicio-loop/") == 1
    assert _git(repo, "status", "--porcelain") == ""  # the state directory is invisible to git


def test_info_exclude_gets_the_line_and_gitignore_is_left_alone(tmp_path):
    repo = _repo(tmp_path, b"*.log\n")
    ensure_state_dir(repo)
    assert _lines(repo / ".git" / "info" / "exclude").count(".simplicio-loop/") == 1
    # .gitignore should not be modified
    assert _lines(repo / ".gitignore") == ["*.log"]


def test_a_gitignore_that_cannot_be_written_never_fails_the_run(tmp_path):
    repo = _repo(tmp_path, b"*.log\n")
    (repo / ".gitignore").chmod(0o444)
    try:
        assert ensure_state_dir(repo) == repo / ".simplicio-loop"
    finally:
        (repo / ".gitignore").chmod(0o644)


def test_this_repositorys_own_gitignore_already_covers_the_state_directory():
    """.simplicio-loop/* is a covering line, so the repo's .gitignore is fine as-is."""
    root = Path(__file__).resolve().parents[1]
    assert ".simplicio-loop/*" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()


# -- the turbo path calls it first ---------------------------------------------------------------------------------

@pytest.fixture
def no_provider(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("host mode called the provider")

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(turbo_provider, "complete", boom)


def _status(repo: Path) -> list[str]:
    return [line for line in _git(repo, "status", "--porcelain").splitlines()]


def test_a_turbo_apply_on_a_fresh_repo_registers_the_state_directory_before_writing_into_it(tmp_path, no_provider, capsys, monkeypatch):
    repo = _repo(tmp_path, b"*.log\n")
    assert not (repo / ".simplicio-loop").exists()
    import io

    class _Stdin:
        buffer = io.BytesIO(json.dumps({"operations": [{"path": "app.py", "find": "x = 1", "replace": "x = 2"}]}).encode())

        def isatty(self):
            return False

    monkeypatch.setattr(sys, "stdin", _Stdin())
    assert cli_main(["turbo", "--repo", str(repo), "--apply", "-"]) == 0
    capsys.readouterr()
    # .gitignore should not be modified
    assert (repo / ".gitignore").read_text() == "*.log\n"
    # Only app.py should show as modified
    assert sorted(_status(repo)) == [" M app.py"]


def test_a_blocked_turbo_call_creates_no_state_directory(tmp_path, no_provider, capsys):
    repo = _repo(tmp_path, b"*.log\n")
    assert cli_main(["turbo", "--repo", str(repo)]) == 2  # no task
    capsys.readouterr()
    assert not (repo / ".simplicio-loop").exists() and (repo / ".gitignore").read_text() == "*.log\n"


def test_a_turbo_call_on_a_missing_directory_creates_nothing(tmp_path, no_provider, capsys):
    ghost = tmp_path / "typo"
    cli_main(["turbo", "--repo", str(ghost), "--task", "Change x in app.py"])
    capsys.readouterr()
    assert not ghost.exists()



def test_a_turbo_request_and_apply_leave_no_simplicio_loop_path_in_git_status(tmp_path, no_provider, capsys, monkeypatch):
    """Tests that turbo doesn't add .simplicio-loop to git status and doesn't modify .gitignore."""
    repo = _repo(tmp_path, b"*.log\n")
    assert cli_main(["turbo", "--repo", str(repo), "--task", "Change x to 2 in app.py."]) == 0
    request = json.loads(capsys.readouterr().out)
    assert request["status"] == "needs_plan"
    assert (repo / ".simplicio-loop").is_dir() and (repo / ".simplicio-loop" / "project-map.json").is_file()
    # .gitignore should not be modified
    assert (repo / ".gitignore").read_text() == "*.log\n"
    # .git/info/exclude should have the line
    assert _lines(repo / ".git" / "info" / "exclude").count(".simplicio-loop/") == 1

    import io

    class _Stdin:
        buffer = io.BytesIO(json.dumps({"operations": [{"path": "app.py", "find": "x = 1", "replace": "x = 2"}]}).encode())

        def isatty(self):
            return False

    monkeypatch.setattr(sys, "stdin", _Stdin())
    assert cli_main(["turbo", "--repo", str(repo), "--apply", "-"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    # Only app.py should show as modified, not .gitignore
    assert sorted(_status(repo)) == [" M app.py"]


def test_a_provider_run_registers_the_state_directory_too(tmp_path, monkeypatch, capsys):
    """Tests that provider mode excludes the state dir and doesn't modify .gitignore."""
    repo = _repo(tmp_path, b"*.log\n")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    def fake_complete(arm, messages, **kwargs):
        plan = {"operations": [{"path": "app.py", "find": "x = 1", "replace": "x = 2"}]}
        return {"ok": True, "content": json.dumps(plan), "prompt_tokens": 10, "completion_tokens": 5}

    monkeypatch.setattr(turbo_provider, "complete", fake_complete)
    assert cli_main(["turbo", "--provider", "openrouter", "--repo", str(repo), "--task", "Change x to 2 in app.py."]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    # Only app.py should show as modified, not .gitignore
    assert sorted(_status(repo)) == [" M app.py"]
