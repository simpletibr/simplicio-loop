"""A plan the loop applies never names a path inside ``.git`` (issue #1565).

The loop applies plans through whichever ``simplicio-dev-cli`` is installed, and dev-cli versions before the fix wrote
``.git/hooks/*`` and ``.git/config`` without a word. A hook or a ``core.*`` line planted there runs outside every sandbox
with the token in the environment, so the loop refuses such a plan itself, before dev-cli is called, on every path a plan
enters by: host mode (``turbo --apply -``), the model-written plans of the provider modes and ``apply``'s ops.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from simplicio_loop import apply as loop_apply
from simplicio_loop import plan_paths, turbo, turbo_provider
from simplicio_loop.cli_impl import main as cli_main

GIT_PATHS = [
    ".git/hooks/pre-commit",
    ".git/config",
    ".git/info/exclude",
    ".git",
    "./.git/config",
    "sub/.git/hooks/pre-commit",
    "sub/../.git/config",
    ".GIT/hooks/pre-push",
    ".Git/config",
    ".git\\hooks\\pre-commit",
    "sub\\.git\\config",
    ".git./config",
    ".git /config",
    ".git.../config",
    "GIT~1/config",
    "git~1/hooks/pre-commit",
    ".g‌it/config",
    ".gi​t/config",
    "﻿.git/config",
]
ORDINARY_PATHS = [
    "app.py",
    "src/gitlib.py",
    ".gitignore",
    ".gitattributes",
    ".gitmodules",
    ".githubx/workflows/ci.yml",
    "docs/git-notes.md",
    "sub/.gitkeep",
    "my.git/x",
    "git/x",
    "gitt~1/x",
    ".githooksx/pre-commit",
    "a/.git-hooks/pre-commit",
    "área/código.py",
]


def _plan(path: str) -> str:
    return json.dumps({"operations": [{"path": path, "find": "", "replace": "planted\n"}]})


@pytest.mark.parametrize("path", GIT_PATHS)
def test_the_predicate_names_every_spelling_of_the_git_dir(path):
    assert plan_paths.inside_git_dir(path) is True


@pytest.mark.parametrize("path", ORDINARY_PATHS)
def test_the_predicate_leaves_ordinary_paths_alone(path):
    assert plan_paths.inside_git_dir(path) is False


@pytest.mark.parametrize("path", GIT_PATHS)
def test_a_host_plan_that_names_the_git_dir_is_refused_when_it_is_read(path):
    with pytest.raises(ValueError, match=r"\.git"):
        turbo.load_operations(_plan(path))


@pytest.mark.parametrize("path", GIT_PATHS)
def test_a_model_written_plan_that_names_the_git_dir_is_refused_when_it_is_parsed(path):
    fenced = "Here is the plan:\n```json\n" + _plan(path) + "\n```"
    with pytest.raises(ValueError, match=r"\.git"):
        turbo._parse_operations(fenced)


@pytest.mark.parametrize("path", ORDINARY_PATHS)
def test_ordinary_plans_still_load(path):
    assert turbo.load_operations(_plan(path))[0]["path"] == path


def test_one_bad_operation_refuses_the_whole_plan_and_names_which():
    plan = json.dumps({"operations": [
        {"path": "ok.py", "find": "", "replace": "x\n"},
        {"path": ".git/config", "find": "", "replace": "x\n"},
    ]})
    with pytest.raises(ValueError, match=r"operation 2"):
        turbo.load_operations(plan)


@pytest.mark.parametrize("path", GIT_PATHS)
def test_apply_refuses_an_ops_json_that_names_the_git_dir(path):
    ops = {"tasks": [{"id": "T1", "operations": [{"path": path, "find": "", "replace": "x\n"}]}]}
    with pytest.raises(loop_apply.ApplyValidationError, match=r"\.git"):
        loop_apply._normalize_tasks(ops)


@pytest.mark.parametrize("path", ORDINARY_PATHS)
def test_apply_still_accepts_ordinary_paths(path):
    ops = {"tasks": [{"id": "T1", "operations": [{"path": path, "find": "", "replace": "x\n"}]}]}
    assert loop_apply._normalize_tasks(ops)[0]["operations"][0]["path"] == path


class _Stdin:
    def __init__(self, data: str) -> None:
        import io
        self.buffer = io.BytesIO(data.encode("utf-8"))

    def isatty(self) -> bool:
        return False


@pytest.fixture
def repo(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("host mode called the provider")

    monkeypatch.setattr(turbo_provider, "complete", boom)
    monkeypatch.setattr(turbo_provider, "require_key", boom)
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", AsyncMock(return_value=None))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("old\n", encoding="utf-8")
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"],
                 ["add", "-A"], ["commit", "-qm", "seed"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "hooks-link").symlink_to(".git/hooks")
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    """Every file of the work tree plus the two places git runs code from (the loop itself keeps ``.git/info/exclude``)."""
    def watched(rel: str) -> bool:
        return not rel.startswith(".git/") and ".simplicio-loop" not in rel or rel == ".git/config" or rel.startswith(".git/hooks/")
    return {rel: p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and not p.is_symlink() and watched(rel := p.relative_to(root).as_posix())}


@pytest.mark.parametrize("path", [".git/hooks/post-commit", ".git/config", ".GIT/hooks/pre-push", ".git\\hooks\\post-commit"])
def test_turbo_apply_stdin_refuses_a_plan_into_git_and_dev_cli_is_never_called(repo, capsys, monkeypatch, path):
    called = []

    async def no_dev_cli(*args, **kwargs):
        called.append(args)
        raise AssertionError("dev-cli was called with a plan that names .git")

    monkeypatch.setattr(turbo, "_apply_operations", no_dev_cli)
    before = _snapshot(repo)
    monkeypatch.setattr(sys, "stdin", _Stdin(_plan(path)))
    rc = cli_main(["turbo", "--repo", str(repo), "--apply", "-"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == "turbo_plan_malformed"
    assert ".git" in out["detail"]
    assert called == [] and _snapshot(repo) == before


def test_turbo_apply_stdin_with_the_installed_dev_cli_writes_nothing_into_git(repo, capsys, monkeypatch):
    """No stub: whichever dev-cli is installed, the loop's own refusal keeps the hook out."""
    before = _snapshot(repo)
    for path in (".git/hooks/post-commit", ".GIT/hooks/post-commit", ".git/config"):
        monkeypatch.setattr(sys, "stdin", _Stdin(_plan(path)))
        rc = cli_main(["turbo", "--repo", str(repo), "--apply", "-"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 1 and out["status"] == "failed", (path, out)
    assert not (repo / ".git" / "hooks" / "post-commit").exists()
    assert _snapshot(repo) == before


@pytest.mark.parametrize("path", ["hooks-link/post-commit", "cfg-link"])
def test_turbo_apply_stdin_with_the_installed_dev_cli_writes_nothing_through_a_symlink_to_git(repo, capsys, monkeypatch, path):
    """The audit of #1571 (D1): a committed ``hooks-link -> .git/hooks`` reached ``.git`` through the 0.18.16 dev-cli."""
    (repo / "cfg-link").symlink_to(".git/config")
    before = _snapshot(repo)
    for find in ("", "zzz-not-in-the-file"):
        monkeypatch.setattr(sys, "stdin", _Stdin(json.dumps({"operations": [{"path": path, "find": find, "replace": "planted\n"}]})))
        rc = cli_main(["turbo", "--repo", str(repo), "--apply", "-"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 1 and out["status"] == "failed", (path, find, out)
        assert "[core]" not in json.dumps(out["failed"]), "a refused path must not echo the file it leads to"
    assert not (repo / ".git" / "hooks" / "post-commit").exists()
    assert _snapshot(repo) == before


def test_turbo_apply_stdin_still_applies_an_ordinary_plan(repo, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Stdin(_plan(".gitignore")))
    rc = cli_main(["turbo", "--repo", str(repo), "--apply", "-"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["status"] == "ok" and out["applied"] == [".gitignore"], out
    assert (repo / ".gitignore").read_text(encoding="utf-8") == "planted\n"
