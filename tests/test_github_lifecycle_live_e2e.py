"""True e2e for issue #285's DoD item: "Teste live opt-in gera receipt auditável de um ciclo
completo em issue sandbox" -- unlike ``tests/test_planning_gate_live_e2e.py`` (which only
carries a live issue through CLAIMED -> PLANNED for #284's mutation-authority proof), this test
drives the GitHub lifecycle adapter itself through a full cycle against a REAL, disposable
GitHub issue: CLAIMED -> IN_PROGRESS -> VERIFYING (with evidence) -> CLOSED, via the real `gh`
CLI, and confirms every step with a real re-query -- ending in ``close_source_issue`` genuinely
closing the issue and the final canonical comment (re-queried) showing CLOSED.

Gate: only runs when SIMPLICIO_LIVE_GH_E2E=1 is set AND `gh` is authenticated. Repo overridable
via SIMPLICIO_LIVE_GH_REPO (defaults to simpletibr/simplicio-loop). Skipped everywhere else
(default local runs, CI without a token) -- never touches the network unless explicitly opted
into, exactly like ``test_planning_gate_live_e2e.py``/``test_merge_executor_live_e2e.py``.

What it proves, against the real API:
  1. `publish_lifecycle_state(state="CLAIMED", ...)` posts a REAL comment on a freshly created
     scratch issue and a real re-query confirms the id/body hash.
  2. `publish_lifecycle_state(state="IN_PROGRESS", ...)` updates the SAME comment id (no new
     comment created) -- real re-query confirms the same id, new body.
  3. `publish_lifecycle_state(state="VERIFYING", tests_and_evidence=...)` attaches evidence text
     to the SAME comment id -- proving `attach_evidence` (via the `SourceAdapter` binding) lands
     on the canonical comment rather than a separate one.
  4. `close_source_issue(...)` performs a REAL `gh issue close`, re-queries and confirms
     `state == "closed"`, then moves the SAME canonical comment to CLOSED and re-queries that
     too -- the full fail-closed, re-query-confirmed close path, not a bare `gh issue close`
     cleanup call.
  5. A final direct `gh api` re-query independently confirms: issue state is `closed`, and
     exactly ONE lifecycle-marker comment exists on the issue (no duplicate created across the
     four writes above).

Cleanup: the scratch issue is already closed by step 4 (that IS the test); nothing further to
clean up. If any assertion fails before step 4, the scratch issue is closed unconditionally in
the `finally` block so a broken assertion never leaves a stray open issue on the tracker.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.external_integration

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, REPO)

from pr_evidence import publish_comment  # noqa: E402  (scripts/ on sys.path for this import)

from simplicio_loop import github_lifecycle  # noqa: E402

LIVE_REPO = os.environ.get("SIMPLICIO_LIVE_GH_REPO", "simpletibr/simplicio-loop")


def _live_gate_open():
    if os.environ.get("SIMPLICIO_LIVE_GH_E2E") != "1":
        return False
    if not shutil.which("gh"):
        return False
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    return r.returncode == 0


def _gh(args, check=True):
    r = subprocess.run(["gh"] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError("gh %s failed: %s" % (" ".join(args), r.stderr or r.stdout))
    return r


def _create_scratch_issue():
    r = _gh([
        "issue", "create", "--repo", LIVE_REPO,
        "--title", "[test-scratch] #285 github-lifecycle live e2e (auto-created, safe to close)",
        "--body", "Auto-created by tests/test_github_lifecycle_live_e2e.py -- drives this "
                  "issue through CLAIMED -> IN_PROGRESS -> VERIFYING -> CLOSED via the real "
                  "GitHub lifecycle adapter, then closes itself as the final assertion. Safe "
                  "to ignore.",
    ])
    url = r.stdout.strip().splitlines()[-1]
    return url.rstrip("/").rsplit("/", 1)[-1]


def _lifecycle_comments(issue):
    r = _gh(["api", "repos/%s/issues/%s/comments" % (LIVE_REPO, issue), "--paginate"])
    comments = json.loads(r.stdout or "[]")
    return [c for c in comments
            if github_lifecycle.LIFECYCLE_COMMENT_MARKER in (c.get("body") or "")]


def test_full_lifecycle_claim_to_closed_on_a_live_scratch_issue():
    if not _live_gate_open():
        pytest.skip(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[live_github_opt_in]: set "
            "SIMPLICIO_LIVE_GH_E2E=1 with an authenticated gh CLI to run this "
            "live e2e against %s" % LIVE_REPO
        )

    owner, repo_name = LIVE_REPO.split("/", 1)
    issue = _create_scratch_issue()
    run_id = "run-285-live-e2e"
    attempt_id = "1"
    try:
        # -- 1. real CLAIMED comment --
        claimed = github_lifecycle.publish_lifecycle_state(
            owner=owner, repo=repo_name, issue=issue, state="CLAIMED",
            run_id=run_id, attempt_id=attempt_id, publish_comment_fn=publish_comment,
        )
        assert claimed["verified"] is True, claimed
        after_claim = _lifecycle_comments(issue)
        assert len(after_claim) == 1, after_claim
        assert "CLAIMED" in after_claim[0]["body"]
        comment_id = after_claim[0]["id"]

        # -- 2. real IN_PROGRESS update, SAME comment --
        in_progress = github_lifecycle.publish_lifecycle_state(
            owner=owner, repo=repo_name, issue=issue, state="IN_PROGRESS",
            run_id=run_id, attempt_id=attempt_id, publish_comment_fn=publish_comment,
            progress="live e2e: doing the work",
        )
        assert in_progress["verified"] is True, in_progress
        after_progress = _lifecycle_comments(issue)
        assert len(after_progress) == 1, after_progress
        assert after_progress[0]["id"] == comment_id, (
            "IN_PROGRESS must update the SAME canonical comment CLAIMED created")
        assert "IN_PROGRESS" in after_progress[0]["body"]

        # -- 3. real VERIFYING update with evidence text, SAME comment (attach_evidence) --
        verifying = github_lifecycle.publish_lifecycle_state(
            owner=owner, repo=repo_name, issue=issue, state="VERIFYING",
            run_id=run_id, attempt_id=attempt_id, publish_comment_fn=publish_comment,
            tests_and_evidence="live e2e: pytest tests/test_github_lifecycle_live_e2e.py -> PASS",
        )
        assert verifying["verified"] is True, verifying
        after_evidence = _lifecycle_comments(issue)
        assert len(after_evidence) == 1, after_evidence
        assert after_evidence[0]["id"] == comment_id, (
            "attach_evidence (VERIFYING) must update the SAME canonical comment, not a new one")
        assert "live e2e: pytest" in after_evidence[0]["body"]

        print("MEASURED|live e2e: issue=%s comment_id=%s CLAIMED -> IN_PROGRESS -> VERIFYING "
              "on one comment" % (issue, comment_id))

        # -- 4. real fail-closed close: gh issue close, re-query-confirmed, then the SAME
        #    comment moved to CLOSED and re-queried again --
        close_receipt = github_lifecycle.close_source_issue(
            owner=owner, repo=repo_name, issue=issue, run_id=run_id, attempt_id=attempt_id,
            reason="completed", publish_comment_fn=publish_comment,
        )
        assert close_receipt["outcome"] == "closed", close_receipt
        assert close_receipt["source_state"] == "closed"
        assert close_receipt.get("verified") is True, close_receipt

        # -- 5. independent final re-query: issue truly closed, exactly one lifecycle comment --
        final_issue = _gh(["api", "repos/%s/%s/issues/%s" % (owner, repo_name, issue)])
        final_state = json.loads(final_issue.stdout)["state"]
        assert final_state == "closed", final_state
        final_comments = _lifecycle_comments(issue)
        assert len(final_comments) == 1, final_comments
        assert final_comments[0]["id"] == comment_id, (
            "close must update the SAME canonical comment, not create a new one")
        assert "CLOSED" in final_comments[0]["body"]

        print("MEASURED|live e2e: issue=%s closed for real, comment_id=%s shows CLOSED, "
              "no duplicate comment created across CLAIMED->IN_PROGRESS->VERIFYING->CLOSED"
              % (issue, comment_id))
    finally:
        # Idempotent no-op if step 4 already closed it; a safety net if an earlier assertion
        # raised before the real close happened.
        _gh(["issue", "close", issue, "--repo", LIVE_REPO,
            "--comment", "Live e2e scratch issue for #285 -- cleaned up automatically."],
           check=False)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_github_lifecycle_live_e2e")
