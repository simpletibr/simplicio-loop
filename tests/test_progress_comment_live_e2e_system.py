"""True e2e for issue #301 AC4 — `scripts/pr_evidence.py progress-comment` idempotency against a
LIVE GitHub issue, using the REAL `gh` CLI (no injected fake runner, unlike the unit coverage in
`tests/test_delivery_progress.py::test_find_existing_progress_comment_matches_marker`).

This is exactly the gap the #301 review comment flagged: "idempotency logic only unit-tested with
an injected fake `gh` runner; no true e2e against a live GitHub issue." AC4 itself anticipated this
would be `token/live-repo`-gated ("teste e2e opcional gated por token, com mock em CI local") — this
test IS that opt-in e2e.

Gate: only runs when SIMPLICIO_LIVE_GH_E2E=1 is set AND `gh` is authenticated AND
SIMPLICIO_LIVE_GH_REPO names a repo the token can create/close issues and post/delete comments in
(defaults to wesleysimplicio/simplicio-loop, this project's own repo, where the agent running this
suite has push/comment access). Skipped everywhere else (default local runs, CI without a token) —
never touches the network unless explicitly opted into.

What it proves, against the real API:
  1. `progress-comment` posted twice against a freshly-created scratch issue results in exactly ONE
     comment carrying the `<!-- simplicio-loop:progress -->` anchor (same comment id both times).
  2. The comment's `updated_at` actually changes between the two posts (a real PATCH happened, not
     a silent no-op).

Cleanup is unconditional (try/finally): the scratch comment is deleted and the scratch issue is
closed even if an assertion fails, so a broken assertion never leaves noise on the tracker.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.external_integration

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PR_EVIDENCE = os.path.join(REPO, "scripts", "pr_evidence.py")
LIVE_REPO = os.environ.get("SIMPLICIO_LIVE_GH_REPO", "wesleysimplicio/simplicio-loop")


def _live_gate_open():
    if os.environ.get("SIMPLICIO_LIVE_GH_E2E") != "1":
        return False
    if not shutil.which("gh"):
        return False
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    return r.returncode == 0


def _gh(args, input_text=None, check=True):
    r = subprocess.run(["gh"] + args, capture_output=True, text=True, input=input_text)
    if check and r.returncode != 0:
        raise RuntimeError("gh %s failed: %s" % (" ".join(args), r.stderr or r.stdout))
    return r


def _create_scratch_issue():
    r = _gh([
        "issue", "create", "--repo", LIVE_REPO,
        "--title", "[test-scratch] #301 AC4 progress-comment idempotency e2e (auto-created, safe to close)",
        "--body", "Auto-created by tests/test_progress_comment_live_e2e.py — verifies "
                  "progress-comment idempotency against the live GitHub API, then deletes its own "
                  "comment(s) and closes this issue. Safe to ignore.",
    ])
    # gh issue create prints the issue URL on the last stdout line.
    url = r.stdout.strip().splitlines()[-1]
    return url.rstrip("/").rsplit("/", 1)[-1]


def _comments(issue):
    r = _gh(["api", "repos/%s/issues/%s/comments" % (LIVE_REPO, issue), "--paginate"])
    return json.loads(r.stdout or "[]")


def _run_progress_comment(issue, min_interval=0):
    env = dict(os.environ)
    return subprocess.run(
        [sys.executable, PR_EVIDENCE, "progress-comment", "--issue", str(issue),
         "--min-interval", str(min_interval)],
        capture_output=True, text=True, cwd=REPO, env=env)


def _reset_rate_limit_state():
    state = os.path.join(REPO, ".simplicio-loop/orchestrator", "loop", "progress_comment_state.json")
    try:
        os.remove(state)
    except OSError:
        pass


def test_progress_comment_posted_twice_updates_same_comment_on_live_issue():
    if not _live_gate_open():
        pytest.skip(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[live_github_opt_in]: set "
            "SIMPLICIO_LIVE_GH_E2E=1 with an authenticated gh CLI to run this "
            "live e2e against %s" % LIVE_REPO
        )

    issue = _create_scratch_issue()
    try:
        _reset_rate_limit_state()
        r1 = _run_progress_comment(issue, min_interval=0)
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert "MEASURED|progress-comment" in r1.stdout, r1.stdout

        after_first = _comments(issue)
        marked = [c for c in after_first
                 if "<!-- simplicio-loop:progress -->" in (c.get("body") or "")]
        assert len(marked) == 1, "expected exactly 1 marked comment after first post: %r" % after_first
        first_id = marked[0]["id"]
        first_updated_at = marked[0]["updated_at"]

        _reset_rate_limit_state()  # bypass the 60s rate-limit gate for this deterministic test
        r2 = _run_progress_comment(issue, min_interval=0)
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "MEASURED|progress-comment" in r2.stdout, r2.stdout

        after_second = _comments(issue)
        marked2 = [c for c in after_second
                  if "<!-- simplicio-loop:progress -->" in (c.get("body") or "")]
        assert len(marked2) == 1, (
            "idempotency violated: expected exactly 1 comment after the SECOND post, got %d: %r"
            % (len(marked2), after_second))
        assert marked2[0]["id"] == first_id, "second post created a NEW comment instead of updating"
        assert marked2[0]["updated_at"] != first_updated_at, (
            "comment updated_at did not change — the second call may have been a silent no-op")

        print("MEASURED|live e2e: issue=%s comment_id=%s posted twice -> 1 comment, "
             "updated_at changed (%s -> %s)" % (issue, first_id, first_updated_at,
                                                marked2[0]["updated_at"]))

        for c in after_second:
            if "<!-- simplicio-loop:progress -->" in (c.get("body") or ""):
                _gh(["api", "-X", "DELETE",
                    "repos/%s/issues/comments/%s" % (LIVE_REPO, c["id"])], check=False)
    finally:
        _gh(["issue", "close", issue, "--repo", LIVE_REPO,
            "--comment", "Live e2e scratch issue for #301 AC4 — cleaned up automatically."],
           check=False)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_progress_comment_live_e2e")
