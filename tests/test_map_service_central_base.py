"""The central base is the default branch of the repository, never a worktree's own branch (#1574)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from simplicio_loop.map_service_git import (
    git_common_dir,
    merge_base_tree,
    resolve_default_base,
    resolve_repository_identity,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _repo(root: Path, branch: str = "main") -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", branch)
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _with_origin(root: Path, tmp_path: Path, branch: str) -> None:
    remote = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", branch, str(remote))
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-q", "origin", branch)
    _git(root, "remote", "set-head", "origin", branch)


def test_linked_worktree_on_a_feature_branch_still_resolves_the_default_branch(tmp_path):
    root = _repo(tmp_path / "repo")
    feature = tmp_path / "feature"
    _git(root, "worktree", "add", "-q", "-b", "feature/x", str(feature))

    # Before the fix the worktree's own branch was reported as "the default branch".
    assert resolve_repository_identity(str(feature)).default_branch == "main"
    base = resolve_default_base(str(feature))
    assert base is not None
    assert base.branch == "main"


def test_origin_head_wins_over_a_local_main(tmp_path):
    root = _repo(tmp_path / "repo", branch="trunk")
    _with_origin(root, tmp_path, "trunk")
    _git(root, "branch", "main")  # a decoy: origin/HEAD says trunk
    base = resolve_default_base(str(root))
    assert base is not None and base.branch == "trunk"
    assert base.ref == "refs/remotes/origin/trunk"


def test_falls_back_to_master_when_there_is_no_origin_and_no_main(tmp_path):
    root = _repo(tmp_path / "repo", branch="master")
    base = resolve_default_base(str(root))
    assert base is not None and base.branch == "master"
    assert base.ref == "refs/heads/master"


def test_no_default_branch_candidate_resolves_to_none(tmp_path):
    root = _repo(tmp_path / "repo", branch="work")
    assert resolve_default_base(str(root)) is None


def test_detached_head_resolves_the_same_base(tmp_path):
    root = _repo(tmp_path / "repo")
    head = _git(root, "rev-parse", "HEAD")
    detached = tmp_path / "detached"
    _git(root, "worktree", "add", "-q", "--detach", str(detached), head)
    assert resolve_default_base(str(detached)) == resolve_default_base(str(root))


def test_base_depends_only_on_the_default_branch_tree_not_on_worktree_edits(tmp_path):
    root = _repo(tmp_path / "repo")
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "-b", "feature", str(wt))
    before = resolve_default_base(str(wt))
    (wt / "a.py").write_text("def a():\n    return 2\n", encoding="utf-8")
    (wt / "new.py").write_text("x = 1\n", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-qm", "work")
    (wt / "a.py").write_text("def a():\n    return 3\n", encoding="utf-8")
    after = resolve_default_base(str(wt))
    assert before == after
    assert before.tree == _git(root, "rev-parse", "main^{tree}")
    assert before.commit == _git(root, "rev-parse", "main")


def test_every_worktree_shares_one_common_dir(tmp_path):
    root = _repo(tmp_path / "repo")
    a, b = tmp_path / "a", tmp_path / "b"
    _git(root, "worktree", "add", "-q", "-b", "fa", str(a))
    _git(root, "worktree", "add", "-q", "-b", "fb", str(b))
    common = {git_common_dir(str(path)) for path in (root, a, b)}
    assert common == {(root / ".git").resolve()}


def test_merge_base_tree_follows_the_worktree_fork_point(tmp_path):
    root = _repo(tmp_path / "repo")
    old_tree = _git(root, "rev-parse", "HEAD^{tree}")
    old = tmp_path / "old"
    _git(root, "worktree", "add", "-q", "-b", "old", str(old))
    (root / "b.py").write_text("b = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "main moves on")
    base = resolve_default_base(str(root))
    assert base is not None
    assert merge_base_tree(str(old), base.ref) == old_tree
    assert merge_base_tree(str(root), base.ref) == base.tree
