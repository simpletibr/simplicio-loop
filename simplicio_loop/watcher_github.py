"""Watcher GitHub adapter: #1470 (canonical status comment with claim) + #1471 (patrol PRs for fix tasks).

This module is a thin async layer over `simplicio_loop.github_lifecycle`,
`simplicio_loop.pr_patrol` and `simplicio_loop.pr_evidence.publish_comment`:

  * `post_status()` keeps ONE marker comment per issue updated in place. The current state
    is parsed from that canonical comment (the `| Estado |` row), never defaulted: a
    transport failure propagates as `GitHubTransportError`. Invalid transitions are refused
    with a `reason_code` (`github_lifecycle.validate_transition`).
  * `claim_on_github()` writes the claim (state CLAIMED plus the owner in the `| Agente |`
    row) to that same comment; a different owner already on the comment is refused.
  * `patrol_open_prs()` runs `PrPatrol.inspect(final=True)` and turns review comments,
    failing checks and conflicts into fix tasks {pr, kind, text, files}. Read-only: it
    only issues `gh pr list`, `gh pr view` and GET `gh api` calls.

Blocking `gh` calls run in `asyncio.to_thread`.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import github_lifecycle as _github_lifecycle
from . import pr_patrol as _pr_patrol

_STATE_ROW = re.compile(r"^\| Estado \| (\S+) \|$", re.MULTILINE)
_AGENT_ROW = re.compile(r"^\| Agente \| (.+?) \|$", re.MULTILINE)


class LifecycleCommentError(RuntimeError):
    """The canonical status comment exists but its state row cannot be parsed."""


def _split_repo(repo: str) -> Tuple[str, str]:
    owner, sep, name = str(repo).partition("/")
    if not sep or not owner or not name:
        raise ValueError("repo must be owner/name, got %r" % (repo,))
    return owner, name


def _default_publisher() -> Callable[..., Dict[str, Any]]:
    from .pr_evidence import publish_comment
    return publish_comment


def read_lifecycle(repo: str, issue: str, *, runner: Callable = subprocess.run,
                   timeout: int = 20) -> Dict[str, Any]:
    """Current {state, agent, comment_id} parsed from the issue's canonical comment.

    No marker comment means nothing was ever posted, which is the DISCOVERED state.
    Transport failures raise `GitHubTransportError`; they are never read as DISCOVERED.
    """
    owner, name = _split_repo(repo)
    details = _github_lifecycle.get_details(owner, name, str(issue), runner=runner, timeout=timeout)
    canonical = details.get("canonical_comment")
    if not canonical:
        return {"state": "DISCOVERED", "agent": "", "comment_id": None}
    body = canonical.get("body") or ""
    state = _STATE_ROW.search(body)
    if not state or state.group(1) not in _github_lifecycle.LIFECYCLE_STATES:
        raise LifecycleCommentError("canonical comment %s has no valid state row" % canonical.get("id"))
    agent = _AGENT_ROW.search(body)
    return {"state": state.group(1), "agent": agent.group(1).strip() if agent else "",
            "comment_id": canonical.get("id")}


@dataclass
class ClaimReceipt:
    """Receipt for a claim operation."""
    repo: str
    issue: str
    claimed_by: str
    state: str
    verified: bool
    reason: str = ""


@dataclass
class FixTask:
    """A fix task generated from PR feedback."""
    pr: int
    kind: str  # "review_comment", "checks_failed", "conflict", "rebase_required"
    text: str
    files: List[str] = field(default_factory=list)
    head: str = ""  # the PR head branch, e.g. loop/issue-7


async def post_status(
    *,
    repo: str,
    issue: str,
    state: str,
    detail: str = "",
    agent_id: str = "",
    reason_code: str = "",
    run_id: str = "watcher",
    attempt_id: str = "",
    publish_comment_fn: Optional[Callable] = None,
    runner: Callable = subprocess.run,
    timeout: int = 20,
) -> Dict[str, Any]:
    """Post/update the issue's ONE canonical status comment, refusing invalid transitions.

    The current state is read from the canonical comment; `reason_code` may carry a
    `REGRESSION_REASON_CODES` value to authorize a regression. An omitted `agent_id`
    keeps the owner already on the comment. Returns the verified
    `simplicio.github-lifecycle-receipt/v1`; a refused transition returns
    `outcome: "blocked"` with the validator's `reason_code`.
    """
    owner, name = _split_repo(repo)
    current = await asyncio.to_thread(read_lifecycle, repo, str(issue), runner=runner, timeout=timeout)
    verdict = _github_lifecycle.validate_transition(current["state"], state, reason_code=reason_code)
    if not verdict["ok"]:
        return {
            "schema": _github_lifecycle.LIFECYCLE_SCHEMA,
            "verified": False,
            "outcome": "blocked",
            "reason_code": verdict["reason_code"],
            "reason": verdict["reason"],
            "previous_state": current["state"],
            "state": state,
            "repo": repo,
            "issue": str(issue),
        }
    render_kwargs: Dict[str, Any] = {"agent_id": agent_id or current["agent"]}
    if detail:
        render_kwargs["progress"] = detail
    return await asyncio.to_thread(
        _github_lifecycle.publish_lifecycle_state,
        owner=owner,
        repo=name,
        issue=str(issue),
        state=state,
        run_id=run_id,
        attempt_id=attempt_id or state.lower(),
        publish_comment_fn=publish_comment_fn or _default_publisher(),
        runner=runner,
        timeout=timeout,
        **render_kwargs,
    )


async def claim_on_github(
    *,
    repo: str,
    issue: str,
    owner: str,
    runner: Callable = subprocess.run,
    timeout: int = 20,
) -> ClaimReceipt:
    """Make `owner`'s claim visible on the issue's canonical comment.

    Refuses (verified=False, reason `claimed_by_other`) when the comment already names a
    different owner, and is a no-op when `owner` already holds it. After the write the
    comment is re-read: if another owner overwrote it in the meantime the claim is
    reported as `lost_race`.
    """
    if not str(owner).strip():
        raise ValueError("owner is required")
    owner = str(owner).strip()
    current = await asyncio.to_thread(read_lifecycle, repo, str(issue), runner=runner, timeout=timeout)
    holder = current["agent"]
    if holder and holder != owner:
        return ClaimReceipt(repo, str(issue), holder, current["state"], False, "claimed_by_other")
    if holder == owner and current["state"] != "DISCOVERED":
        return ClaimReceipt(repo, str(issue), owner, current["state"], True, "already_claimed")

    result = await post_status(repo=repo, issue=str(issue), state="CLAIMED", agent_id=owner,
                               run_id="watcher-claim", runner=runner, timeout=timeout)
    if not result.get("verified"):
        return ClaimReceipt(repo, str(issue), holder, str(result.get("state", "")), False,
                            str(result.get("reason_code") or "unverified"))
    after = await asyncio.to_thread(read_lifecycle, repo, str(issue), runner=runner, timeout=timeout)
    if after["agent"] != owner:
        return ClaimReceipt(repo, str(issue), after["agent"], after["state"], False, "lost_race")
    return ClaimReceipt(repo, str(issue), owner, after["state"], True, "claimed")


async def patrol_open_prs(
    *,
    repo: str,
    branch_filter: str = "loop",
    runner: Callable = subprocess.run,
    timeout: int = 30,
) -> List[FixTask]:
    """Fix tasks for the open PRs whose head branch contains `branch_filter`.

    Runs `PrPatrol.inspect(final=True)` (so the cadence gate is open on every tick), then
    reads each actionable PR's reviews, inline review comments and failing checks. Read-only:
    never merges, closes, edits or rewrites a PR.
    """
    patrol = _pr_patrol.PrPatrol(repo, runner=runner, timeout=timeout)
    report = await asyncio.to_thread(patrol.inspect, final=True)
    tasks: List[FixTask] = []
    for pr in report["action_required"]:
        if branch_filter and branch_filter not in pr["head"]:
            continue
        found = await asyncio.to_thread(_tasks_for_pr, patrol, pr)
        for task in found:
            task.head = pr["head"]
        tasks.extend(found)
    return tasks


def _tasks_for_pr(patrol: _pr_patrol.PrPatrol, pr: Dict[str, Any]) -> List[FixTask]:
    number, signals = pr["number"], pr["signals"]
    view = json.loads(patrol._gh([
        "pr", "view", str(number), "--repo", patrol.repo, "--json", "reviews,files,statusCheckRollup",
    ]).stdout or "{}")
    pr_files = [f["path"] for f in view.get("files") or [] if f.get("path")]
    tasks: List[FixTask] = []
    if "CONFLICTING" in signals:
        tasks.append(FixTask(number, "conflict",
                             "PR #%s (%s) conflicts with %s: merge the base into the branch and resolve."
                             % (number, pr["head"], pr["base"]), pr_files))
    elif "REBASE_REQUIRED" in signals:
        tasks.append(FixTask(number, "rebase_required",
                             "PR #%s (%s) is behind %s: merge the base into the branch."
                             % (number, pr["head"], pr["base"]), pr_files))
    if "REVIEW_CHANGES_REQUESTED" in signals:
        tasks.append(_review_task(patrol, number, view.get("reviews") or [], pr_files))
    if "CHECKS_FAILED" in signals:
        failing = [str(c.get("name") or c.get("context") or "unnamed check")
                   for c in view.get("statusCheckRollup") or []
                   if "CHECKS_FAILED" in _pr_patrol.classify_pr({"statusCheckRollup": [c]})["signals"]]
        tasks.append(FixTask(number, "checks_failed",
                             "PR #%s has failing checks: %s" % (number, ", ".join(failing)), pr_files))
    return tasks


def _review_task(patrol: _pr_patrol.PrPatrol, number: int, reviews: List[Dict[str, Any]],
                 pr_files: List[str]) -> FixTask:
    latest: Dict[str, Dict[str, Any]] = {}
    for review in reviews:  # chronological: the last review per author is the standing one
        latest[str((review.get("author") or {}).get("login") or "")] = review
    parts = ["%s: %s" % (author or "reviewer", str(r.get("body") or "").strip())
             for author, r in latest.items()
             if r.get("state") == "CHANGES_REQUESTED" and str(r.get("body") or "").strip()]
    inline = json.loads(patrol._gh([
        "api", "repos/%s/pulls/%s/comments?per_page=100" % (patrol.repo, number),
    ]).stdout or "[]")
    files: List[str] = []
    for comment in inline:
        path = str(comment.get("path") or "")
        parts.append("%s:%s %s" % (path, comment.get("line") or comment.get("original_line") or "",
                                   str(comment.get("body") or "").strip()))
        if path and path not in files:
            files.append(path)
    text = "\n".join(parts) or "changes requested without comment text"
    return FixTask(number, "review_comment", "PR #%s review feedback:\n%s" % (number, text),
                   files or pr_files)


__all__ = [
    "ClaimReceipt",
    "FixTask",
    "LifecycleCommentError",
    "claim_on_github",
    "patrol_open_prs",
    "post_status",
    "read_lifecycle",
]
