"""#1601 guards that the first review's mutants (R01, R04, R06, R12, R13) showed were not pinned by any test.

R01 `_forget` without realpath, R04 the removal outside the repo lock, R06 the state saved with overwrite=False, R12 the push
outside the repo lock, R13 the tick never marks `item.published`. The real-git ones use test_worktrees.py's fixtures; the lock and
`published` ones run a whole tick against FakeRun and spy on which git calls run while the repo lock is held.
"""
from __future__ import annotations

import asyncio
import shutil

import pytest

from simplicio_loop.watcher247 import config, proc, worktrees

from .fakes import FakeRun, baseline, issue, run_tick
from .test_worktrees import REPO, real_repo, state_file  # noqa: F401  (real_repo is a fixture)

TICK_REPO = "simplicio-a"


# --- R01: the admin entry of a killed run is found when WORK sits behind a symlink ----------------------------------------------------

def test_a_killed_runs_entry_is_forgotten_when_the_work_dir_is_reached_through_a_symlink(real_repo, tmp_path, monkeypatch):
    real_work = config.WORK
    link = tmp_path / "state-link"
    link.symlink_to(tmp_path)  # config.WORK is now <link>/work: the same directory, spelled through a symlink
    monkeypatch.setattr(config, "WORK", link / "work")
    gate = worktrees.Gate(1)

    async def scenario():
        item = await worktrees._acquire(gate, REPO, "main", 31, False)
        shutil.rmtree(item.path)  # a SIGKILL: the directory is gone, the admin entry stays
        assert (real_work / REPO / ".git" / "worktrees" / "31").is_dir()
        await worktrees._drop(REPO, 31, item.path)
        return item

    item = asyncio.run(scenario())
    assert not (real_work / REPO / ".git" / "worktrees" / "31").exists(), "the entry of the killed run survived _drop"
    assert not item.path.exists()


def test_an_entry_whose_gitdir_is_spelled_through_a_symlink_is_still_found_and_forgotten(real_repo, tmp_path, monkeypatch):
    """The item can rewrite the `gitdir` file of its own admin entry: the same place spelled another way is still its entry."""
    real_work = config.WORK
    link = tmp_path / "state-link"
    link.symlink_to(tmp_path)
    monkeypatch.setattr(config, "WORK", link / "work")
    gate = worktrees.Gate(1)

    async def scenario():
        item = await worktrees._acquire(gate, REPO, "main", 31, False)
        entry = real_work / REPO / ".git" / "worktrees" / "31"
        shutil.rmtree(item.path)
        (entry / "gitdir").write_text(f"{item.path}/.git\n")  # through the link, whatever git wrote before
        assert (entry / "gitdir").read_text().strip() == f"{link}/work/{REPO}.wt/31/.git"
        await worktrees._drop(REPO, 31, item.path)

    asyncio.run(scenario())
    assert not (real_work / REPO / ".git" / "worktrees" / "31").exists()


# --- R06: every release saves the LATEST state, not the first ---------------------------------------------------------------------

def test_the_state_saved_at_release_is_the_latest_one_over_three_runs_of_the_same_issue(real_repo):
    gate = worktrees.Gate(1)
    seen: list[str | None] = []

    async def scenario():
        previous = None
        for rung in ("haiku", "sonnet", "opus"):  # the escalation ladder climbs one rung per reprocess
            async with worktrees.checkout(gate, REPO, "main", 1) as item:
                found = state_file(item.path, 1)
                seen.append(found.read_text().strip() if found.exists() else None)
                found.parent.mkdir(parents=True, exist_ok=True)
                found.write_text(rung + "\n")
            previous = rung
        return previous

    asyncio.run(scenario())
    assert seen == [None, "haiku", "sonnet"]  # each run found what the one before it left, not the first run's copy
    saved = worktrees.state_home(REPO, 1) / ".simplicio-loop" / "escalation-states" / "issue-1.json"
    assert saved.read_text().strip() == "opus"


# --- R04 / R12 / R13 at the tick level ----------------------------------------------------------------------------------------------

class LockSpy:
    """Which git calls ran while the repo lock of TICK_REPO was held. install() wraps whatever proc.run is installed by then."""

    def __init__(self, monkeypatch) -> None:
        self.monkeypatch = monkeypatch
        self.locks: dict[str, asyncio.Lock] = {}
        self.seen: list[tuple[tuple[str, ...], bool]] = []
        real_lock = worktrees.Gate.repo_lock

        def recording(gate, repo):
            self.locks[repo] = real_lock(gate, repo)
            return self.locks[repo]

        monkeypatch.setattr(worktrees.Gate, "repo_lock", recording)

    def install(self) -> None:
        inner = proc.run

        async def spy(argv, **kwargs):
            if argv[:1] == ["git"] and TICK_REPO in self.locks:
                self.seen.append((tuple(argv[1:3]), self.locks[TICK_REPO].locked()))
            return await inner(argv, **kwargs)

        self.monkeypatch.setattr(proc, "run", spy)

    def held(self, *prefix: str) -> list[bool]:
        found = [locked for argv, locked in self.seen if argv == prefix]
        assert found, f"git {' '.join(prefix)} never ran"
        return found


@pytest.fixture
def lock_spy(monkeypatch):
    return LockSpy(monkeypatch)


def test_removing_the_worktree_and_deleting_the_branch_happen_while_the_repo_lock_is_held(env, lock_spy):
    fake = env(FakeRun({TICK_REPO: [issue(1)]}, diff=True))
    lock_spy.install()
    baseline()
    run_tick()
    assert fake.ran("git", "worktree", "remove") and fake.ran("git", "branch", "-D")
    assert lock_spy.held("worktree", "remove") == [True]  # writes <common>/worktrees and the shared config
    assert lock_spy.held("branch", "-D") == [True]  # writes the shared .git/config


def test_the_push_of_the_item_happens_while_the_repo_lock_is_held(env, lock_spy):
    fake = env(FakeRun({TICK_REPO: [issue(1)]}, diff=True))
    lock_spy.install()
    baseline()
    run_tick()
    assert fake.push_cwds == [config.WORK / f"{TICK_REPO}.wt" / "1"]
    assert lock_spy.held("push", "-u") == [True]  # `git push -u` writes the shared .git/config


@pytest.mark.parametrize("diff, turbo_ok, branch_deleted", [
    (True, True, True),    # a PR was opened: the item's local branch (it made it) goes
    (False, True, False),  # no diff, no failure, no PR: the branch stays, as the rule says
    (True, False, True),   # the item failed: the branch goes
])
def test_the_ticks_item_marks_published_so_the_branch_of_an_opened_pr_is_deleted(env, diff, turbo_ok, branch_deleted):
    fake = env(FakeRun({TICK_REPO: [issue(1)]}, diff=diff, turbo_ok=turbo_ok))
    baseline()
    run_tick()
    assert bool(fake.ran("git", "branch", "-D", "loop/issue-1")) is branch_deleted


@pytest.mark.parametrize("code", [1, 128])
def test_an_ls_remote_that_fails_is_an_error_and_never_a_free_branch(monkeypatch, tmp_path, code):
    async def failing(argv, timeout=120, cwd=None, stdin=None, env=None):
        return proc.Result(code, "", "fatal: unable to access origin")
    monkeypatch.setattr(proc, "run", failing)
    with pytest.raises(RuntimeError, match="unable to access origin"):
        asyncio.run(worktrees._on_origin(tmp_path, "loop/issue-7"))
