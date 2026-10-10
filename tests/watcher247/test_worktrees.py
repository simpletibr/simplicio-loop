"""#1601: one git worktree per item, tested against REAL git (no FakeRun, no fake of proc.run's behaviour).

Every test builds a bare origin with a commit on `main`, a shallow BASE clone at config.WORK/<repo> (so `gh` is never called) and
then drives worktrees.checkout/_acquire/_release/_drop/push with a real worktrees.Gate. The asserts read the state of git itself:
`git worktree list --porcelain`, the entries under `<common>/worktrees`, `git branch --list`, HEAD, the origin refs.
The tick-level wiring (FakeRun) is in test_tick_parallel.py.
"""
from __future__ import annotations

import ast
import asyncio
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from simplicio_loop import squad_capacity
from simplicio_loop.watcher247 import __main__ as watcher_main
from simplicio_loop.watcher247 import config, points, proc, sandbox, squad_flow, tick, worktrees

from .fakes import issue
from .sandbox_rig import needs_bwrap

REPO = "demo"
WAIT = 20  # seconds: the ceiling of every wait on an Event; a healthy run is far below it
LOOP_TOML = 'enabled = true\nverify = "python3 -m pytest -q"\n'


# --- real git helpers -------------------------------------------------------------------------------------------------------------

def git(*args: str, cwd: Path) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(args)} in {cwd}: {done.stderr.strip()}"
    return done.stdout.strip()


def git_rc(*args: str, cwd: Path) -> int:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).returncode


def listing(base: Path) -> list[dict]:
    """`git worktree list --porcelain` as dicts (key -> value, a bare flag such as `detached` -> ""); the base clone is first."""
    rows = []
    for block in git("worktree", "list", "--porcelain", cwd=base).split("\n\n"):
        if not block.strip():
            continue
        row = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            row[key] = value
        row["path"] = Path(row.pop("worktree"))
        rows.append(row)
    return rows


@dataclass
class Repo:
    name: str
    origin: Path
    seed: Path
    base: Path

    @property
    def common(self) -> Path:
        return self.base / ".git"

    def wt(self, number: int) -> Path:
        return config.WORK / f"{self.name}.wt" / str(number)

    def rows(self) -> dict[Path, dict]:
        """The item worktrees git knows (the base clone left out), by resolved path."""
        return {row["path"].resolve(): row for row in listing(self.base)[1:]}

    def entries(self) -> list[str]:
        folder = self.common / "worktrees"
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    def branches(self) -> list[str]:
        return git("branch", "--list", "loop/*", "--format=%(refname:short)", cwd=self.base).split()

    def advance(self, name: str = "fresh.txt", text: str = "fresh\n", branch: str = "main") -> str:
        """A new commit on the origin's `branch`; returns its sha."""
        if branch != "main":
            git("checkout", "-q", "-b", branch, "main", cwd=self.seed)
        (self.seed / name).parent.mkdir(parents=True, exist_ok=True)
        (self.seed / name).write_text(text)
        git("add", "-A", cwd=self.seed)
        git("commit", "-q", "-m", f"advance {name}", cwd=self.seed)
        git("push", "-q", "origin", branch, cwd=self.seed)
        sha = git("rev-parse", "HEAD", cwd=self.seed)
        if branch != "main":
            git("checkout", "-q", "main", cwd=self.seed)
        return sha

    def origin_ref(self, ref: str) -> str:
        return git("rev-parse", "--verify", "-q", ref, cwd=self.origin)


def commit_in(path: Path, name: str, text: str = "x\n") -> str:
    (path / name).write_text(text)
    git("add", name, cwd=path)
    git("commit", "-q", "-m", f"add {name}", cwd=path)
    return git("rev-parse", "HEAD", cwd=path)


@pytest.fixture
def real_repo(tmp_path, monkeypatch):
    """A bare origin with `main`, a shallow base clone at config.WORK/demo, and nothing of the user's global git."""
    home = tmp_path / "home"
    home.mkdir()
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    for key, value in {
        "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "GIT_CONFIG_GLOBAL": str(empty),
        "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "tester", "GIT_AUTHOR_EMAIL": "tester@example.invalid",
        "GIT_COMMITTER_NAME": "tester", "GIT_COMMITTER_EMAIL": "tester@example.invalid",
    }.items():
        monkeypatch.setenv(key, value)
    for stale in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(stale, raising=False)
    monkeypatch.setattr(config, "WORK", tmp_path / "work")

    async def plenty(path):  # the disk is the test of its own (test_disk_*); the others must not depend on this host's free space
        return 1 << 40

    monkeypatch.setattr(worktrees, "free_bytes", plenty)
    origin, seed = tmp_path / "origin.git", tmp_path / "seed"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("init", "-q", "-b", "main", str(seed), cwd=tmp_path)
    for name, text in {"README.md": "demo\n", "src/app.py": "print('app')\n", "src/lib.py": "X = 1\n",
                       ".simplicio-loop/loop.toml": LOOP_TOML}.items():
        (seed / name).parent.mkdir(parents=True, exist_ok=True)
        (seed / name).write_text(text)
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "seed", cwd=seed)
    git("remote", "add", "origin", str(origin), cwd=seed)
    git("push", "-q", "origin", "main", cwd=seed)
    base = config.WORK / REPO
    base.parent.mkdir(parents=True)
    git("clone", "-q", "--depth", "1", f"file://{origin}", str(base), cwd=tmp_path)
    return Repo(REPO, origin, seed, base)


@pytest.fixture
def sigterm_guard():
    """A python-level SIGTERM handler for the test: a watcher whose handler is missing must fail the test, never kill pytest."""
    hits: list[int] = []
    previous = signal.signal(signal.SIGTERM, lambda signum, frame: hits.append(signum))
    try:
        yield hits
    finally:
        signal.signal(signal.SIGTERM, previous if previous is not None else signal.SIG_DFL)


async def until(event: asyncio.Event, what: str = "event") -> None:
    try:
        await asyncio.wait_for(event.wait(), WAIT)
    except asyncio.TimeoutError:
        raise AssertionError(f"timed out waiting for {what}") from None


async def forever() -> None:
    await asyncio.wait_for(asyncio.Event().wait(), WAIT)


# --- 1/2: leftovers of a killed run, and the gitdir of the neighbour -------------------------------------------------------------

def test_a_killed_runs_leftover_is_recreated_and_the_neighbours_entry_is_left_alone(real_repo):
    r, gate = real_repo, worktrees.Gate(2)

    async def scenario():
        one = await worktrees._acquire(gate, REPO, "main", 1, False)
        ten = await worktrees._acquire(gate, REPO, "main", 10, False)
        assert r.entries() == ["1", "10"] and set(r.rows()) == {r.wt(1).resolve(), r.wt(10).resolve()}
        marker = r.common / "worktrees" / "1" / "stale-marker"
        marker.write_text("the entry of the killed run")
        shutil.rmtree(one.path)  # a SIGKILL: the directories are gone, the admin entries in <common>/worktrees stay
        shutil.rmtree(ten.path)
        before = r.rows()
        assert set(before) == {r.wt(1).resolve(), r.wt(10).resolve()}
        assert all("prunable" in row for row in before.values())  # `git worktree prune` WOULD forget both of them now
        async with worktrees.checkout(gate, REPO, "main", 1) as item:
            assert item.path == r.wt(1) and item.path.is_dir()
            assert not marker.exists()  # the old entry of 1 was cleaned and a fresh one made
            rows = r.rows()
            assert "prunable" not in rows[r.wt(1).resolve()] and "detached" not in rows[r.wt(1).resolve()]
            assert "prunable" in rows[r.wt(10).resolve()]  # 10 is not ours: still there, still dangling
            assert r.entries() == ["1", "10"]

    asyncio.run(scenario())
    after = r.rows()
    assert list(after) == [r.wt(10).resolve()] and "prunable" in after[r.wt(10).resolve()]
    assert r.entries() == ["10"]
    assert (r.common / "worktrees" / "10" / "gitdir").read_text().strip() == str(r.wt(10) / ".git")


def test_a_neighbour_whose_number_starts_like_ours_is_never_touched(real_repo):
    """`<wt>/1` is a textual prefix of `<wt>/10`: the gitdir is compared for equality, never by prefix."""
    r, gate = real_repo, worktrees.Gate(2)

    async def scenario():
        ten = await worktrees._acquire(gate, REPO, "main", 10, False)
        async with worktrees.checkout(gate, REPO, "main", 1):  # acquire drops the leftover of 1 (there is none) ...
            assert r.entries() == ["1", "10"]
        assert r.entries() == ["10"]  # ... and the release drops 1 only
        assert ten.path.is_dir() and git_rc("status", "--porcelain", cwd=ten.path) == 0
        assert git("rev-parse", "--is-inside-work-tree", cwd=ten.path) == "true"
        await worktrees._drop(REPO, 1, r.wt(1))  # nothing of 1 is left: a no-op that must not reach 10
        assert r.entries() == ["10"] and git_rc("status", "--porcelain", cwd=ten.path) == 0
        # the other way round: 1 is live and 10 goes
        one = await worktrees._acquire(gate, REPO, "main", 1, False)
        await worktrees._drop(REPO, 10, ten.path)
        assert r.entries() == ["1"] and not ten.path.exists()
        assert one.path.is_dir() and git_rc("status", "--porcelain", cwd=one.path) == 0
        # 10 is a dangling leftover (directory gone, entry stays): dropping 1 keeps its entry
        ten = await worktrees._acquire(gate, REPO, "main", 10, False)
        shutil.rmtree(ten.path)
        await worktrees._drop(REPO, 1, one.path)
        assert r.entries() == ["10"] and not one.path.exists()
        await worktrees._drop(REPO, 10, ten.path)
        assert r.entries() == []

    asyncio.run(scenario())


@pytest.mark.parametrize("name", ["neighbour-10", "base-clone", "inside-the-item", "other-repo"])
def test_drop_refuses_any_path_that_is_not_the_items_and_removes_nothing(real_repo, name):
    r, gate = real_repo, worktrees.Gate(2)
    paths = {"neighbour-10": r.wt(10), "base-clone": r.base, "inside-the-item": r.wt(1) / "src",
             "other-repo": config.WORK / "other.wt" / "1"}

    async def scenario():
        one = await worktrees._acquire(gate, REPO, "main", 1, False)
        ten = await worktrees._acquire(gate, REPO, "main", 10, False)
        with pytest.raises(ValueError, match="is not the worktree of demo#1"):
            await worktrees._drop(REPO, 1, paths[name])
        assert one.path.is_dir() and ten.path.is_dir() and (r.base / "README.md").is_file()
        assert r.entries() == ["1", "10"] and len(r.rows()) == 2

    asyncio.run(scenario())


# --- 3: SIGTERM -------------------------------------------------------------------------------------------------------------------

def test_sigterm_cancels_the_task_and_the_live_worktree_and_its_entry_go(real_repo, sigterm_guard):
    r, gate, seen = real_repo, worktrees.Gate(1), {}

    async def main_task():
        worktrees.cancel_on_sigterm()
        async with worktrees.checkout(gate, REPO, "main", 1) as item:
            seen["path"] = item.path
            assert item.path.is_dir() and r.entries() == ["1"] and r.branches() == ["loop/issue-1"]
            os.kill(os.getpid(), signal.SIGTERM)
            await forever()  # the cancel arrives here

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main_task())
    assert sigterm_guard == []  # the loop's handler took SIGTERM, not the guard
    assert not seen["path"].exists() and r.entries() == [] and r.rows() == {}
    assert r.branches() == []  # a cancelled item counts as failed: its own branch goes


def run_main_until_sigterm(r, gate, monkeypatch, tmp_path, numbers):
    """watcher247.__main__.main(once=True) whose tick holds one live item per number; SIGTERM arrives when all are alive."""
    monkeypatch.setattr(config, "CLAIMS", tmp_path / "claims.json")
    monkeypatch.setenv("SIMPLICIO_247_ENV_FILE", str(tmp_path / "no-such.env"))
    alive, inside = [], []

    async def blocked_tick(dry_run=False):
        alive.append(asyncio.Event())

        async def hold(number):
            async with worktrees.checkout(gate, REPO, "main", number) as item:
                inside.append(item.path)
                if len(inside) == len(numbers):
                    alive[0].set()
                await forever()

        await worktrees.run_batch(numbers, lambda n: frozenset(), hold)

    monkeypatch.setattr(tick, "tick", blocked_tick)

    async def driver():
        task = asyncio.ensure_future(watcher_main.main(once=True))
        while not alive:
            await asyncio.sleep(0)
            assert not task.done(), "main returned before the tick started"
        await until(alive[0], "the live worktrees")
        assert len(r.rows()) == len(numbers) and r.entries() == sorted(str(n) for n in numbers)
        os.kill(os.getpid(), signal.SIGTERM)
        return await asyncio.wait_for(task, WAIT)

    return asyncio.run(driver()), inside


def test_main_once_returns_143_on_sigterm_and_the_live_worktree_goes(real_repo, sigterm_guard, monkeypatch, tmp_path):
    r = real_repo
    code, inside = run_main_until_sigterm(r, worktrees.Gate(1), monkeypatch, tmp_path, [1])
    assert code == 143 and worktrees.SIGTERM_EXIT == 143
    assert sigterm_guard == [] and len(inside) == 1 and not inside[0].exists()
    assert r.entries() == [] and r.rows() == {} and r.branches() == []


def test_main_once_sigterm_with_two_live_items_removes_both_worktrees(real_repo, sigterm_guard, monkeypatch, tmp_path):
    r = real_repo
    code, inside = run_main_until_sigterm(r, worktrees.Gate(2), monkeypatch, tmp_path, [1, 2])
    assert code == 143 and len(inside) == 2
    assert [p.exists() for p in inside] == [False, False], "a live worktree survived SIGTERM"
    assert r.entries() == [] and r.rows() == {} and r.branches() == []


# --- 4: branches ------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("existed, outcome, stays", [
    (False, "published", False),  # the item made the branch and opened a PR: gone
    (False, "failed", False),     # the item made the branch and failed: gone
    (False, "plain", True),       # a clean run without diff and without PR: the branch stays
    (True, "published", True),    # the branch was there before the item: never deleted ...
    (True, "failed", True),       # ... not even when the item failed
])
def test_branch_is_deleted_only_when_the_item_made_it_and_published_or_failed(real_repo, existed, outcome, stays):
    r, gate = real_repo, worktrees.Gate(1)
    if existed:
        git("branch", "loop/issue-4", "origin/main", cwd=r.base)
    before = r.branches()

    async def scenario():
        try:
            async with worktrees.checkout(gate, REPO, "main", 4) as item:
                assert item.created_branch is (not existed) and item.head == "loop/issue-4"
                assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=item.path) == "loop/issue-4"
                assert "loop/issue-4" in r.branches()
                if outcome == "published":
                    item.published = True
                if outcome == "failed":
                    raise RuntimeError("boom")
        except RuntimeError as exc:
            assert outcome == "failed" and str(exc) == "boom"

    asyncio.run(scenario())
    assert r.entries() == [] and r.rows() == {}
    assert r.branches() == (["loop/issue-4"] if stays else [])
    assert before == (["loop/issue-4"] if existed else [])


def test_two_issues_get_two_distinct_branches_each_checked_out_in_its_own_worktree(real_repo):
    r, gate = real_repo, worktrees.Gate(2)

    async def scenario():
        ready = [asyncio.Event(), asyncio.Event()]

        async def item(number, mine, other):
            async with worktrees.checkout(gate, REPO, "main", number) as it:
                mine.set()
                await until(other, "the other item")  # both are alive at the same time
                return it.head, it.path, git("rev-parse", "--abbrev-ref", "HEAD", cwd=it.path), r.branches()

        return await asyncio.gather(item(1, ready[0], ready[1]), item(2, ready[1], ready[0]))

    (head1, path1, cur1, seen1), (head2, path2, cur2, seen2) = asyncio.run(scenario())
    assert (head1, cur1) == ("loop/issue-1", "loop/issue-1") and (head2, cur2) == ("loop/issue-2", "loop/issue-2")
    assert path1 == r.wt(1) and path2 == r.wt(2) and path1 != path2
    assert sorted(seen1) == sorted(seen2) == ["loop/issue-1", "loop/issue-2"]
    assert r.branches() == ["loop/issue-1", "loop/issue-2"]  # neither published nor failed: both stay


def test_a_new_item_starts_at_the_base_branch_even_when_the_origin_has_a_pr_branch_of_the_issue(real_repo):
    r, gate = real_repo, worktrees.Gate(1)
    pr_sha = r.advance("review.txt", "pr work\n", branch="loop/issue-7")
    main_sha = git("rev-parse", "origin/main", cwd=r.base)
    assert pr_sha != main_sha

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 7) as new:
            assert git("rev-parse", "HEAD", cwd=new.path) == main_sha and not (new.path / "review.txt").exists()

    asyncio.run(scenario())
    assert r.origin_ref("refs/heads/loop/issue-7") == pr_sha  # the origin branch of the PR is never touched


def test_a_fix_item_starts_from_the_prs_branch(real_repo):
    r, gate = real_repo, worktrees.Gate(1)
    pr_sha = r.advance("review.txt", "pr work\n", branch="loop/issue-7")

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 7, fix=True) as fix:
            assert git("rev-parse", "HEAD", cwd=fix.path) == pr_sha and (fix.path / "review.txt").is_file()
            assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=fix.path) == "loop/issue-7"

    asyncio.run(scenario())


# --- 5: failure and cancel release everything -------------------------------------------------------------------------------------

def test_an_exception_inside_removes_the_worktree_and_frees_the_slot(real_repo):
    r, gate = real_repo, worktrees.Gate(1)

    async def scenario():
        with pytest.raises(RuntimeError, match="boom"):
            async with worktrees.checkout(gate, REPO, "main", 1) as item:
                path = item.path
                assert path.is_dir()
                raise RuntimeError("boom")
        assert not path.exists() and r.entries() == [] and r.rows() == {}
        async with asyncio.timeout(WAIT):  # the only slot is free again: this would wait forever otherwise
            async with worktrees.checkout(gate, REPO, "main", 2) as second:
                assert second.path.is_dir()

    asyncio.run(scenario())


def test_a_cancel_inside_removes_the_worktree_and_frees_the_slot(real_repo):
    r, gate = real_repo, worktrees.Gate(1)

    async def scenario():
        inside, box = asyncio.Event(), {}

        async def worker():
            async with worktrees.checkout(gate, REPO, "main", 1) as item:
                box["path"] = item.path
                inside.set()
                await forever()

        task = asyncio.ensure_future(worker())
        await until(inside, "the worker")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not box["path"].exists() and r.entries() == [] and r.rows() == {} and r.branches() == []
        async with asyncio.timeout(WAIT):
            async with worktrees.checkout(gate, REPO, "main", 2) as second:
                assert second.path.is_dir()

    asyncio.run(scenario())


def test_a_second_cancel_waits_for_the_cleanup_instead_of_skipping_it(real_repo, monkeypatch):
    r, gate = real_repo, worktrees.Gate(1)
    real_release = worktrees._release

    async def scenario():
        inside, release_started, proceed, box = asyncio.Event(), asyncio.Event(), asyncio.Event(), {}

        async def gated_release(g, item):
            release_started.set()
            await proceed.wait()
            await real_release(g, item)

        monkeypatch.setattr(worktrees, "_release", gated_release)

        async def worker():
            async with worktrees.checkout(gate, REPO, "main", 1) as item:
                box["path"] = item.path
                inside.set()
                await forever()

        task = asyncio.ensure_future(worker())
        await until(inside, "the worker")
        task.cancel()
        await until(release_started, "the cleanup")
        task.cancel()  # a second cancel while the cleanup is in flight
        await asyncio.sleep(0)
        assert not task.done() and box["path"].is_dir()  # it waits for the cleanup
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not box["path"].exists() and r.entries() == [] and r.rows() == {}

    asyncio.run(scenario())


# --- 6: the state kept in .simplicio-loop -----------------------------------------------------------------------------------------

def state_file(item_path: Path, number: int) -> Path:
    return item_path / ".simplicio-loop" / "escalation-states" / f"issue-{number}.json"


def test_the_escalation_state_follows_the_issue_to_its_next_worktree_and_only_that_issue(real_repo):
    gate = worktrees.Gate(1)
    payload = '{"ladder": 2, "rung": "sonnet"}\n'

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 1) as first:
            assert not state_file(first.path, 1).exists()
            state_file(first.path, 1).parent.mkdir(parents=True)
            state_file(first.path, 1).write_text(payload)
        saved = worktrees.state_home(REPO, 1) / ".simplicio-loop" / "escalation-states" / "issue-1.json"
        assert saved.read_text() == payload and not first.path.exists()  # kept outside the worktree
        async with worktrees.checkout(gate, REPO, "main", 1) as again:
            assert state_file(again.path, 1).read_text() == payload  # found by the second checkout of the SAME issue
        async with worktrees.checkout(gate, REPO, "main", 2) as other:
            assert not state_file(other.path, 1).exists()  # never another issue's state
        assert worktrees.state_home(REPO, 1) != worktrees.state_home(REPO, 2)

    asyncio.run(scenario())


def test_a_loop_toml_tracked_by_the_repo_is_not_overwritten_by_the_old_copy(real_repo):
    r, gate = real_repo, worktrees.Gate(1)
    old, new = 'enabled = true\nverify = "OLD"\n', 'enabled = true\nverify = "NEW"\n'

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 1) as first:
            (first.path / ".simplicio-loop" / "loop.toml").write_text(old)  # what the run left behind
            state_file(first.path, 1).parent.mkdir(parents=True)
            state_file(first.path, 1).write_text("{}\n")
        saved = worktrees.state_home(REPO, 1) / ".simplicio-loop" / "loop.toml"
        assert saved.read_text() == old  # the copy is a faithful copy ...
        r.advance(".simplicio-loop/loop.toml", new)  # ... and the repo moved on
        async with worktrees.checkout(gate, REPO, "main", 1) as second:
            toml = second.path / ".simplicio-loop" / "loop.toml"
            assert toml.read_text() == new  # the tracked file of the repo wins
            assert git("status", "--porcelain", "--", ".simplicio-loop/loop.toml", cwd=second.path) == ""
            assert state_file(second.path, 1).read_text() == "{}\n"  # while the untracked state does come back

    asyncio.run(scenario())


def test_a_symlink_planted_in_the_state_dir_is_never_copied_or_followed(real_repo, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-0451\n")
    secret_dir = tmp_path / "secret-dir"
    secret_dir.mkdir()
    (secret_dir / "inner.txt").write_text("TOP-SECRET-0451 inner\n")
    gate = worktrees.Gate(1)

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 1) as first:
            home = first.path / ".simplicio-loop"
            home.mkdir(exist_ok=True)
            (home / "keep.txt").write_text("ordinary\n")
            os.symlink(secret, home / "leak.txt")
            os.symlink(secret_dir, home / "leak-dir")
            os.symlink(tmp_path / "nowhere", home / "dangling")
        saved = worktrees.state_home(REPO, 1) / ".simplicio-loop"
        assert (saved / "keep.txt").read_text() == "ordinary\n"  # the ordinary file is copied ...
        for name in ("leak.txt", "leak-dir", "dangling"):
            assert not os.path.lexists(saved / name), f"{name} was copied to the state home"
        for found in worktrees.state_home(REPO, 1).rglob("*"):
            assert not found.is_file() or "TOP-SECRET" not in found.read_text()
        async with worktrees.checkout(gate, REPO, "main", 1) as second:
            home = second.path / ".simplicio-loop"
            assert (home / "keep.txt").read_text() == "ordinary\n"
            for name in ("leak.txt", "leak-dir", "dangling"):
                assert not os.path.lexists(home / name), f"{name} reached the next worktree"

    asyncio.run(scenario())


# --- 7: the base clone ------------------------------------------------------------------------------------------------------------

def test_the_base_stays_detached_clean_and_without_loop_branches_after_items(real_repo):
    r, gate = real_repo, worktrees.Gate(2)

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 1) as one:
            commit_in(one.path, "one.txt")
            one.published = True
        with pytest.raises(RuntimeError):
            async with worktrees.checkout(gate, REPO, "main", 2) as two:
                commit_in(two.path, "two.txt")
                raise RuntimeError("failed")

    asyncio.run(scenario())
    assert git_rc("symbolic-ref", "-q", "HEAD", cwd=r.base) == 1  # detached: no branch is checked out in the base
    assert git("rev-parse", "HEAD", cwd=r.base) == git("rev-parse", "origin/main", cwd=r.base)
    assert r.branches() == [] and r.entries() == [] and r.rows() == {}
    assert git("status", "--porcelain", cwd=r.base) == ""  # no item ever edited the base
    assert not (r.base / "one.txt").exists() and not (r.base / "two.txt").exists()


def test_fetching_a_newer_origin_leaves_a_live_worktrees_git_working_and_the_next_item_starts_new(real_repo):
    r, gate = real_repo, worktrees.Gate(2)

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 1) as old:
            old_sha = git("rev-parse", "HEAD", cwd=old.path)
            new_sha = r.advance("fresh.txt")
            assert new_sha != old_sha
            async with worktrees.checkout(gate, REPO, "main", 2) as new:  # fetches --depth 1 while `old` is alive
                assert git("rev-parse", "HEAD", cwd=new.path) == new_sha and (new.path / "fresh.txt").is_file()
                assert git_rc("status", "--porcelain", cwd=old.path) == 0
                assert git("log", "-1", "--format=%H", cwd=old.path) == old_sha
                assert not (old.path / "fresh.txt").exists()  # the live item keeps the commit it started from
                assert git("rev-list", "--count", "HEAD", cwd=old.path).isdigit()
                after = commit_in(old.path, "still-works.txt")  # and it can still commit
                assert git("log", "-1", "--format=%H", cwd=old.path) == after
        assert git("rev-parse", "origin/main", cwd=r.base) == new_sha

    asyncio.run(scenario())


# --- 8/9: concurrency -------------------------------------------------------------------------------------------------------------

def test_gate_of_two_with_four_items_runs_exactly_two_at_a_time(real_repo, monkeypatch):
    r, gate = real_repo, worktrees.Gate(2)
    held = peak_held = live = peak_live = 0
    real_acquire, real_release = worktrees._acquire, worktrees._release
    listed: list[int] = []

    async def spy_acquire(*args, **kwargs):  # an item between the start of _acquire and the end of _release holds a slot
        nonlocal held, peak_held
        held += 1
        peak_held = max(peak_held, held)
        try:
            return await real_acquire(*args, **kwargs)
        except BaseException:
            held -= 1
            raise

    async def spy_release(g, item):
        nonlocal held
        try:
            await real_release(g, item)
        finally:
            held -= 1

    monkeypatch.setattr(worktrees, "_acquire", spy_acquire)
    monkeypatch.setattr(worktrees, "_release", spy_release)

    async def scenario():
        pair, arrived = asyncio.Event(), []

        async def item(number):
            nonlocal live, peak_live
            async with worktrees.checkout(gate, REPO, "main", number):
                live += 1
                peak_live = max(peak_live, live)
                listed.append(len(r.rows()))  # the worktrees git itself lists right now
                arrived.append(number)
                if len(arrived) == 2:
                    pair.set()
                await until(pair, "two items alive together")  # proves they ran in parallel
                await asyncio.sleep(0.05)  # holds the slot
                live -= 1

        await asyncio.gather(*(item(n) for n in (1, 2, 3, 4)))

    asyncio.run(scenario())
    assert peak_live == 2  # parallel AND limited
    assert peak_held == 2 and held == 0  # no third item got past the gate while two held it
    assert max(listed) == 2 and len(listed) == 4  # never more than two real worktrees at once
    assert r.entries() == [] and r.rows() == {}


def test_the_repo_lock_is_not_held_while_an_item_runs(real_repo):
    r, gate = real_repo, worktrees.Gate(2)

    async def scenario():
        b_inside = asyncio.Event()

        async def item_b():
            async with worktrees.checkout(gate, REPO, "main", 2) as b:
                assert b.path.is_dir()
                b_inside.set()

        b = None
        try:
            async with worktrees.checkout(gate, REPO, "main", 1) as a:
                assert a.path.is_dir() and not gate.repo_lock(REPO).locked()
                b = asyncio.ensure_future(item_b())
                await until(b_inside, "item B finishing its _acquire while A's body runs")
                await asyncio.wait_for(b, WAIT)
        finally:
            if b is not None and not b.done():
                b.cancel()
                await asyncio.gather(b, return_exceptions=True)

    asyncio.run(scenario())
    assert r.entries() == [] and r.rows() == {}


# --- 10: disk ---------------------------------------------------------------------------------------------------------------------

def test_below_the_disk_floor_the_item_is_deferred_and_nothing_is_created(real_repo, monkeypatch):
    r, gate = real_repo, worktrees.Gate(1)
    asked = []

    async def low(path):
        asked.append(path)
        return squad_capacity.DISK_FLOOR_BYTES - 1

    monkeypatch.setattr(worktrees, "free_bytes", low)

    async def scenario():
        with pytest.raises(points.PointDeferred) as exc:
            async with worktrees.checkout(gate, REPO, "main", 1):
                raise AssertionError("the body must not run below the floor")
        assert exc.value.reason_code == "disk_low" and exc.value.stage == "worktree"
        assert r.entries() == [] and r.rows() == {} and r.branches() == []
        assert not (config.WORK / f"{REPO}.wt").exists()
        async def fine(path):
            return squad_capacity.DISK_FLOOR_BYTES
        monkeypatch.setattr(worktrees, "free_bytes", fine)  # exactly AT the floor is enough ...
        async with asyncio.timeout(WAIT):  # ... and the deferred item gave its slot back
            async with worktrees.checkout(gate, REPO, "main", 1) as item:
                assert item.path.is_dir()

    asyncio.run(scenario())
    assert asked == [config.WORK]


def test_free_bytes_reads_the_real_disk(tmp_path):
    free = asyncio.run(worktrees.free_bytes(tmp_path))
    assert isinstance(free, int) and abs(free - shutil.disk_usage(tmp_path).free) < 1 << 30


# --- 11: push ---------------------------------------------------------------------------------------------------------------------

def test_push_reaches_the_origin_from_the_items_worktree(real_repo):
    r, gate = real_repo, worktrees.Gate(1)
    box = {}

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 1) as item:
            box["sha"] = commit_in(item.path, "change.txt")
            result = await worktrees.push(gate, REPO, item.path, item.head)
            box["rc"], box["err"] = result.returncode, result.stderr
            box["remote"] = git("config", "--get", "branch.loop/issue-1.remote", cwd=r.base)  # -u wrote the shared config
            item.published = True

    asyncio.run(scenario())
    assert box["rc"] == 0, box["err"]
    assert r.origin_ref("refs/heads/loop/issue-1") == box["sha"] and box["remote"] == "origin"
    assert r.origin_ref("refs/heads/main") != box["sha"]  # only the item's branch moved
    assert r.branches() == []  # published: the local branch went, the origin one stays


def test_two_pushes_never_overlap_and_never_force(real_repo, monkeypatch):
    r, gate = real_repo, worktrees.Gate(2)
    spans, argvs = [], []
    real_run = proc.run

    async def watching(argv, *args, **kwargs):  # passes everything to the real proc.run, only notes the pushes
        if list(argv[:2]) == ["git", "push"]:
            argvs.append(list(argv))
            start = time.monotonic()
            try:
                return await real_run(argv, *args, **kwargs)
            finally:
                spans.append((start, time.monotonic()))
        return await real_run(argv, *args, **kwargs)

    monkeypatch.setattr(proc, "run", watching)

    async def scenario():
        one = await worktrees._acquire(gate, REPO, "main", 1, False)
        two = await worktrees._acquire(gate, REPO, "main", 2, False)
        shas = {1: commit_in(one.path, "a.txt"), 2: commit_in(two.path, "b.txt")}
        results = await asyncio.gather(worktrees.push(gate, REPO, one.path, one.head), worktrees.push(gate, REPO, two.path, two.head))
        await worktrees._release(gate, one)
        await worktrees._release(gate, two)
        return shas, results

    shas, results = asyncio.run(scenario())
    assert [x.returncode for x in results] == [0, 0], [x.stderr for x in results]
    assert len(spans) == 2
    first, second = sorted(spans)
    assert first[1] <= second[0], f"the pushes overlapped: {first} {second}"
    assert sorted(argvs) == [["git", "push", "-u", "origin", "loop/issue-1"], ["git", "push", "-u", "origin", "loop/issue-2"]]
    for argv in argvs:  # never a force push, in any spelling
        assert not any(a in ("-f", "--force", "--force-with-lease") or a.startswith(("--force", "+")) for a in argv)
    assert r.origin_ref("refs/heads/loop/issue-1") == shas[1] and r.origin_ref("refs/heads/loop/issue-2") == shas[2]


# --- 12: sandbox binds ------------------------------------------------------------------------------------------------------------

def expected_binds(common: Path, number: int) -> list[str]:
    out: list[str] = []
    for target in (common / "worktrees" / str(number), common / "objects", common / "simplicio"):
        out += ["--bind", str(target), str(target)]
    return out


def test_worktree_binds_are_exactly_the_items_admin_dir_objects_and_simplicio(real_repo):
    r, gate = real_repo, worktrees.Gate(1)
    (r.common / "simplicio").mkdir()

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 3) as item:
            binds = sandbox.worktree_binds(str(item.path))
            assert binds == expected_binds(r.common, 3)
            assert (r.common / "worktrees" / "3").is_dir()  # git really named the admin dir after the issue
            targets = set(binds[1::3])
            assert targets == {str(r.common / "worktrees" / "3"), str(r.common / "objects"), str(r.common / "simplicio")}
            for forbidden in (r.common, r.common / "config", r.common / "hooks", r.common / "refs", r.common / "worktrees"):
                assert str(forbidden) not in targets
            argv = sandbox.wrap(["true"], clone=item.path, state_dir=Path("/state"), platform="linux", environ={},
                                which=lambda binary: "/usr/bin/bwrap")
            at = argv.index(binds[1])
            assert argv[at - 1:at - 1 + len(binds)] == binds  # wrap() passes them, in this order, after the clone bind

    asyncio.run(scenario())


def test_worktree_binds_ignore_what_the_dot_git_file_says(real_repo, tmp_path):
    r, gate = real_repo, worktrees.Gate(1)
    (r.common / "simplicio").mkdir()
    evil = tmp_path / "evil"
    for sub in ("worktrees/1", "objects", "simplicio"):
        (evil / sub).mkdir(parents=True)

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 1) as item:
            honest = sandbox.worktree_binds(str(item.path))
            assert honest == expected_binds(r.common, 1)
            dot_git = item.path / ".git"
            original = dot_git.read_text()
            for tampered in ("gitdir: /tmp/outro\n", f"gitdir: {evil}/worktrees/1\n", "garbage"):
                dot_git.write_text(tampered)  # the sandbox can write this file
                assert sandbox.worktree_binds(str(item.path)) == honest
            dot_git.unlink()
            assert sandbox.worktree_binds(str(item.path)) == honest
            dot_git.write_text(original)

    asyncio.run(scenario())


def test_worktree_binds_are_empty_for_a_plain_clone_and_for_unknown_layouts(real_repo, tmp_path):
    r = real_repo
    assert sandbox.worktree_binds(str(r.base)) == []
    assert sandbox.worktree_binds(str(tmp_path / "work" / "nothing.wt" / "3")) == []  # looks like an item, no such base
    admin, objects = r.common / "worktrees" / "5", r.common / "objects"
    admin.mkdir(parents=True)
    assert sandbox.worktree_binds(str(r.wt(5))) == ["--bind", str(admin), str(admin), "--bind", str(objects), str(objects)]  # no simplicio/ yet
    assert sandbox.worktree_binds(str(r.wt(6))) == ["--bind", str(r.common / "objects"), str(r.common / "objects")]


# --- 13: files shared between items -----------------------------------------------------------------------------------------------

# --- sandbox isolation between items (REAL bwrap + REAL git) ----------------------------------------------------------------------

CONTROL_FILES = ("claims.json", "budget.json", "STOP")


def in_sandbox(item_path: Path, script: str) -> subprocess.CompletedProcess:
    """`script` under the exact bwrap argv an item's turbo gets: state_dir is the watcher's state dir, the parent of work/."""
    argv = sandbox.wrap(["sh", "-c", script], clone=item_path, state_dir=config.ROOT, platform="linux", environ={})
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


@pytest.fixture
def two_live_items(real_repo, tmp_path, monkeypatch):
    """Items 31 (A) and 32 (B) both alive (their worktrees and admin dirs exist); the state dir holds the control files."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    for name in CONTROL_FILES:
        (tmp_path / name).write_text("host\n")
    (real_repo.common / "hooks").mkdir(exist_ok=True)
    (real_repo.common / "hooks" / "pre-push").write_text("host hook\n")
    gate = worktrees.Gate(2)

    async def both():
        return await worktrees._acquire(gate, REPO, "main", 31, False), await worktrees._acquire(gate, REPO, "main", 32, False)

    a, b = asyncio.run(both())
    return real_repo, a, b


def foreign_targets(r: Repo, b: worktrees.Item) -> dict[str, Path]:
    return {
        "neighbour worktree": b.path / "planted",
        "neighbour admin dir": r.common / "worktrees" / "32" / "HEAD",
        "base config": r.common / "config",
        "base hooks": r.common / "hooks" / "pre-push",
        "base refs": r.common / "refs" / "heads" / "planted",
        "base worktree": r.base / "README.md",
        "claims.json": config.ROOT / "claims.json",
        "budget.json": config.ROOT / "budget.json",
        "STOP": config.ROOT / "STOP",
    }


@needs_bwrap
@pytest.mark.parametrize("name", ["neighbour worktree", "neighbour admin dir", "base config", "base hooks", "base refs", "base worktree",
                                  "claims.json", "budget.json", "STOP"])
def test_the_sandbox_of_one_item_cannot_write_what_belongs_to_the_neighbour_the_base_or_the_watcher(two_live_items, name):
    r, a, b = two_live_items
    target = foreign_targets(r, b)[name]
    before = target.read_bytes() if target.is_file() else None
    done = in_sandbox(a.path, f"echo pwned >> '{target}'")
    assert done.returncode != 0, f"{name} was writable from inside item A's sandbox"
    assert (target.read_bytes() if target.is_file() else None) == before


@needs_bwrap
def test_the_sandbox_of_one_item_still_writes_its_own_worktree_admin_dir_and_objects_and_the_host_then_commits_and_pushes(two_live_items):
    r, a, b = two_live_items
    own_admin = r.common / "worktrees" / "31"
    done = in_sandbox(a.path, f"echo ok > edited.txt && echo ok > '{own_admin}/own-marker' && mkdir -p '{r.common}/objects/zz' "
                              f"&& echo ok > '{r.common}/objects/zz/own' && git add edited.txt && git status --porcelain")
    assert done.returncode == 0, done.stderr
    assert (a.path / "edited.txt").read_text() == "ok\n" and (own_admin / "own-marker").exists()
    sha = commit_in(a.path, "feature.txt")  # the host's commit and push of the item
    pushed = asyncio.run(worktrees.push(worktrees.Gate(1), REPO, a.path, a.head))
    assert pushed.returncode == 0, pushed.stderr
    assert r.origin_ref("refs/heads/loop/issue-31") == sha
    assert not (b.path / "planted").exists() and git("rev-parse", "--abbrev-ref", "HEAD", cwd=b.path) == "loop/issue-32"


@needs_bwrap
def test_a_planted_dot_git_file_makes_the_sandbox_see_the_neighbours_branch_but_the_host_git_does_not_follow_it(two_live_items):
    r, a, b = two_live_items
    done = in_sandbox(a.path, f"echo 'gitdir: {r.common}/worktrees/32' > .git")  # the item rewrites its own .git file (still writable)
    assert done.returncode == 0, done.stderr
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=a.path) == "loop/issue-32"  # plain git follows the file: the attack is real
    seen = {}

    async def host():
        for key, args in {"head": ["rev-parse", "--abbrev-ref", "HEAD"], "gitdir": ["rev-parse", "--absolute-git-dir"],
                          "top": ["rev-parse", "--show-toplevel"]}.items():
            seen[key] = (await proc.run(["git", *args], cwd=a.path)).stdout.strip()
        (a.path / "host-made.txt").write_text("x\n")
        await proc.run(["git", "add", "host-made.txt"], cwd=a.path)
        seen["commit"] = (await proc.run(["git", "commit", "-q", "-m", "host commit"], cwd=a.path)).returncode

    asyncio.run(host())
    assert seen == {"head": "loop/issue-31", "gitdir": str(r.common / "worktrees" / "31"), "top": str(a.path), "commit": 0}
    assert git("log", "-1", "--format=%s", "loop/issue-31", cwd=r.base) == "host commit"
    assert git("log", "-1", "--format=%s", "loop/issue-32", cwd=r.base) == "seed"  # the neighbour's branch was not touched


@needs_bwrap
def test_a_rewritten_commondir_of_the_items_own_admin_dir_does_not_redirect_the_host_git(two_live_items, tmp_path):
    r, a, _b = two_live_items
    other = tmp_path / "other"
    git("init", "-q", "-b", "main", str(other), cwd=tmp_path)
    done = in_sandbox(a.path, f"echo '{other}/.git' > '{r.common}/worktrees/31/commondir'")
    assert done.returncode == 0, done.stderr
    top = asyncio.run(proc.run(["git", "rev-parse", "--git-common-dir"], cwd=a.path)).stdout.strip()
    assert top == str(r.common)


# --- #1680 item 7: the base seeds `.simplicio-loop/` into its info/exclude (read-only inside the item's sandbox) --------------------

EXCLUDE_LINE = ".simplicio-loop/"
ENSURE = ("import sys; sys.path.insert(0, {root!r}); from pathlib import Path; "
          "from simplicio_loop.state_dir import ensure_state_dir; ensure_state_dir(Path({clone!r}))")


def exclude_file(r: Repo) -> Path:
    return r.common / "info" / "exclude"


def test_update_base_seeds_the_state_dir_line_once_and_keeps_the_existing_content(real_repo):
    r = real_repo
    exclude_file(r).write_text("*.log")  # no final newline
    asyncio.run(worktrees._update_base(REPO, "main", 1, False))
    asyncio.run(worktrees._update_base(REPO, "main", 2, False))
    assert exclude_file(r).read_text().splitlines().count(EXCLUDE_LINE) == 1
    assert exclude_file(r).read_text() == f"*.log\n{EXCLUDE_LINE}\n"


def test_update_base_seeds_a_base_whose_exclude_file_is_missing(real_repo):
    r = real_repo
    exclude_file(r).unlink()
    asyncio.run(worktrees._update_base(REPO, "main", 1, False))
    assert exclude_file(r).read_text().splitlines() == [EXCLUDE_LINE]


@needs_bwrap
def test_ensure_state_dir_in_the_items_sandbox_fails_with_erofs_before_the_seed_and_runs_after_it(two_live_items):
    r, a, _b = two_live_items
    code = ENSURE.format(root=str(Path(__file__).resolve().parents[2]), clone=str(a.path))
    script = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    exclude_file(r).write_text("*.log\n")  # a base the host never seeded
    before = in_sandbox(a.path, script)
    assert before.returncode != 0 and "Errno 30" in before.stderr and "exclude" in before.stderr, before.stderr
    asyncio.run(worktrees._update_base(REPO, "main", 31, False))  # the host seeds the line
    after = in_sandbox(a.path, script)
    assert after.returncode == 0 and "Errno 30" not in after.stderr, after.stderr
    assert exclude_file(r).read_text().splitlines().count(EXCLUDE_LINE) == 1


TURBO_WRITE = ("; (Path({clone!r}) / '.simplicio-loop' / 'turbo-request.json').write_text('{{}}')")


@needs_bwrap
def test_a_turbo_like_run_in_the_items_sandbox_writes_its_state_dir_without_errno_30_once_the_base_is_seeded(two_live_items):
    """#1680 item 7, end to end: after the host seeds the line, ensure_state_dir and a write into the item's state dir both succeed
    inside the item's real sandbox. The state dir is the item's clone's `.simplicio-loop/`, which the item may write."""
    r, a, _b = two_live_items
    code = ENSURE.format(root=str(Path(__file__).resolve().parents[2]), clone=str(a.path)) + TURBO_WRITE.format(clone=str(a.path))
    script = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"
    exclude_file(r).write_text("*.log\n")  # a base the host has not seeded yet: the first attempt is the EROFS of the ticket
    assert "Errno 30" in in_sandbox(a.path, script).stderr
    asyncio.run(worktrees._update_base(REPO, "main", 31, False))  # the host seeds the line
    done = in_sandbox(a.path, script)
    assert done.returncode == 0 and "Errno 30" not in done.stderr, done.stderr
    assert (a.path / ".simplicio-loop" / "turbo-request.json").read_text() == "{}"


def test_a_base_whose_pack_index_was_deleted_is_cloned_again_and_a_healthy_base_is_not(real_repo, monkeypatch):
    """#1656 item 3: an item can delete a pack .idx in the shared objects; the base (and every item) is then broken for good
    unless the host notices and clones again."""
    r = real_repo
    git("repack", "-a", "-d", "-q", cwd=r.base)  # a small fetch is unpacked to loose objects: make sure there is a pack to break
    indexes = list((r.common / "objects" / "pack").glob("*.idx"))
    assert indexes
    for index in indexes:
        index.unlink()
    assert git_rc("cat-file", "-e", "HEAD^{tree}", cwd=r.base) != 0  # the control: the damage is real
    real_run, cloned = proc.run, []

    async def run(argv, **kwargs):
        if argv[:3] == ["gh", "repo", "clone"]:  # no network here: the same clone, from the local origin
            cloned.append(argv)
            return await real_run(["git", "clone", "-q", "--depth", "1", f"file://{r.origin}", argv[4]], **kwargs)
        return await real_run(argv, **kwargs)

    monkeypatch.setattr(proc, "run", run)
    asyncio.run(worktrees._update_base(REPO, "main", 1, False))
    assert len(cloned) == 1 and git_rc("cat-file", "-e", "HEAD^{tree}", cwd=r.base) == 0
    asyncio.run(worktrees._update_base(REPO, "main", 2, False))
    assert len(cloned) == 1  # healthy: fetched, not cloned again


def test_drop_never_follows_a_symlink_planted_at_the_items_path(real_repo, tmp_path):
    r, gate = real_repo, worktrees.Gate(2)

    async def scenario():
        victim = await worktrees._acquire(gate, REPO, "main", 32, False)  # the neighbour's live worktree
        mine = await worktrees._acquire(gate, REPO, "main", 31, False)
        shutil.rmtree(mine.path)
        mine.path.symlink_to(victim.path)  # what an item inside the sandbox can plant for its successor
        await worktrees._drop(REPO, 31, mine.path)
        return victim

    victim = asyncio.run(scenario())
    assert victim.path.is_dir() and (victim.path / "README.md").exists()
    assert r.entries() == ["32"] and set(r.rows()) == {victim.path.resolve()}
    assert not r.wt(31).exists() and not r.wt(31).is_symlink()


def test_a_link_at_the_items_path_to_a_directory_outside_is_removed_and_the_outside_is_left_alone(real_repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n")
    gate = worktrees.Gate(1)
    path = real_repo.wt(31)
    path.parent.mkdir(parents=True)
    path.symlink_to(outside)

    async def scenario():
        async with worktrees.checkout(gate, REPO, "main", 31) as item:
            return item.path.is_symlink(), (item.path / "README.md").exists()

    assert asyncio.run(scenario()) == (False, True)  # a real worktree took the place of the link
    assert (outside / "keep.txt").read_text() == "keep\n" and [p.name for p in outside.iterdir()] == ["keep.txt"]


@pytest.mark.parametrize("repo", ["../x", "..", ".", "a/b", "/abs", "", "foo.wt", "foo.state", "foo.WT", "x.Wt", "foo.State", "-rf", ".hidden", "sp ace", "ünï", "a\nb"])
def test_a_repo_name_that_could_leave_work_or_collide_with_a_layout_dir_is_refused_everywhere(repo):
    for call in (worktrees.item_path, worktrees.state_home):
        with pytest.raises(ValueError):
            call(repo, 1)
    with pytest.raises(ValueError):
        worktrees.base_path(repo)


@pytest.mark.parametrize("repo", ["demo", "simplicio-loop", "simplicio.runtime", "a_b", "x1", "foo.wtx", "wt", "state"])
def test_a_github_repo_name_is_kept_under_work(repo):
    for path in (worktrees.item_path(repo, 7), worktrees.state_home(repo, 7), worktrees.base_path(repo)):
        assert config.WORK in path.parents


def test_a_repo_named_foo_wt_cannot_share_a_directory_with_the_items_of_foo(real_repo):
    assert worktrees.item_path("foo", 1).parent == config.WORK / "foo.wt"
    with pytest.raises(ValueError):
        worktrees.base_path("foo.wt")


def fs(*names: str) -> frozenset[str]:
    return frozenset(names)


def normalized(groups: list[list[int]]) -> set[tuple[int, ...]]:
    assert all(g == sorted(g) for g in groups), f"a group is out of batch order: {groups}"
    flat = [i for g in groups for i in g]
    assert len(flat) == len(set(flat)), f"an item is in two groups: {groups}"
    return {tuple(g) for g in groups}


def test_conflict_groups_are_transitive_and_keep_batch_order():
    assert normalized(worktrees.conflict_groups([fs("a", "b"), fs("b", "c"), fs("d"), fs("c", "z")])) == {(0, 1, 3), (2,)}
    assert normalized(worktrees.conflict_groups([fs("a", "b"), fs("d"), fs("b")])) == {(0, 2), (1,)}


def test_conflict_groups_merge_two_earlier_groups_when_a_later_item_bridges_them():
    assert normalized(worktrees.conflict_groups([fs("a"), fs("d"), fs("x"), fs("a", "d")])) == {(0, 1, 3), (2,)}
    assert normalized(worktrees.conflict_groups([fs("a"), fs("b"), fs("c"), fs("a", "b", "c")])) == {(0, 1, 2, 3)}


def test_conflict_groups_an_item_with_no_files_runs_alone_even_next_to_another_without():
    assert normalized(worktrees.conflict_groups([fs(), fs(), fs("a"), fs()])) == {(0,), (1,), (2,), (3,)}
    assert worktrees.conflict_groups([]) == []


def test_conflict_groups_read_the_files_from_the_issue_bodies():
    issues = [issue(1, body="Ajustar `src/a.py` para o fluxo do watcher seguir o contrato descrito."),
              issue(2, body="Ajustar `b.py` para o fluxo do watcher seguir o contrato descrito aqui."),
              issue(3, body="Ajustar `./src/a.py` e `c.py` para o fluxo do watcher seguir o contrato."),
              issue(4, body="Sem arquivo nomeado, apenas uma descricao de comportamento esperado.")]
    paths = [squad_flow.target_paths(i) for i in issues]
    assert paths[0] == fs("src/a.py") and paths[2] == fs("src/a.py", "c.py") and paths[3] == fs()
    assert normalized(worktrees.conflict_groups(paths)) == {(0, 2), (1,), (3,)}


def test_run_batch_serializes_items_that_share_a_file_and_runs_the_others_together():
    names = [fs("x"), fs("x"), fs("y"), fs("z")]  # items 0 and 1 share x
    spans, parked = {}, []

    async def scenario():
        together = asyncio.Event()

        async def run_one(item):
            start = time.monotonic()
            if item != 1:  # 0, 2 and 3 are the first of their groups: all three are inside at once, or this times out
                parked.append(item)
                if len(parked) == 3:
                    together.set()
                await until(together, "three independent items running together")
            await asyncio.sleep(0.05)
            spans[item] = (start, time.monotonic())
            return item * 10

        return await worktrees.run_batch([0, 1, 2, 3], lambda i: names[i], run_one)

    assert asyncio.run(scenario()) == [0, 10, 20, 30]  # results are in batch order
    assert spans[1][0] >= spans[0][1], f"items 0 and 1 share a file but overlapped: {spans}"
    overlap = lambda a, b: spans[a][0] < spans[b][1] and spans[b][0] < spans[a][1]  # noqa: E731
    assert overlap(0, 2) and overlap(0, 3) and overlap(2, 3)


def test_gate_needs_at_least_one_slot_and_gives_one_lock_per_repo():
    with pytest.raises(ValueError):
        worktrees.Gate(0)
    gate = worktrees.Gate(1)
    assert gate.repo_lock("a") is gate.repo_lock("a") and gate.repo_lock("a") is not gate.repo_lock("b")


# --- 14: the package never prunes, and removes only through _forget ---------------------------------------------------------------

PACKAGE = Path(worktrees.__file__).parent


def docstring_nodes(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def prune_literals(tree: ast.AST) -> list[str]:
    """String literals (docstrings excluded: they may explain why there is no prune) that contain the word prune."""
    skip = docstring_nodes(tree)
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "prune" in n.value.lower() and id(n) not in skip]


def rmtree_calls(tree: ast.AST) -> list[tuple[str, str]]:
    """(enclosing function, source of the first argument) of every rmtree call."""
    found: list[tuple[str, str]] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            if isinstance(child, ast.Call):
                func = child.func
                name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
                if name == "rmtree" and child.args:
                    found.append((scope, ast.unparse(child.args[0])))
            visit(child, inner)

    visit(tree, "<module>")
    return found


def test_the_scans_see_what_they_are_meant_to_see():
    bad = ast.parse('"""doc says prune."""\nimport shutil\ndef f(base):\n    run(["git", "worktree", "prune"])\n    shutil.rmtree(base)\n')
    assert prune_literals(bad) == ["prune"]  # the docstring is skipped, the argv is not
    assert rmtree_calls(bad) == [("f", "base")]
    assert prune_literals(ast.parse("def g():\n    return 'no such word'\n")) == [] and rmtree_calls(ast.parse("pass")) == []


def test_no_module_of_the_watcher_package_has_a_prune_literal():
    offenders = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        found = prune_literals(ast.parse(path.read_text(encoding="utf-8")))
        if found:
            offenders[str(path.relative_to(PACKAGE))] = found
    assert offenders == {}


def test_rmtree_is_called_only_inside_forget_and_only_on_the_items_path_or_entry():
    calls = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        found = rmtree_calls(ast.parse(path.read_text(encoding="utf-8")))
        if found:
            calls[str(path.relative_to(PACKAGE))] = found
    assert set(calls) == {"worktrees.py"}, f"rmtree outside worktrees.py: {sorted(calls)}"
    assert calls["worktrees.py"], "the scan found no rmtree at all"
    for scope, first_arg in calls["worktrees.py"]:
        assert scope == "_forget" and first_arg in ("path", "entry"), (scope, first_arg)


# Task 4: _seed_exclude error handling
def test_task4_seed_exclude_with_directory_raises_clear_error(tmp_path):
    """#1680 task 4: _seed_exclude raises clear RuntimeError when .git/info/exclude is a directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)

    # Replace .git/info/exclude file with a directory
    exclude_path = repo / ".git" / "info" / "exclude"
    exclude_path.unlink()  # Remove the file created by git init
    exclude_path.mkdir()  # Replace it with a directory

    with pytest.raises(RuntimeError, match="cannot seed .simplicio-loop"):
        worktrees._seed_exclude(repo)


def test_task4_seed_exclude_with_non_utf8_file_raises_clear_error(tmp_path):
    """#1680 task 4: _seed_exclude raises clear RuntimeError when .git/info/exclude is not UTF-8."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)

    # Create .git/info/exclude with non-UTF-8 content
    exclude_file = repo / ".git" / "info" / "exclude"
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    exclude_file.write_bytes(b"\x80\x81\x82\x83")  # Invalid UTF-8

    with pytest.raises(RuntimeError, match="cannot seed .simplicio-loop"):
        worktrees._seed_exclude(repo)


def test_task4_seed_exclude_with_file_instead_of_directory_raises_clear_error(tmp_path):
    """#1680 task 4: _seed_exclude raises clear RuntimeError when .git/info is a file instead of directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)

    # Replace .git/info directory with a file
    info_dir = repo / ".git" / "info"
    shutil.rmtree(info_dir)  # Remove the directory
    info_dir.write_text("")  # Create it as a file

    with pytest.raises(RuntimeError, match="cannot seed .simplicio-loop"):
        worktrees._seed_exclude(repo)


def test_a_damaged_base_with_a_live_item_is_not_deleted_and_the_item_keeps_its_commit(real_repo):
    """#1656 item 3, review of the first version: cloning the base again destroyed the live items of the repo and their unpublished commits."""
    r, gate = real_repo, worktrees.Gate(2)

    async def scenario():
        item = await worktrees._acquire(gate, REPO, "main", 41, False)
        git("commit", "-q", "--allow-empty", "-m", "unpublished", cwd=item.path)
        git("repack", "-a", "-d", "-q", cwd=item.path)
        for index in (r.common / "objects" / "pack").glob("*.idx"):
            index.unlink()
        assert git_rc("cat-file", "-e", "HEAD^{tree}", cwd=r.base) != 0  # the control: the damage is real
        with pytest.raises(worktrees.points.PointDeferred):
            await worktrees._update_base(REPO, "main", 42, False)
        return item

    item = asyncio.run(scenario())
    assert (r.base / ".git").exists() and (item.path / ".git").exists()  # nothing was deleted
    assert git_rc("rev-parse", "--git-dir", cwd=item.path) == 0


def test_a_cat_file_failure_that_is_not_a_missing_object_does_not_reclone(real_repo, monkeypatch):
    r, real_run, cloned = real_repo, proc.run, []

    async def run(argv, **kwargs):
        if argv[:2] == ["git", "cat-file"]:  # a killed git or an I/O error: no proof of damage
            return proc.Result(137, "", "Killed")
        if argv[:3] == ["gh", "repo", "clone"]:
            cloned.append(argv)
        return await real_run(argv, **kwargs)

    monkeypatch.setattr(proc, "run", run)
    asyncio.run(worktrees._update_base(REPO, "main", 1, False))
    assert cloned == [] and (r.base / ".git").exists()
