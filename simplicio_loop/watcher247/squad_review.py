"""The squad coordinator's mechanical review (#1649): `review_gate` over one PR of the watcher's clone.

`evaluate()` fetches the PR, the issue and the git objects, runs the gate on disposable trees under
`.simplicio-loop/review-gate/` of the clone, and returns the GateReport. Posting the verdict is `squad_flow._review`'s job.
A step that cannot run raises ReviewError with its cause, and the cause is shown on the PR.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from ..review_gate import gate as review_gate
from ..review_gate import identity
from ..review_gate.model import GateReport
from . import config, proc

FETCH_DEPTH = "200"
MAIN_REF = "refs/remotes/origin/main"
FULL_SHA = re.compile(r"[0-9a-f]{40}")


class ReviewError(RuntimeError):
    """The review could not run; the message is the cause."""


async def _gh(argv: list[str]) -> dict[str, Any]:
    done = await proc.run(["gh", *argv], timeout=60)
    if done.returncode != 0:
        raise ReviewError(f"gh {' '.join(argv[:3])} failed: {(done.stderr or done.stdout).strip()[-200:]}")
    try:
        return json.loads(done.stdout)
    except ValueError as exc:
        raise ReviewError(f"gh {' '.join(argv[:3])} returned invalid json") from exc


async def _git(dest: Path, *args: str) -> str:
    done = await proc.run(["git", *args], cwd=dest, timeout=180)
    if done.returncode != 0:
        raise ReviewError(f"git {' '.join(args[:3])} failed: {(done.stderr or done.stdout).strip()[-200:]}")
    return done.stdout.strip()


async def evaluate(repo: str, number: int, issue: int, head: str, author: identity.Agent, lock) -> tuple[GateReport, identity.Agent | None]:
    if not FULL_SHA.fullmatch(head):  # the approval is tied to one commit: a prefix (or any other spelling) is not that commit
        raise ReviewError(f"the reviewed head must be the full 40-character sha, got {head!r}")
    full, dest = f"{config.ORG}/{repo}", config.WORK / repo
    branch = f"loop/issue-{issue}"
    pr_ref = f"refs/remotes/origin/{branch}"
    view = await _gh(["pr", "view", str(number), "--repo", full, "--json", "body,comments"])
    issue_view = await _gh(["issue", "view", str(issue), "--repo", full, "--json", "body"])
    independent = identity.parse_independent_marker(view.get("comments") or [], head)
    async with lock:  # the gate adds and removes git worktrees of the clone: writes are serialized
        # Explicit refspecs: the clone of the item may never have fetched the PR branch (or be single-branch), and then
        # `origin/loop/issue-N` is an ambiguous revision. The refs the gate reads below are the ones fetched here.
        await _git(dest, "fetch", "--depth", FETCH_DEPTH, "origin", f"+refs/heads/main:{MAIN_REF}", f"+refs/heads/{branch}:{pr_ref}")
        fetched = await _git(dest, "rev-parse", "--verify", f"{pr_ref}^{{commit}}")
        if fetched != head:
            raise ReviewError(f"branch {branch} is at {fetched[:7]}, not at the reviewed head {head[:7]}")
        base = await _git(dest, "merge-base", MAIN_REF, head)
        inp = review_gate.GateInput(
            repo=dest, pr=number, issue=issue, issue_body=issue_view.get("body") or "", pr_body=view.get("body") or "",
            base=base, head=head, author=author, independent=independent,
            state_dir=config.ROOT)  # wrap_for stays None: the gate's own jail (bwrap, scrubbed env, empty HOME) or sandbox_unavailable
        return await asyncio.to_thread(review_gate.run_gate, inp), independent
