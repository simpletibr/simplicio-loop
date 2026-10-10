"""A second attempt on an issue whose `loop/issue-<N>` is already on origin (merged or closed PR) gets `-r2`, `-r3`, ... (real git).

Found on 2026-10-10: the push of the second attempt was rejected as non-fast-forward and the claim ended `dead`. No force push and
no remote deletion: the attempt just takes the first free name. `Item.head` is the one source of the branch name.
"""
from __future__ import annotations

import asyncio

from simplicio_loop import watcher_github
from simplicio_loop.watcher247 import tick, worktrees

from .test_worktrees import REPO, commit_in, git, real_repo  # noqa: F401  (real_repo is a fixture)


def _checkout(number=7, fix=False, head=None):
    """Run checkout() and return the Item as handed out and the branch its worktree is on inside the block."""
    seen = {}

    async def scenario():
        gate = worktrees.Gate(1)
        extra = {"head": head} if head else {}
        async with worktrees.checkout(gate, REPO, "main", number, fix=fix, **extra) as item:
            seen["branch"] = git("rev-parse", "--abbrev-ref", "HEAD", cwd=item.path)
            seen["item"] = item

    asyncio.run(scenario())
    return seen["item"], seen["branch"]


def test_a_branch_already_on_origin_makes_the_next_attempt_take_r2(real_repo):
    real_repo.advance(branch="loop/issue-7")
    item, branch = _checkout()
    assert item.head == "loop/issue-7-r2" and branch == "loop/issue-7-r2"
    assert item.created_branch is True


def test_r2_on_origin_too_makes_it_r3(real_repo):
    real_repo.advance(name="a.txt", branch="loop/issue-7")
    real_repo.advance(name="b.txt", branch="loop/issue-7-r2")
    item, branch = _checkout()
    assert item.head == "loop/issue-7-r3" and branch == "loop/issue-7-r3"


def test_a_gap_is_filled_by_the_first_free_name(real_repo):
    real_repo.advance(name="a.txt", branch="loop/issue-7")
    real_repo.advance(name="c.txt", branch="loop/issue-7-r3")  # r2 is free
    item, _ = _checkout()
    assert item.head == "loop/issue-7-r2"


def test_without_a_remote_branch_the_first_attempt_keeps_the_plain_name(real_repo):
    item, branch = _checkout()
    assert item.head == "loop/issue-7" and branch == "loop/issue-7"


def test_a_branch_of_another_issue_on_origin_does_not_count(real_repo):
    real_repo.advance(branch="loop/issue-70")  # `loop/issue-7*` is not `loop/issue-7`
    item, _ = _checkout()
    assert item.head == "loop/issue-7"


def test_a_review_fix_keeps_working_on_the_branch_of_its_open_pr(real_repo):
    real_repo.advance(branch="loop/issue-7")
    item, branch = _checkout(fix=True)
    assert item.head == "loop/issue-7" and branch == "loop/issue-7"


def test_a_review_fix_of_a_reattempt_pr_works_on_that_prs_branch(real_repo):
    real_repo.advance(name="a.txt", branch="loop/issue-7")
    real_repo.advance(name="b.txt", branch="loop/issue-7-r2")
    item, branch = _checkout(fix=True, head="loop/issue-7-r2")
    assert item.head == "loop/issue-7-r2" and branch == "loop/issue-7-r2"


def test_the_push_of_the_second_attempt_is_not_rejected_and_the_old_branch_is_untouched(real_repo):
    old = real_repo.advance(branch="loop/issue-7")

    async def scenario():
        gate = worktrees.Gate(1)
        async with worktrees.checkout(gate, REPO, "main", 7) as item:
            commit_in(item.path, "new.txt")
            done = await worktrees.push(gate, REPO, item.path, item.head)
            assert done.returncode == 0, done.stderr
            item.published = True
            return item.head

    head = asyncio.run(scenario())
    assert head == "loop/issue-7-r2"
    assert real_repo.origin_ref("refs/heads/loop/issue-7") == old  # no force push, no deletion
    assert real_repo.origin_ref(f"refs/heads/{head}")


def test_the_local_branch_cleanup_removes_the_new_head(real_repo):
    real_repo.advance(branch="loop/issue-7")

    async def scenario():
        gate = worktrees.Gate(1)
        async with worktrees.checkout(gate, REPO, "main", 7) as item:
            assert "loop/issue-7-r2" in real_repo.branches()
            item.published = True

    asyncio.run(scenario())
    assert real_repo.branches() == []


# --- the patrol maps a reattempt PR to its issue -------------------------------------------------------------------------------

def _patrol(monkeypatch, heads):
    async def found(*, repo, runner):
        return [watcher_github.FixTask(pr=100 + i, kind="review_comment", text=f"fix {head}", head=head) for i, head in enumerate(heads)]

    monkeypatch.setattr(watcher_github, "patrol_open_prs", found)
    fixes = {"queued": {}, "seen": []}
    asyncio.run(tick._enqueue_fixes(None, "demo", fixes))
    return fixes["queued"]


def test_the_patrol_maps_a_reattempt_pr_to_its_issue(monkeypatch):
    queued = _patrol(monkeypatch, ["loop/issue-7-r2"])
    assert list(queued) == ["demo#7"] and queued["demo#7"]["pr"] == 100


def test_the_patrol_maps_r10_and_the_plain_name_and_ignores_other_branches(monkeypatch):
    heads = ["loop/issue-8", "loop/issue-9-r10", "feature/issue-7", "loop/issue-7-x", "loop/issue-7-r", "loop/issue-7-r2-x",
             "xloop/issue-7-r2", "loop/issue-"]
    assert sorted(_patrol(monkeypatch, heads)) == ["demo#8", "demo#9"]


def test_a_fix_queued_from_a_reattempt_pr_remembers_the_pr_branch(monkeypatch):
    assert _patrol(monkeypatch, ["loop/issue-7-r2"])["demo#7"]["head"] == "loop/issue-7-r2"
