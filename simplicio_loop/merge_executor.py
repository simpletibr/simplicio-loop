"""Merge executor (issue #288): once a claimed task's worktree work is VERIFIED
(``simplicio_loop.receipt_verifier.verify_receipt`` passes), actually perform the merge --
create the PR (idempotent), poll for a mergeable state, merge it, and then *reconcile*
against the remote afterward instead of trusting the merge command's exit code alone.

Formalizes, as a reusable, testable primitive, the ad-hoc ``gh pr create`` / ``gh pr merge
--squash --delete-branch`` pattern this project's own delivery workflow already performs by
hand at the end of every task (see AGENTS.md "Process" section) -- the epic-288
gap this closes is that pattern living only as prose an operator must remember, with no
programmatic remote-state check that the merge actually landed.

Deliberately transport-shaped like ``simplicio_loop/github_lifecycle.py``: every GitHub call
goes through an injectable ``runner`` (default ``subprocess.run``) so unit tests can supply a
deterministic fake, and a real, non-mocked e2e is still possible by injecting the real
``subprocess.run`` against disposable scratch branches (see
``tests/test_merge_executor_live_e2e.py``).
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional

from .watcher247.closing_words import sanitize

SCHEMA = "simplicio.merge-result/v1"

Runner = Callable[..., "subprocess.CompletedProcess[str]"]

# gh's mergeStateStatus values that mean "would merge cleanly right now" per GitHub's API.
_CLEAN_STATES = {"CLEAN", "UNSTABLE", "HAS_HOOKS"}
_BLOCKED_MERGEABLE = {"CONFLICTING"}


class MergeExecutorError(RuntimeError):
    """A `gh` call itself failed (network, auth, bad repo/branch) -- distinct from a merge
    that ran but was rejected (conflicts, blocked checks), which is reported as a
    :class:`MergeResult` with ``merged=False`` instead of raised."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class MergeResult:
    schema: str
    pr_number: int
    pr_url: str
    merged: bool
    reconciled: bool
    reason_code: str
    detail: str
    merge_commit_sha: str = ""
    base_ref: str = ""
    post_merge_patrol: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "pr_number": self.pr_number,
            "pr_url": self.pr_url,
            "merged": self.merged,
            "reconciled": self.reconciled,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "merge_commit_sha": self.merge_commit_sha,
            "base_ref": self.base_ref,
            "post_merge_patrol": self.post_merge_patrol,
        }


class MergeExecutor:
    """Create/find a PR for a claimed work item's branch, wait for it to become mergeable,
    merge it, and reconcile remote state afterward. Never assumes; every step that matters
    re-queries the API rather than trusting the previous call's stated intent."""

    def __init__(self, *, repo: str, runner: Runner = subprocess.run, timeout: int = 30) -> None:
        if not str(repo).strip():
            raise ValueError("repo is required (owner/name)")
        self.repo = str(repo).strip()
        self.runner = runner
        self.timeout = timeout

    def _gh(self, args, *, check: bool = True) -> "subprocess.CompletedProcess[str]":
        completed = self.runner(["gh"] + list(args), capture_output=True, text=True, timeout=self.timeout)
        if check and completed.returncode != 0:
            raise MergeExecutorError(
                "GH_CLI_FAILED",
                "gh %s failed (exit %d): %s" % (" ".join(args), completed.returncode,
                                                (completed.stderr or completed.stdout or "").strip()),
            )
        return completed

    # ------------------------------------------------------------------ PR creation ----

    def find_existing_pr(self, branch: str) -> Optional[Dict[str, Any]]:
        """Idempotency: never open a second PR for a branch that already has one."""
        completed = self._gh(
            ["pr", "list", "--repo", self.repo, "--head", branch, "--state", "all",
             "--json", "number,url,state,mergeable,mergeStateStatus"],
            check=False,
        )
        if completed.returncode != 0:
            return None
        try:
            items = json.loads(completed.stdout or "[]")
        except (ValueError, TypeError):
            return None
        if not items:
            return None
        # Prefer an OPEN one; otherwise the most recent entry gh returned.
        for item in items:
            if item.get("state") == "OPEN":
                return item
        return items[0]

    def ensure_pr(self, *, branch: str, base: str, title: str, body: str) -> Dict[str, Any]:
        """Create the PR for ``branch`` -> ``base`` if none exists yet; otherwise return the
        existing one unchanged. Safe to call repeatedly (e.g. on a retried attempt)."""
        existing = self.find_existing_pr(branch)
        if existing is not None and existing.get("state") == "OPEN":
            return existing
        try:
            title = sanitize(title, "PR title")  # a closing word in a PR closes the issue on merge (#1644)
            body = sanitize(body, "PR body")
        except RuntimeError as e:
            raise MergeExecutorError(
                "CLOSING_WORD_REFUSED",
                str(e),
            )
        completed = self._gh([
            "pr", "create", "--repo", self.repo, "--head", branch, "--base", base,
            "--title", title, "--body", body,
        ])
        lines = [line for line in completed.stdout.strip().splitlines() if line.strip()]
        url = lines[-1] if lines else ""
        number_str = url.rstrip("/").rsplit("/", 1)[-1]
        try:
            number = int(number_str)
        except ValueError:
            number = 0
        return {"number": number, "url": url, "state": "OPEN", "mergeable": None, "mergeStateStatus": ""}

    # ------------------------------------------------------------- mergeability wait ----

    def poll_mergeable(self, pr_number: int, *, poll_interval: float = 2.0, timeout: float = 120.0,
                        sleep: Callable[[float], None] = time.sleep,
                        clock: Callable[[], float] = time.time) -> Dict[str, Any]:
        """Poll `gh pr view` until GitHub has computed a mergeable verdict (it is computed
        asynchronously server-side and is briefly ``UNKNOWN`` right after PR creation), or
        until the PR closes/conflicts, or until ``timeout`` elapses."""
        deadline = clock() + timeout
        last: Dict[str, Any] = {}
        while True:
            completed = self._gh(["pr", "view", str(pr_number), "--repo", self.repo,
                                  "--json", "state,mergeable,mergeStateStatus"])
            last = json.loads(completed.stdout or "{}")
            if last.get("state") != "OPEN":
                return last
            mergeable = last.get("mergeable")
            if mergeable in _BLOCKED_MERGEABLE:
                return last
            if mergeable == "MERGEABLE" and last.get("mergeStateStatus") in _CLEAN_STATES:
                return last
            if clock() >= deadline:
                return last
            sleep(poll_interval)

    # ------------------------------------------------------------------------ merge -----

    def merge(self, pr_number: int, *, strategy: str = "squash", delete_branch: bool = True,
               poll_interval: float = 2.0, mergeable_timeout: float = 120.0,
               post_merge_patrol: bool = True,
               sleep: Callable[[float], None] = time.sleep,
               clock: Callable[[], float] = time.time) -> MergeResult:
        """Wait for mergeability, merge, then reconcile against the remote. Never raises for
        an ordinary "can't merge yet" outcome -- those come back as ``merged=False`` with a
        specific ``reason_code`` so a caller (e.g. the loop's saga) can retry or escalate."""
        state = self.poll_mergeable(pr_number, poll_interval=poll_interval, timeout=mergeable_timeout,
                                    sleep=sleep, clock=clock)
        if state.get("state") != "OPEN":
            return MergeResult(SCHEMA, pr_number, "", False, False, "PR_NOT_OPEN",
                               "PR state is %r, not OPEN" % state.get("state"))
        if state.get("mergeable") in _BLOCKED_MERGEABLE:
            return MergeResult(SCHEMA, pr_number, "", False, False, "CONFLICTING",
                               "PR has merge conflicts against its base branch")
        if state.get("mergeable") != "MERGEABLE":
            return MergeResult(SCHEMA, pr_number, "", False, False, "NOT_MERGEABLE_YET",
                               "GitHub had not computed MERGEABLE within %.0fs (last=%r)"
                               % (mergeable_timeout, state))

        args = ["pr", "merge", str(pr_number), "--repo", self.repo, "--%s" % strategy]
        if delete_branch:
            args.append("--delete-branch")
        completed = self._gh(args, check=False)
        if completed.returncode != 0:
            return MergeResult(SCHEMA, pr_number, "", False, False, "MERGE_COMMAND_FAILED",
                               (completed.stderr or completed.stdout or "").strip())

        reconciled = self.reconcile(pr_number)
        if not reconciled["merged"]:
            return MergeResult(SCHEMA, pr_number, "", False, False, "RECONCILE_MISMATCH",
                               "gh pr merge exited 0 but re-query shows state=%r merge_commit=%r"
                               % (reconciled["state"], reconciled["merge_commit_sha"]))
        patrol: Dict[str, Any] = {}
        if post_merge_patrol:
            # A merge changes main's conflict surface for every other open branch.
            # Re-query them immediately; this is read-only and never changes the
            # already-proven merged result into a fabricated failure.
            patrol = self.patrol_open_prs()
        return MergeResult(SCHEMA, pr_number, "", True, True, "OK", "merged and reconciled",
                           merge_commit_sha=reconciled["merge_commit_sha"], base_ref=reconciled["base_ref"],
                           post_merge_patrol=patrol)

    def patrol_open_prs(self) -> Dict[str, Any]:
        """Inspect every remaining open PR after a merge, without mutating it.

        A patrol transport failure is an explicit ``unverified`` receipt rather
        than an assumption that the other branches are conflict-free.
        """
        from .pr_patrol import PrPatrol, PrPatrolError, SCHEMA as PATROL_SCHEMA

        try:
            return PrPatrol(self.repo, runner=self.runner, timeout=self.timeout).inspect(post_merge=True)
        except PrPatrolError as exc:
            return {
                "schema": PATROL_SCHEMA,
                "repo": self.repo,
                "due": True,
                "reason": "post_merge",
                "status": "unverified",
                "reason_code": "POST_MERGE_PATROL_FAILED",
                "detail": str(exc),
                "open_prs": [],
                "action_required": [],
                "clean": [],
            }

    # ------------------------------------------------------- remote-target reconciliation

    def reconcile(self, pr_number: int) -> Dict[str, Any]:
        """Re-query the PR after a merge/delivery action instead of assuming the prior call's
        exit code tells the whole story (the epic-288 "remote-target reconciliation" gap).
        ``merged`` is only true when GitHub itself reports ``state == MERGED`` AND a real
        merge-commit sha is attached -- either alone is not proof."""
        completed = self._gh(["pr", "view", str(pr_number), "--repo", self.repo,
                              "--json", "state,mergeCommit,baseRefName"])
        data = json.loads(completed.stdout or "{}")
        merge_commit = data.get("mergeCommit") or {}
        sha = str(merge_commit.get("oid") or "")
        merged = data.get("state") == "MERGED" and bool(sha)
        return {
            "merged": merged,
            "state": data.get("state"),
            "merge_commit_sha": sha,
            "base_ref": data.get("baseRefName") or "",
        }


__all__ = ["MergeExecutor", "MergeExecutorError", "MergeResult", "SCHEMA"]
