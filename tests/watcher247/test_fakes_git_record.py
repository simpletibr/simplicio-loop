"""Contract of FakeRun: every git command it receives is recorded, in order, whatever it answers (#1649).

b6daeb40 taught the fake the squad_gate git commands; `ran(...)` must keep returning every call, and a ref that is not a fetched
remote ref must keep answering "does not exist", or worktrees.py believes the branch pre-existed and skips `git branch -D`.
"""
from __future__ import annotations

import asyncio

from .fakes import FakeRun


def _call(fake, *argv, cwd="/w"):
    return asyncio.run(fake(list(argv), cwd=cwd))


def test_worktree_remove_then_branch_delete_are_recorded_in_order(tmp_path):
    fake = FakeRun({})
    path = tmp_path / "wt"
    path.mkdir()
    fake.worktrees[path] = "loop/issue-1"
    _call(fake, "git", "worktree", "remove", "--force", str(path))
    _call(fake, "git", "branch", "-D", "x")
    assert fake.ran("git", "worktree", "remove") == [["git", "worktree", "remove", "--force", str(path)]]
    assert fake.ran("git", "branch", "-D", "x") == [["git", "branch", "-D", "x"]]
    assert [a[1] for a in fake.calls if a[0] == "git"] == ["worktree", "branch"]


def test_a_local_branch_does_not_exist_for_rev_parse():
    fake = FakeRun({})
    assert _call(fake, "git", "rev-parse", "--verify", "-q", "refs/heads/loop/issue-1").returncode != 0
    assert _call(fake, "git", "rev-parse", "--verify", "refs/remotes/origin/loop/issue-1^{commit}").returncode == 0
