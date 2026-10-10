"""One git worktree per work item (#1601): the items of one repo run in parallel.

Before, process() held the repo lock for the whole item (clone, plan, turbo, apply, verify, PR) on ONE working tree per repo.
Now a repo has a BASE clone (config.WORK/<repo>) that no item edits, and every item gets its own worktree
(config.WORK/<repo>.wt/<issue>, branch loop/issue-<issue>) for its whole run. The repo lock covers only what really conflicts:

- updating the base clone (fetch), `git worktree add`, the push (`git push -u` writes the shared .git/config) and the removal of
  the item's own worktree. All short git calls. Never the plan, the turbo, the apply, the verify or the PR.
- one path per issue: the claim lease already allows one live item per issue, and a run killed by SIGKILL leaves its worktree at the
  path its successor will use, so the successor finds the leftover by the exact path.

Cleanup is exact. An item removes only its own path (`git worktree remove --force <path>`, then its leftover directory) and the
`<git-common-dir>/worktrees/<name>` entry whose `gitdir` file names exactly `<path>/.git` (same idea as scripts/build_binary.py
release_source, #1587). There is no `git worktree prune`: it forgets every worktree whose directory is missing at that moment,
and those are not ours. The state an item keeps in `.simplicio-loop/` (escalation ladder, runs, reports) is copied to
config.WORK/<repo>.state/<issue> when the worktree goes and put back when the next one for that issue is made.

Files: items of one batch that name the same target file (squad_flow.target_paths) run one after the other, in batch order; the
others run at once. Merge stays serial through the merge train.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shutil
import signal
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from .. import squad_capacity, state_dir
from . import config, points, proc, state

T = TypeVar("T")
STATE = ".simplicio-loop"
SIGTERM_EXIT = 143


class Gate:
    """One lock per repo for the short git steps above, and `slots` live worktrees at most (the tick's capacity plan)."""

    def __init__(self, slots: int) -> None:
        if slots < 1:
            raise ValueError("slots must be >= 1")
        self._locks: dict[str, asyncio.Lock] = {}
        self.slots = asyncio.Semaphore(slots)

    def repo_lock(self, repo: str) -> asyncio.Lock:
        return self._locks.setdefault(repo, asyncio.Lock())


@dataclass
class Item:
    """The worktree of one work item."""
    repo: str
    number: int
    head: str  # the item's branch, loop/issue-<number>
    path: Path
    created_branch: bool  # the branch did not exist before this item: only then may it be deleted
    published: bool = False  # a PR was opened or updated
    failed: bool = False

    @property
    def base(self) -> Path:
        return base_path(self.repo)


_REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _repo_dir(repo: str) -> str:
    """The repo name as one directory under config.WORK: a GitHub name, never a path, never `<x>.wt` / `<x>.state` (those are ours)."""
    if not _REPO_NAME.fullmatch(repo) or repo.endswith((".wt", ".state")):
        raise ValueError(f"not a usable repo name: {repo!r}")
    return repo


def base_path(repo: str) -> Path:
    return config.WORK / _repo_dir(repo)


def item_path(repo: str, number: int) -> Path:
    return config.WORK / f"{_repo_dir(repo)}.wt" / str(number)


def state_home(repo: str, number: int) -> Path:
    return config.WORK / f"{_repo_dir(repo)}.state" / str(number)


def _owned(repo: str, number: int, path: Path) -> None:
    """The one guard before anything is removed: `path` is exactly this item's path."""
    if path != item_path(repo, number):
        raise ValueError(f"{path} is not the worktree of {repo}#{number}")


async def free_bytes(path: Path) -> int:
    return (await asyncio.to_thread(shutil.disk_usage, path)).free


def _fail(result: proc.Result, what: str) -> RuntimeError:
    return RuntimeError((result.stderr or result.stdout or what)[:500])


async def _update_base(repo: str, branch: str, number: int, fix: bool) -> Path:
    """Clone the repo once, then fetch what this item starts from. The base holds no loop/* branch: it is detached at the base."""
    dest = base_path(repo)
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        result = await proc.run(
            ["gh", "repo", "clone", f"{config.ORG}/{repo}", str(dest), "--", "--depth", "1"], timeout=300)
        if result.returncode != 0:
            raise _fail(result, "clone failed")
    await proc.run(["git", "config", "user.name", "simplicio-loop"], cwd=dest)
    email = await proc.run(["git", "config", "user.email"], cwd=dest)
    if email.returncode != 0 or not email.stdout.strip():
        await proc.run(["git", "config", "user.email", "wesleysimplicio@users.noreply.github.com"], cwd=dest)
    refs = [branch, f"loop/issue-{number}"] if fix else [branch]
    for ref in refs:
        # the explicit refspec: a --depth 1 clone is single-branch, and without it `origin/<ref>` is never made for any other branch
        fetch = await proc.run(
            ["git", "fetch", "--depth", "1", "origin", f"+refs/heads/{ref}:refs/remotes/origin/{ref}"], cwd=dest, timeout=180)
        if fetch.returncode != 0:
            raise _fail(fetch, "fetch failed")
    detach = await proc.run(["git", "checkout", "-q", "-f", "--detach", f"origin/{branch}"], cwd=dest, timeout=60)
    if detach.returncode != 0:
        raise _fail(detach, "base checkout failed")
    await asyncio.to_thread(_seed_exclude, dest)
    return dest


def _seed_exclude(base: Path) -> None:
    """Put `.simplicio-loop/` in the base's info/exclude (state_dir's own helper). Inside an item's sandbox that file is read-only,
    so the `ensure_state_dir` of turbo would fail with EROFS there: the host writes the line first."""
    exclude = state_dir._git_info_exclude_path(base)
    if exclude is not None:
        state_dir._append_exclude_line_once(exclude)


def _forget(common: Path, path: Path) -> None:
    """Delete `path` (this item's own directory) and the entry in `<common>/worktrees` whose gitdir names exactly path/.git."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    wanted = Path(os.path.realpath(path / ".git"))
    for entry in sorted((common / "worktrees").glob("*")):
        try:
            if Path(os.path.realpath((entry / "gitdir").read_text(encoding="utf-8").strip())) == wanted:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


async def _drop(repo: str, number: int, path: Path) -> None:
    """Remove the worktree at `path` and only it; a leftover of a killed run goes the same way."""
    _owned(repo, number, path)
    base = base_path(repo)
    if path.is_symlink():  # a planted link: git resolves it and would remove the worktree it points at (another item's)
        path.unlink()
    if (path / ".git").exists():
        await proc.run(["git", "worktree", "remove", "--force", str(path)], cwd=base, timeout=120)
    await asyncio.to_thread(_forget, base / ".git", path)


def _copy_state(src: Path, dst: Path, overwrite: bool) -> None:
    if not src.is_dir():
        return
    for found in src.rglob("*"):
        if found.is_symlink():  # the sandbox can plant one: the copy runs outside it and would read what it points at
            continue
        target = dst / found.relative_to(src)
        if found.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif overwrite or not target.exists():  # a tracked file of the repo (loop.toml) is never replaced by an old copy
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(found, target)


async def _acquire(gate: Gate, repo: str, branch: str, number: int, fix: bool) -> Item:
    path, head = item_path(repo, number), f"loop/issue-{number}"
    config.WORK.mkdir(parents=True, exist_ok=True)
    async with gate.repo_lock(repo):
        if await free_bytes(config.WORK) < squad_capacity.DISK_FLOOR_BYTES:
            raise points.PointDeferred("worktree", "disk_floor", "disk_low", [])  # the tick tries again, no attempt is spent
        base = await _update_base(repo, branch, number, fix)
        await _drop(repo, number, path)  # a killed run's leftover at this exact path
        existed = (await proc.run(["git", "rev-parse", "--verify", "-q", f"refs/heads/{head}"], cwd=base)).returncode == 0
        path.parent.mkdir(parents=True, exist_ok=True)
        added = await proc.run(
            ["git", "worktree", "add", "-q", "-B", head, str(path), f"origin/{head if fix else branch}"], cwd=base, timeout=120)
        if added.returncode != 0:
            raise _fail(added, "worktree add failed")
    return Item(repo, number, head, path, created_branch=not existed)


async def _release(gate: Gate, item: Item) -> None:
    await asyncio.to_thread(_copy_state, item.path / STATE, state_home(item.repo, item.number) / STATE, True)
    async with gate.repo_lock(item.repo):
        await _drop(item.repo, item.number, item.path)
        if item.created_branch and (item.published or item.failed):
            await proc.run(["git", "branch", "-D", item.head], cwd=item.base, timeout=60)


@asynccontextmanager
async def checkout(gate: Gate, repo: str, branch: str, number: int, fix: bool = False) -> AsyncIterator[Item]:
    """The item's worktree for the `with` block, one of the gate's slots. It is removed on success, failure, cancel and SIGTERM."""
    async with gate.slots:
        item = None
        try:
            item = await _acquire(gate, repo, branch, number, fix)
            await asyncio.to_thread(_copy_state, state_home(repo, number) / STATE, item.path / STATE, False)
            yield item
        except BaseException:
            if item is not None:
                item.failed = True
            raise
        finally:
            if item is not None:
                cleanup = asyncio.ensure_future(_release(gate, item))
                while not cleanup.done():  # a second cancel waits for the cleanup, it does not skip it
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.shield(cleanup)
                cleanup.result()


async def push(gate: Gate, repo: str, dest: Path, head: str) -> proc.Result:
    """`git push -u` from the item's worktree. It writes the shared .git/config, so it takes the repo lock. Never a force push."""
    async with gate.repo_lock(repo):
        return await proc.run(["git", "push", "-u", "origin", head], cwd=dest, timeout=180)


def conflict_groups(paths: Sequence[frozenset[str]]) -> list[list[int]]:
    """Indices of the items grouped by shared target files (transitively), each group in batch order."""
    groups: list[tuple[set[str], list[int]]] = []
    for index, wanted in enumerate(paths):
        hit = [g for g in groups if g[0] & wanted]
        merged: tuple[set[str], list[int]] = (set(wanted), [index])
        for group in hit:
            groups.remove(group)
            merged = (merged[0] | group[0], group[1] + merged[1])
        merged[1].sort()
        groups.append(merged)
    return [members for _paths, members in groups]


async def run_batch(items: Sequence[T], paths_of: Callable[[T], frozenset[str]],
                    run_one: Callable[[T], Awaitable[object]]) -> list:
    """Run every item, those that share a target file one after the other, the rest at once. Results are in batch order."""
    results: list = [None] * len(items)

    async def run_group(indices: list[int]) -> None:
        for index in indices:
            results[index] = await run_one(items[index])

    # return_exceptions: gather without it ends at the first item that stops, and then asyncio.run cancels the cleanup of the others
    done = await asyncio.gather(*(run_group(g) for g in conflict_groups([paths_of(i) for i in items])), return_exceptions=True)
    for outcome in done:
        if isinstance(outcome, BaseException):
            raise outcome
    return results


def cancel_on_sigterm() -> None:
    """SIGTERM cancels the current task, so the `finally` of every live item removes its worktree before the process ends."""
    task = asyncio.current_task()
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    except NotImplementedError:
        state.log("SIGTERM handler unavailable on this platform: a stopped service leaves its worktrees for the next run")
