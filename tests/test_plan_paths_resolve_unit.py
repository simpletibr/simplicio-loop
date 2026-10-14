"""A plan path is checked where it lands, not only as text (issue #1565, audit of #1571, D1 and D3).

``plan_paths`` used to read the plan path as text only. A repository may commit ``ln -s .git link`` (git versions a
symlink without looking at its target) and a plan that names ``link/hooks/pre-commit`` then writes ``.git/hooks/pre-commit``
through a ``simplicio-dev-cli`` that predates its own symlink check (0.18.16). The loop therefore resolves the path
against the real repository, with real symlinks here, and refuses what lands inside ``.git`` or outside the root. It
also refuses absolute paths, ``..``, drive letters and ``:`` before anything is read, so a plan cannot ask the loop
whether ``/etc/passwd`` exists or how many times a word occurs in it. A plan cannot create a symlink (it only creates
and edits text files), so a link made by the same plan is not a case. Only fake data lives here.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import apply as loop_apply
from simplicio_loop import plan_paths, turbo

GIT_LINKS = [
    "link/hooks/pre-commit",
    "link/config",
    "link/new/deeper/hook",
    "link",
    "./link/config",
    "cfg",
    "sub/link/hooks/post-commit",
    "sub/link",
    "l1/hooks/pre-push",
    "l1",
    "hk/pre-commit",
    "hk",
    "dangling",
    "chain3/hooks/x",
    "up/repo/.git/config",
]
OUTSIDE = ["out/file.txt", "out/new/file.txt", "out", "outfile", "up/outside/x", "up/other/new.py"]
ALLOWED = [
    "app.py",
    "src/a.txt",
    "src/new/deeper/file.py",
    ".gitignore",
    ".gitattributes",
    ".github/workflows/x.yml",
    "srcln/a.txt",
    "srcln/new.txt",
    "appln",
    "up/repo/new.py",
    "área/código.py",
    "a..b/c.py",
    "..git/x",
]
# Each of these is refused as text, before the file system is asked anything.
UNSAFE = [
    "/etc/passwd",
    "/",
    "../../../etc/hostname",
    "..",
    "a/../b",
    "a/..",
    "..\\x",
    "C:\\Windows\\win.ini",
    "C:/x",
    "c:x",
    "a:b",
    "app.py::$DATA",
    "\\\\server\\share\\x",
    "\\x",
    ".",
]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path) -> Path:
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "file.txt").write_text("outside\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8")
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "sub").mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "app.py").write_text("old\n", encoding="utf-8")
    (root / "src" / "a.txt").write_text("a\n", encoding="utf-8")
    (root / ".github" / "workflows" / "x.yml").write_text("on: push\n", encoding="utf-8")
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"]):
        _git(root, *args)
    links = {
        "link": ".git", "cfg": ".git/config", "sub/link": "../.git", "hk": ".git/hooks",
        "l1": "l2", "l2": ".git", "chain3": "c2", "c2": "c1", "c1": ".git",
        "dangling": ".git/hooks/not-there-yet",
        "out": str(tmp_path / "outside"), "outfile": "../outside.txt", "up": "..",
        "srcln": "src", "appln": "app.py", "loop1": "loop2", "loop2": "loop1",
    }
    for name, target in links.items():
        os.symlink(target, root / name)
    _git(root, "add", "-A")  # git versions a symlink without looking at where it points
    _git(root, "commit", "-qm", "seed")
    return root


@pytest.mark.parametrize("path", GIT_LINKS)
def test_a_path_that_lands_inside_git_through_a_symlink_is_refused(repo, path):
    reason = plan_paths.refusal(path, repo)
    assert reason is not None and ".git" in reason


@pytest.mark.parametrize("path", OUTSIDE)
def test_a_path_that_lands_outside_the_root_through_a_symlink_is_refused(repo, path):
    reason = plan_paths.refusal(path, repo)
    assert reason is not None and "outside" in reason


@pytest.mark.parametrize("path", ALLOWED)
def test_a_symlink_to_an_ordinary_place_inside_the_repo_stays_allowed(repo, path):
    assert plan_paths.refusal(path, repo) is None


def test_a_symlink_loop_does_not_crash_the_guard(repo):
    assert plan_paths.refusal("loop1/x", repo) is None or isinstance(plan_paths.refusal("loop1/x", repo), str)


def test_the_root_may_sit_behind_a_symlink_and_below_a_dir_called_git(tmp_path):
    real = tmp_path / ".git-lookalike" / "repo"
    real.mkdir(parents=True)
    (real / "app.py").write_text("x\n", encoding="utf-8")
    os.symlink(real, tmp_path / "alias")
    assert plan_paths.refusal("app.py", tmp_path / "alias") is None
    assert plan_paths.refusal("new/file.py", tmp_path / "alias") is None
    below_git = tmp_path / ".git" / "checkout"
    below_git.mkdir(parents=True)
    assert plan_paths.refusal("new/file.py", below_git) is None


def test_without_a_root_only_the_text_is_checked():
    assert plan_paths.refusal("link/config") is None
    assert plan_paths.refusal(".git/config") is not None


def test_operations_name_both_path_and_dest(repo):
    move = [{"op": "move_file", "path": "app.py", "dest": "link/hooks/pre-commit"}]
    assert plan_paths.operations_refusal(move, repo) is not None
    assert plan_paths.operations_refusal([{"path": "app.py", "find": "old", "replace": "new"}], repo) is None
    assert plan_paths.operations_refusal([{"path": "cfg", "find": "", "replace": "x"}], repo) is not None


def test_a_plan_is_read_under_every_key_the_runner_accepts(repo):
    for key in ("operations", "ops", "edits"):
        assert plan_paths.plan_refusal({key: [{"path": "link/config"}]}, repo) is not None
        assert plan_paths.plan_refusal({key: [{"path": "app.py", "dest": ".git/HEAD"}]}, repo) is not None
        assert plan_paths.plan_refusal({key: [{"path": "app.py"}]}, repo) is None
    assert plan_paths.plan_refusal({"operations": "no"}, repo) is None
    assert plan_paths.plan_refusal({"operations": [None, 3, {"path": 4}]}, repo) is None


@pytest.mark.parametrize("path", UNSAFE)
def test_an_absolute_path_a_dotdot_a_drive_or_a_colon_is_refused_as_text(path):
    reason = plan_paths.refusal(path)
    assert reason is not None and reason.startswith("unsafe_path")


@pytest.mark.parametrize("path", [*UNSAFE, "", "   ", "a\0b"])
def test_the_unsafe_reason_says_nothing_about_the_file(path):
    reason = plan_paths.refusal(path) or ""
    assert reason.startswith("unsafe_path")
    assert "count" not in reason and "not found" not in reason and "exist" not in reason


@pytest.mark.parametrize("path", UNSAFE)
def test_a_host_plan_with_an_unsafe_path_is_refused_when_it_is_read(path):
    with pytest.raises(ValueError, match="unsafe_path"):
        turbo.load_operations(json.dumps({"operations": [{"path": path, "find": "root", "replace": "x"}]}))


@pytest.mark.parametrize("path", UNSAFE)
def test_apply_refuses_an_unsafe_path_when_it_reads_ops_json(path):
    ops = {"tasks": [{"id": "T1", "operations": [{"path": path, "find": "root", "replace": "x"}]}]}
    with pytest.raises(loop_apply.ApplyValidationError, match="unsafe_path"):
        loop_apply._normalize_tasks(ops)


def _task(path: str, find: str = "root") -> dict:
    return {"id": "T1", "operations": [{"path": path, "find": find, "replace": "x"}], "depends_on": [], "check": None}


@pytest.mark.parametrize("path", ["/etc/passwd", "../../../etc/hostname", "out/file.txt", "link/config", "cfg"])
def test_validate_ops_answers_the_same_for_every_unsafe_path_and_reads_nothing(repo, path, monkeypatch):
    def no_read(self, *args, **kwargs):
        raise AssertionError(f"validate_ops read {self}")

    monkeypatch.setattr(Path, "read_text", no_read)
    problems = loop_apply.validate_ops(repo, [_task(path)], [["T1"]])
    assert problems == [{"task": "T1", "path": path, "op_index": 0, "reason": "unsafe_path"}]


def test_validate_ops_still_checks_an_ordinary_path(repo):
    assert loop_apply.validate_ops(repo, [_task("app.py", "old")], [["T1"]]) == []
    assert loop_apply.validate_ops(repo, [_task("appln", "old")], [["T1"]]) == []
    assert loop_apply.validate_ops(repo, [_task("app.py", "nope")], [["T1"]])[0]["reason"] == "find_not_found"


@pytest.fixture
def fake_dev_cli(tmp_path) -> tuple[str, Path]:
    """A dev-cli that predates the symlink check would write wherever the path leads. This one only records its call."""
    calls = tmp_path / "dev-cli-calls.txt"
    script = tmp_path / "old-dev-cli"
    script.write_text(f"#!{sys.executable}\nimport sys\nopen({str(calls)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n",
                      encoding="utf-8")
    script.chmod(0o755)
    return str(script), calls


@pytest.mark.parametrize("path", ["link/hooks/pre-commit", "cfg", "hk/post-commit", "out/file.txt", "dangling"])
def test_apply_plan_never_calls_dev_cli_for_a_path_that_lands_in_git_or_outside(repo, fake_dev_cli, path):
    binary, calls = fake_dev_cli
    result = asyncio.run(turbo.apply_plan(repo, [{"path": path, "find": "", "replace": "planted\n"}], "t", binary))
    assert result["applied"] is False
    assert ".git" in result["reason"] or "outside" in result["reason"]
    assert not calls.exists()


def test_apply_plan_still_calls_dev_cli_for_an_ordinary_path_through_a_symlink(repo, fake_dev_cli):
    binary, calls = fake_dev_cli
    asyncio.run(turbo.apply_plan(repo, [{"path": "srcln/a.txt", "find": "a", "replace": "b"}], "t", binary))
    assert calls.exists() and "--compile" in calls.read_text(encoding="utf-8")


def test_a_second_operation_into_git_refuses_the_whole_plan(repo, fake_dev_cli):
    binary, calls = fake_dev_cli
    ops = [{"path": "app.py", "find": "old", "replace": "new"}, {"path": "link/config", "find": "", "replace": "x"}]
    assert asyncio.run(turbo.apply_plan(repo, ops, "t", binary))["applied"] is False
    assert not calls.exists() and (repo / "app.py").read_text(encoding="utf-8") == "old\n"


@pytest.mark.parametrize("path", ["link/hooks/pre-commit", "cfg", "hk/x"])
def test_apply_task_refuses_a_path_that_lands_in_git_before_it_spawns_anything(repo, tmp_path, monkeypatch, path):
    def no_spawn(*args, **kwargs):
        raise AssertionError("dev-cli was spawned for a path that lands in .git")

    monkeypatch.setattr(loop_apply.subprocess, "run", no_spawn)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    task = {"id": "T1", "operations": [{"path": path, "find": "", "replace": "x"}]}
    result = loop_apply._apply_task_devcli(repo, task, run_dir)
    assert result["ok"] is False and result["reason_code"] == "unsafe_path"
    assert ".git" in result["steps"][0]["error"]
