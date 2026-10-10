"""The squad coordinator's mechanical review (#1649): `review_gate` over one PR of the watcher's clone.

`evaluate()` fetches the PR, the issue and the git objects, runs the gate on disposable trees under
`.simplicio-loop/review-gate/` of the clone, and returns the GateReport. Posting the verdict is `squad_flow._review`'s job.
A step that cannot run raises ReviewError with its cause, and the cause is shown on the PR.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from ..review_gate import gate as review_gate
from ..review_gate import identity
from ..review_gate.model import GateReport
from . import config, proc, sandbox

FETCH_DEPTH = "200"


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
    full, dest = f"{config.ORG}/{repo}", config.WORK / repo
    view = await _gh(["pr", "view", str(number), "--repo", full, "--json", "body,comments"])
    issue_view = await _gh(["issue", "view", str(issue), "--repo", full, "--json", "body"])
    independent = identity.parse_independent_marker(view.get("comments") or [], head)
    async with lock:  # the gate adds and removes git worktrees of the clone: writes are serialized
        await _git(dest, "fetch", "--depth", FETCH_DEPTH, "origin", "main", f"loop/issue-{issue}")
        fetched = await _git(dest, "rev-parse", f"origin/loop/issue-{issue}")  # FETCH_HEAD holds one line per ref: the first is main
        if not fetched.startswith(head[:7]):
            raise ReviewError(f"branch loop/issue-{issue} is at {fetched[:7]}, not at the reviewed head {head[:7]}")
        base = await _git(dest, "merge-base", "origin/main", head)
        inp = review_gate.GateInput(
            repo=dest, pr=number, issue=issue, issue_body=issue_view.get("body") or "", pr_body=view.get("body") or "",
            base=base, head=head, author=author, independent=independent,
            wrap_for=lambda root: (lambda argv: sandbox.wrap(argv, clone=root, state_dir=config.ROOT)))
        return await asyncio.to_thread(review_gate.run_gate, inp), independent
