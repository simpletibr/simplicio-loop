"""The state folder `.simplicio-loop/` keeps itself out of git, except `loop.toml`, the opt-in file the user commits.

Install writes `.simplicio-loop/.gitignore` with `*` and `!loop.toml`.

The file is owned by the ownership receipt, so uninstall removes it, and removes the folder when install created it.
A file that is already there with other content (the user's, or another command's) is left alone and not owned. The
project's own top-level `.gitignore` is never touched, so uninstall returns the project to its exact bytes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.install.planner import (
    InstallError,
    apply_plan,
    plan_install,
    uninstall,
)

IGNORE = Path(".simplicio-loop") / ".gitignore"
RECEIPT = Path(".simplicio-loop") / "install-ownership.json"
BODY = b"*\n!loop.toml\n"  # what install writes
OTHER_CONTENT = b"# another command\n*\n"


def make_bundle(root: Path) -> Path:
    skill = root / "skills" / "simplicio-loop"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("loop\n", encoding="utf-8")
    (root / "hooks").mkdir()
    for name in ("loop_stop.py", "action_gate.py", "orient_rewrite.py"):
        (root / "hooks" / name).write_text("# hook\n", encoding="utf-8")
    return root


def write(path: Path, data: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return path


def install(root: Path, bundle: Path) -> dict:
    return apply_plan(plan_install(root, host="claude"), bundle=bundle)


def snapshot(root: Path) -> dict:
    """Every path under `root`: the bytes of each file, None for each directory. Equal snapshots mean byte-identical."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


def receipt_paths(root: Path) -> list:
    return json.loads((root / RECEIPT).read_text(encoding="utf-8"))["paths"]


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    return make_bundle(tmp_path / "bundle")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    folder = tmp_path / "repo"
    folder.mkdir()
    return folder


def test_install_writes_a_state_folder_gitignore_that_hides_the_state_but_not_loop_toml(repo, bundle):
    install(repo, bundle)
    assert (repo / IGNORE).read_bytes() == b"*\n!loop.toml\n"
    assert IGNORE.as_posix() in receipt_paths(repo), "install owns the file it writes, so uninstall removes it"


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_after_install_git_status_lists_nothing_under_the_state_folder(repo, bundle):
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    install(repo, bundle)
    done = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, text=True, check=True,
    )
    assert ".claude/skills/simplicio-loop/SKILL.md" in done.stdout, "the install's own files are listed: not vacuous"
    assert [line for line in done.stdout.splitlines() if ".simplicio-loop" in line] == []


def git_status(root: Path) -> list:
    done = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, text=True, check=True,
    )
    return done.stdout.splitlines()


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
@pytest.mark.parametrize("loop_toml_first", [True, False], ids=["loop-toml-before-install", "loop-toml-after-install"])
def test_a_loop_toml_the_user_writes_is_untracked_and_the_receipt_is_not(repo, bundle, loop_toml_first):
    """`loop.toml` is the opt-in file: the watcher reads it from the default branch, so git must offer it for commit."""
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    if loop_toml_first:
        write(repo / ".simplicio-loop" / "loop.toml", "enabled = true\n")
        install(repo, bundle)
    else:
        install(repo, bundle)
        write(repo / ".simplicio-loop" / "loop.toml", "enabled = true\n")
    lines = git_status(repo)
    assert "?? .simplicio-loop/loop.toml" in lines
    assert all("install-ownership.json" not in line and ".simplicio-loop/.gitignore" not in line for line in lines)


def test_uninstall_removes_the_state_folder_gitignore_and_the_folder_install_created(repo, bundle):
    install(repo, bundle)
    uninstall(repo)
    assert not (repo / ".simplicio-loop").exists()


@pytest.mark.parametrize("with_user_gitignore", [False, True], ids=["no-gitignore", "user-gitignore"])
def test_uninstall_returns_the_project_to_its_exact_bytes(repo, bundle, with_user_gitignore):
    write(repo / "src" / "app.py", "print('hi')\n")
    if with_user_gitignore:
        write(repo / ".gitignore", "node_modules/\n*.log")  # no final newline: the bytes are kept exactly
    before = snapshot(repo)
    install(repo, bundle)
    uninstall(repo)
    assert snapshot(repo) == before


def test_a_state_folder_gitignore_with_other_content_is_left_alone_and_not_owned(repo, bundle):
    write(repo / IGNORE, OTHER_CONTENT)
    result = install(repo, bundle)
    assert (repo / IGNORE).read_bytes() == OTHER_CONTENT
    assert IGNORE.as_posix() in result["changes"]["left_alone"]
    assert IGNORE.as_posix() not in receipt_paths(repo)
    uninstall(repo)
    assert (repo / IGNORE).read_bytes() == OTHER_CONTENT


def test_a_state_folder_gitignore_already_holding_the_rule_is_not_owned_either(repo, bundle):
    write(repo / IGNORE, BODY)
    result = install(repo, bundle)
    assert IGNORE.as_posix() in result["changes"]["left_alone"]
    assert IGNORE.as_posix() not in receipt_paths(repo)
    uninstall(repo)
    assert (repo / IGNORE).read_bytes() == BODY, "a file install did not create is never removed"


def test_a_state_folder_gitignore_the_user_edits_is_no_longer_owned_by_the_next_install(repo, bundle):
    install(repo, bundle)
    write(repo / IGNORE, b"*\n!loop.toml\n!dashboard.toml\n")
    result = install(repo, bundle)
    assert IGNORE.as_posix() in result["changes"]["left_alone"]
    assert IGNORE.as_posix() not in receipt_paths(repo)
    uninstall(repo)
    assert (repo / IGNORE).read_bytes() == b"*\n!loop.toml\n!dashboard.toml\n"


def test_a_second_install_creates_and_updates_nothing(repo, bundle):
    install(repo, bundle)
    second = install(repo, bundle)
    assert second["changes"]["created"] == []
    assert second["changes"]["updated"] == []
    assert second["up_to_date"] is True


def test_install_check_is_clean_right_after_install(repo, bundle):
    install(repo, bundle)
    check = apply_plan(plan_install(repo, host="claude"), dry_run=True, bundle=bundle)
    assert check["up_to_date"] is True


def test_a_second_uninstall_refuses_and_changes_nothing(repo, bundle):
    install(repo, bundle)
    uninstall(repo)
    before = snapshot(repo)
    with pytest.raises(InstallError, match="no Loop ownership receipt"):
        uninstall(repo)
    assert snapshot(repo) == before


def test_install_uninstall_install_uninstall_returns_the_same_bytes(repo, bundle):
    write(repo / ".gitignore", "build/\n")
    before = snapshot(repo)
    install(repo, bundle)
    uninstall(repo)
    install(repo, bundle)
    uninstall(repo)
    assert snapshot(repo) == before


def test_uninstall_keeps_a_state_folder_that_holds_files_install_did_not_write(repo, bundle):
    write(repo / ".simplicio-loop" / "loop.toml", "enabled = true\n")
    before = snapshot(repo)
    install(repo, bundle)
    uninstall(repo)
    assert snapshot(repo) == before
