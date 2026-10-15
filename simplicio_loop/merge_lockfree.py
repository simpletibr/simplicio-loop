"""Lock-free merge mode for the merge train (#1820). OFF by default: `batch` is the train of #1504, and nothing here runs unless
SIMPLICIO_247_MERGE_MODE is exactly `lockfree` (the watcher's `watch247 --mode lockfree` sets it).

The model (Anthropic's in-house source control, https://www.anthropic.com/engineering/redesigning-source-control): an approved PR
merges when its targeted tests are green, without a global lock or queue. The impacted tests then run on main after the merge. On
red, the loop opens a REVERT PR (or a fix task for the owning squad). It never force-pushes, never rewrites history, and never
merges a revert: a human or the merge coordinator does.

Rules that do not change in this mode:

* the approval gate (`squads.squad_gate`, the approval written by the watcher's own login) comes first, for every PR;
* the merge is pinned to the reviewed head (`gh pr merge --match-head-commit`);
* a PR on a file whose merge is still unverified waits (`wait`), it is never stacked on it;
* after a red, no further lock-free merge happens in the same tick.

Pure decisions (`decide_merge`, `merge_pass`, `post_merge_check`) take injected callables, so the tests run them over fakes. `Forge` is
the git and gh adapter; its `run` is injected too (watcher247.proc.run in production). Scaling claims for this mode are UNVERIFIED:
no benchmark measures them yet (see docs/MERGE_LOCKFREE.md).
"""

from __future__ import annotations

import inspect
import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODE_BATCH = "batch"
MODE_LOCKFREE = "lockfree"
MODES = (MODE_BATCH, MODE_LOCKFREE)
MODE_ENV = "SIMPLICIO_247_MERGE_MODE"
RED_POLICY = "revert"  # on a red post-merge run: a revert PR; a fix task only when the revert cannot be opened (or policy="fix")
TRAIN_FETCH_DEPTH = "100"  # the clone is shallow: enough history for the merge commit and its parent
_FAILED = re.compile(r"^FAILED (\S+)", re.MULTILINE)


@dataclass(frozen=True)
class Result:
    """The shape of watcher247.proc.Result: returncode, stdout, stderr."""
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class PRState:
    pr: int
    issue: int
    head: str  # the reviewed head commit: the merge is pinned to it
    files: frozenset
    approved: bool  # the approval gate (squad_gate) passed on this head
    gate_reason: str = ""
    tests_green: bool = False  # the worker's targeted tests were measured green on this head
    squad: str = ""  # the owning squad: a red after its merge goes to it


@dataclass(frozen=True)
class Decision:
    action: str  # merge | wait | refuse
    reason: str


@dataclass(frozen=True)
class PostMerge:
    status: str  # green | red | pending (the run did not finish: the merge stays unverified, it is not a red)
    failing: tuple = ()
    tests: tuple = ()
    reason: str = ""


@dataclass(frozen=True)
class Red:
    pr: int
    issue: int
    squad: str
    merge_sha: str
    failing: tuple


@dataclass(frozen=True)
class Action:
    kind: str  # open_revert_pr | open_fix_task
    url: str
    detail: str = ""


class RevertError(RuntimeError):
    """The revert PR could not be opened. Nothing was merged or force-pushed; the caller opens a fix task instead."""


@dataclass
class PassReport:
    merged: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    refused: dict = field(default_factory=dict)  # pr -> reason (the gate, the tests, a red earlier in the tick)
    waited: dict = field(default_factory=dict)  # pr -> reason (a file still unverified)
    pending: dict = field(default_factory=dict)  # pr -> reason (merged; its post-merge run did not finish)
    red: dict | None = None
    actions: list = field(default_factory=list)


async def _call(fn: Callable[..., Any], *args: Any) -> Any:
    out = fn(*args)
    return await out if inspect.isawaitable(out) else out


class Forge:
    """git and gh calls for one repo. `run(argv, timeout=..., cwd=...)` is injected; `base` is the repo's base clone."""

    def __init__(self, full_name: str, base: Path, run: Callable[..., Awaitable[Any]]) -> None:
        self.full = full_name
        self.base = base
        self._run = run

    async def _git(self, *args: str, timeout: float = 180) -> Any:
        return await self._run(["git", *args], timeout=timeout, cwd=self.base)

    async def _gh(self, *args: str, timeout: float = 120) -> Any:
        return await self._run(["gh", *args], timeout=timeout, cwd=None)

    async def merge(self, pr: int, head: str) -> str | None:
        """Squash-merge `pr` pinned to the reviewed `head`. Returns the merge commit, or None when gh refused."""
        done = await self._gh("pr", "merge", str(pr), "--repo", self.full, "--squash", "--match-head-commit", head)
        if done.returncode != 0:
            return None
        sha = (await self._gh("api", f"repos/{self.full}/pulls/{pr}", "--jq", ".merge_commit_sha")).stdout.strip()
        return sha or None

    async def checkout_main(self) -> str:
        """Put the base clone on origin/main and return its commit. Raises when git cannot."""
        if (await self._git("fetch", "--depth", TRAIN_FETCH_DEPTH, "origin", "main")).returncode != 0:
            raise RuntimeError("fetch of origin/main failed")
        if (await self._git("checkout", "-q", "-f", "--detach", "origin/main")).returncode != 0:
            raise RuntimeError("checkout of origin/main failed")
        sha = (await self._git("rev-parse", "HEAD")).stdout.strip()
        if not sha:
            raise RuntimeError("origin/main has no commit")
        return sha

    async def parent(self, sha: str) -> str:
        found = await self._git("rev-parse", f"{sha}^")
        if found.returncode != 0 or not found.stdout.strip():
            raise RuntimeError(f"no parent for {sha[:12]} in the clone")
        return found.stdout.strip()

    async def impacted(self, base_sha: str) -> list | None:
        """The impacted tests of the change `base_sha`..main, from scripts/impact_tests.py. None (= run the full verify) when the
        tool is missing, fails, or selects nothing: an empty selection is never taken as green."""
        found = await self._run(["python3", "scripts/impact_tests.py", "--base", base_sha], timeout=120, cwd=self.base)
        if found.returncode != 0:
            return None
        tests = [line.strip() for line in found.stdout.splitlines() if line.strip()]
        return tests or None

    async def open_revert(self, pr: int, merge_sha: str, title: str, body: str) -> str:
        """A revert PR: `git revert` of the merge commit on a branch from origin/main, pushed without force, then opened as a PR.
        The PR is opened, never merged here. Raises RevertError when any step does not hold."""
        branch = f"revert/pr-{pr}-{merge_sha[:12]}"
        try:
            if (await self._git("fetch", "--depth", TRAIN_FETCH_DEPTH, "origin", "main")).returncode != 0:
                raise RevertError("fetch of origin/main failed")
            if (await self._git("checkout", "-q", "-B", branch, "origin/main")).returncode != 0:
                raise RevertError("branch from origin/main failed")
            reverted = await self._git("revert", "--no-edit", merge_sha)
            if reverted.returncode != 0:
                await self._git("revert", "--abort")
                raise RevertError(f"git revert of {merge_sha[:12]} did not apply: {reverted.stderr.strip()[:200]}")
            if (await self._git("push", "-u", "origin", branch)).returncode != 0:  # no force flag: a branch that exists is refused
                raise RevertError("push of the revert branch was refused")
            opened = await self._gh("api", "-X", "POST", f"repos/{self.full}/pulls", "-f", f"title={title}",
                                    "-f", f"head={branch}", "-f", "base=main", "-f", f"body={body}", "--jq", ".html_url")
            if opened.returncode != 0 or not opened.stdout.strip():
                raise RevertError("the revert pull request was not opened")
            return opened.stdout.strip()
        finally:
            await self._git("checkout", "-q", "--detach", "origin/main")  # best effort: leave the base clone detached

    async def open_fix_task(self, title: str, body: str) -> str:
        opened = await self._gh("api", "-X", "POST", f"repos/{self.full}/issues", "-f", f"title={title}", "-f", f"body={body}",
                                "--jq", ".html_url")
        if opened.returncode != 0 or not opened.stdout.strip():
            raise RuntimeError("the fix task was not opened")
        return opened.stdout.strip()


def mode_from_env(environ: Mapping[str, str] | None = None) -> str:
    """`lockfree` only for exactly that value. Anything else, unset included, is the batch train."""
    value = (os.environ if environ is None else environ).get(MODE_ENV)
    return MODE_LOCKFREE if value == MODE_LOCKFREE else MODE_BATCH


def parse_failing(output: str) -> tuple:
    """The test ids of a pytest run: its `FAILED <id>` short-summary lines."""
    return tuple(_FAILED.findall(output or ""))


def decide_merge(state: PRState, unverified: Mapping[int, frozenset]) -> Decision:
    """merge | wait | refuse for one approved PR. `unverified` maps the PRs merged in this tick whose post-merge run has not
    gone green to their files."""
    if not state.approved:
        return Decision("refuse", f"approval gate: {state.gate_reason or 'no authorized approval on this head'}")
    if not state.head:
        return Decision("refuse", "reviewed head unknown")
    if not state.tests_green:
        return Decision("refuse", "targeted tests not green on the reviewed head")
    clash = sorted(pr for pr, files in unverified.items() if pr != state.pr and files & state.files)
    if clash:
        return Decision("wait", "file overlap with unverified merge of " + ", ".join(f"#{pr}" for pr in clash))
    return Decision("merge", "approved, targeted tests green, no unverified overlap")


async def post_merge_check(main_sha: str, *, impacted: Callable[[str], Awaitable[list | None]],
                           run_tests: Callable[[list | None, str], Awaitable[tuple]]) -> PostMerge:
    """The impacted tests on main at `main_sha` (None = the full verify). A run that cannot finish is `pending`, not red."""
    try:
        selected = list(await _call(impacted, main_sha) or []) or None
        ok, failing = await _call(run_tests, selected, main_sha)
    except Exception as exc:  # noqa: BLE001 - infrastructure failure: the merge stays unverified, nothing is called red
        return PostMerge("pending", reason=f"{type(exc).__name__}: {exc}")
    tests = tuple(selected or ())
    reason = f"{len(tests)} impacted test file(s)" if tests else "no impacted test selected: full verify"
    if ok:
        return PostMerge("green", tests=tests, reason=reason)
    return PostMerge("red", failing=tuple(failing) or ("(verify exited non-zero: no test id named)",), tests=tests, reason=reason)


def _revert_body(red: Red) -> str:
    named = "\n".join(f"- `{t}`" for t in red.failing[:20]) or "- (no test id named)"
    return (f"Reverts #{red.pr} (merge commit `{red.merge_sha}`).\n\nThe post-merge run of the impacted tests on main was red:\n{named}\n\n"
            "Opened by the lock-free merge mode (#1820). The loop does NOT merge this PR: a human or the merge coordinator merges it "
            "after review. Nothing was force-pushed.\n")


async def on_red(red: Red, *, policy: str, forge: Forge) -> Action:
    """After a red post-merge run: a revert PR (policy `revert`), or a fix task for the owning squad (policy `fix`, or when the
    revert cannot be opened). Never a merge."""
    if policy not in ("revert", "fix"):
        raise ValueError(f"policy must be revert or fix: {policy!r}")
    detail = ""
    if policy == "revert":
        try:
            url = await forge.open_revert(red.pr, red.merge_sha, f"Revert #{red.pr}: post-merge tests red on main", _revert_body(red))
            return Action("open_revert_pr", url)
        except RevertError as exc:
            detail = f"revert not opened: {exc}"
    named = "\n".join(f"- `{t}`" for t in red.failing[:20]) or "- (no test id named)"
    body = (f"Post-merge run of the impacted tests on main was red after #{red.pr} (merge commit `{red.merge_sha}`).\n\n"
            f"Owning squad: {red.squad or 'unknown'}\n\nFailing:\n{named}\n\n{detail}\n\n"
            "Opened by the lock-free merge mode (#1820). Nothing was merged or force-pushed to fix this.\n")
    url = await forge.open_fix_task(f"Fix post-merge red after #{red.pr} ({red.squad or 'squad'})", body)
    return Action("open_fix_task", url, detail)


async def merge_pass(prs: Sequence[PRState], *, merge: Callable[..., Awaitable[str | None]],
                     check: Callable[..., Awaitable[PostMerge]], on_red: Callable[..., Awaitable[Action]]) -> PassReport:
    """Walk the approved PRs in order. Each one is decided, merged (no batch, no shared test), and checked on main. Callables:
    `merge(pr, head) -> merge commit | None`, `check(pr, merge_commit) -> PostMerge`, `on_red(Red) -> Action`."""
    report = PassReport()
    unverified: dict[int, frozenset] = {}
    halted = ""
    for state in prs:
        decision = Decision("refuse", halted) if halted else decide_merge(state, unverified)
        if decision.action == "refuse":
            report.refused[state.pr] = decision.reason
            continue
        if decision.action == "wait":
            report.waited[state.pr] = decision.reason
            continue
        merge_sha = await _call(merge, state.pr, state.head)
        if not merge_sha:
            report.failed.append(state.pr)
            continue
        report.merged.append(state.pr)
        try:
            result = await _call(check, state.pr, merge_sha)
        except Exception as exc:  # noqa: BLE001 - a check that cannot run leaves the merge unverified
            result = PostMerge("pending", reason=f"{type(exc).__name__}: {exc}")
        if result.status == "green":
            continue
        if result.status == "pending":
            unverified[state.pr] = state.files
            report.pending[state.pr] = result.reason
            continue
        action = await _call(on_red, Red(pr=state.pr, issue=state.issue, squad=state.squad, merge_sha=merge_sha, failing=result.failing))
        report.actions.append(action)
        report.red = {"pr": state.pr, "merge_sha": merge_sha, "failing": list(result.failing)}
        halted = f"main is red after #{state.pr} ({action.kind} opened): no lock-free merge this tick"
    return report
