"""Watcher GitHub adapter: #1470 (canonical status comment with claim) + #1471 (patrol PRs for fix tasks).

This module adapts issues #1470 and #1471 as a standalone async wrapper around the existing
primitives in `simplicio_loop.github_lifecycle`, `simplicio_loop.pr_patrol`, and
`scripts.pr_evidence.publish_comment`:

  * `post_status()` — keep a single status comment updated, rejecting invalid transitions with
    a reason. Reuses `github_lifecycle.publish_lifecycle_state()` to ensure idempotency and
    re-query verification.
  * `claim_on_github()` — mark a claim visible on GitHub (via the status comment state or a
    label) so another session/machine skips the issue. Reuses the same canonical comment,
    never creates a second one.
  * `patrol_open_prs()` — list the loop's open PRs, read review comments and failing checks,
    and return fix tasks {pr, kind, text, files}. Never merges, closes, or rewrites. Reuses
    `pr_patrol.PrPatrol` for read-only feedback collection.

Async-safe: wraps blocking `gh` calls in `asyncio.to_thread` so caller can run multiple
issues in parallel without blocking.

Tested with fake gh (no real GitHub writes).
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional

from . import github_lifecycle as _github_lifecycle
from . import pr_patrol as _pr_patrol


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
    files: List[str] = None

    def __post_init__(self):
        if self.files is None:
            self.files = []


async def post_status(
    *,
    repo: str,
    issue: str,
    state: str,
    detail: str = "",
    owner: str = "",
    run_id: str = "watcher",
    attempt_id: str = "",
    publish_comment_fn: Optional[Callable] = None,
    runner: Callable = subprocess.run,
    timeout: int = 20,
) -> Dict[str, Any]:
    """Post/update a single status comment on the issue, rejecting invalid transitions.

    Args:
        repo: GitHub repo (owner/name)
        issue: GitHub issue number
        state: Target lifecycle state (DISCOVERED, CLAIMED, PLANNED, etc.)
        detail: Optional detail message to include in the status
        owner: GitHub owner (extracted from repo if not provided)
        run_id: Run ID for the receipt (default: "watcher")
        attempt_id: Attempt ID for the receipt
        publish_comment_fn: Comment publisher (from scripts.pr_evidence, injected by caller)
        runner: Subprocess runner (injectable for testing)
        timeout: gh command timeout in seconds

    Returns:
        A `simplicio.github-lifecycle-receipt/v1` receipt dict with verified/outcome/state.
        Invalid transitions are rejected with reason_code in the dict.
    """
    if not publish_comment_fn:
        from scripts.pr_evidence import publish_comment as _pub
        publish_comment_fn = _pub

    if "/" not in repo or not owner:
        owner = repo.split("/")[0] if "/" in repo else owner
    repo_name = repo.split("/")[1] if "/" in repo else repo

    # Validate the transition
    current_state = await _get_current_state(repo, issue, runner, timeout)
    validation = _github_lifecycle.validate_transition(current_state, state)
    if not validation["ok"]:
        return {
            "schema": "simplicio.github-lifecycle-receipt/v1",
            "verified": False,
            "outcome": "blocked",
            "reason_code": validation["reason_code"],
            "reason": validation["reason"],
            "state": state,
            "repo": repo,
            "issue": str(issue),
        }

    # Publish the new state
    render_kwargs = {}
    if detail:
        render_kwargs["progress"] = detail

    result = await asyncio.to_thread(
        _github_lifecycle.publish_lifecycle_state,
        owner=owner,
        repo=repo_name,
        issue=str(issue),
        state=state,
        run_id=run_id,
        attempt_id=attempt_id or state.lower(),
        publish_comment_fn=publish_comment_fn,
        runner=runner,
        timeout=timeout,
        **render_kwargs,
    )
    return result


async def claim_on_github(
    *,
    repo: str,
    issue: str,
    owner: str = "",
    runner: Callable = subprocess.run,
    timeout: int = 20,
) -> ClaimReceipt:
    """Mark a claim visible on GitHub through the status comment state.

    This transitions the issue state to CLAIMED and ensures the state is visible
    on GitHub so another session/machine can see it without re-querying claims.json.

    Args:
        repo: GitHub repo (owner/name)
        issue: GitHub issue number
        owner: GitHub owner (extracted from repo if not provided)
        runner: Subprocess runner (injectable for testing)
        timeout: gh command timeout in seconds

    Returns:
        A ClaimReceipt with verified status and reason.
    """
    if "/" not in repo or not owner:
        owner = repo.split("/")[0] if "/" in repo else owner
    repo_name = repo.split("/")[1] if "/" in repo else repo

    # Post the claim state
    result = await post_status(
        repo=repo,
        issue=str(issue),
        state="CLAIMED",
        owner=owner,
        run_id="watcher-claim",
        publish_comment_fn=None,
        runner=runner,
        timeout=timeout,
    )

    verified = result.get("verified", False)
    reason = result.get("reason", "")
    if not verified:
        reason = result.get("reason_code", "unknown") + ": " + reason

    return ClaimReceipt(
        repo=repo,
        issue=str(issue),
        claimed_by="watcher",
        state=result.get("state", "CLAIMED"),
        verified=verified,
        reason=reason,
    )


async def patrol_open_prs(
    *,
    repo: str,
    author_filter: str = "loop",
    runner: Callable = subprocess.run,
    timeout: int = 30,
) -> List[FixTask]:
    """List open PRs matching the author filter and convert feedback to fix tasks.

    Reads review comments, check failures, merge conflicts and rebasing needs,
    then generates fix tasks. Never merges, closes or rewrites a PR.

    Args:
        repo: GitHub repo (owner/name)
        author_filter: Filter for PR head branch name (default: "loop" matches loop/issue-*)
        runner: Subprocess runner (injectable for testing)
        timeout: gh command timeout in seconds

    Returns:
        A list of FixTask objects, one per actionable feedback item.
    """
    patrol = _pr_patrol.PrPatrol(repo, runner=runner, timeout=timeout)

    # Get the list of open PRs
    report = await asyncio.to_thread(patrol.inspect)

    if not report.get("open_prs"):
        return []

    tasks: List[FixTask] = []

    # Filter PRs matching the author pattern
    prs = report["open_prs"]
    if author_filter:
        prs = [pr for pr in prs if author_filter in pr.get("head", "")]

    # For each PR, check its signals and create fix tasks
    for pr in prs:
        pr_number = pr["number"]
        signals = pr.get("signals", [])

        for signal in signals:
            if signal == "CONFLICTING":
                tasks.append(FixTask(
                    pr=pr_number,
                    kind="conflict",
                    text=f"PR #{pr_number} has merge conflicts. Rebase or resolve conflicts.",
                ))
            elif signal == "REBASE_REQUIRED":
                tasks.append(FixTask(
                    pr=pr_number,
                    kind="rebase_required",
                    text=f"PR #{pr_number} needs to be rebased on main.",
                ))
            elif signal == "REVIEW_CHANGES_REQUESTED":
                tasks.append(FixTask(
                    pr=pr_number,
                    kind="review_comment",
                    text=f"PR #{pr_number} has requested changes. Address the review feedback.",
                ))
            elif signal == "REVIEW_REQUIRED":
                tasks.append(FixTask(
                    pr=pr_number,
                    kind="review_required",
                    text=f"PR #{pr_number} requires approval. Request review or address feedback.",
                ))
            elif signal == "CHECKS_FAILED":
                tasks.append(FixTask(
                    pr=pr_number,
                    kind="checks_failed",
                    text=f"PR #{pr_number} has failing checks. Fix the failing tests/checks.",
                ))

    return tasks


async def _get_current_state(
    repo: str, issue: str, runner: Callable, timeout: int
) -> str:
    """Get the current lifecycle state of an issue by reading the status comment.

    Returns the state from the canonical comment marker, or "DISCOVERED" as default.
    """
    try:
        owner = repo.split("/")[0] if "/" in repo else ""
        repo_name = repo.split("/")[1] if "/" in repo else repo

        details = await asyncio.to_thread(
            _github_lifecycle.get_details,
            owner, repo_name, str(issue),
            runner=runner, timeout=timeout,
        )
        state = details.get("lifecycle_state", "DISCOVERED")
        return state
    except Exception:
        return "DISCOVERED"  # default to DISCOVERED if we can't read the state


__all__ = [
    "post_status",
    "claim_on_github",
    "patrol_open_prs",
    "ClaimReceipt",
    "FixTask",
]
