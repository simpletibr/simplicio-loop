"""Real, non-mocked e2e for ``simplicio_loop.merge_executor.MergeExecutor`` against the
actual GitHub API via the real `gh` CLI -- proves the merge executor genuinely creates a PR,
waits for GitHub to compute mergeability, merges it, and that its remote-target reconciliation
step is telling the truth (a live re-query, not an assumption from the merge command's exit
code).

This deliberately never touches `main`: it creates a disposable *scratch base branch* (its own
throwaway integration target, pushed straight from `main`'s current tip) and a *scratch feature
branch* off of it, opens a real PR of feature -> scratch-base, merges it for real with
`MergeExecutor.merge()`, and then deletes BOTH scratch branches -- so cleanup is unconditional
(try/finally) and complete: nothing lands on `main`, and no branch is left behind either
merged or not.

Gate: only runs when SIMPLICIO_LIVE_GH_E2E=1 is set AND `gh` is authenticated (same convention
as tests/test_progress_comment_live_e2e.py). Skipped everywhere else -- never touches the
network unless explicitly opted into.
"""
import os
import shutil
import subprocess
import sys
import uuid

import pytest

pytestmark = pytest.mark.external_integration

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from simplicio_loop.merge_executor import MergeExecutor  # noqa: E402

LIVE_REPO = os.environ.get("SIMPLICIO_LIVE_GH_REPO", "simpletibr/simplicio-loop")


def _live_gate_open():
    if os.environ.get("SIMPLICIO_LIVE_GH_E2E") != "1":
        return False
    if not shutil.which("gh") or not shutil.which("git"):
        return False
    r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    return r.returncode == 0


def _git(args, check=True, cwd=REPO_ROOT):
    r = subprocess.run(["git"] + args, capture_output=True, text=True, cwd=cwd)
    if check and r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), r.stderr or r.stdout))
    return r


def test_merge_executor_creates_and_merges_a_real_pr_on_scratch_branches():
    if not _live_gate_open():
        pytest.skip(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[live_github_opt_in]: set "
            "SIMPLICIO_LIVE_GH_E2E=1 with an authenticated gh CLI to run this "
            "live e2e against %s" % LIVE_REPO
        )

    token = uuid.uuid4().hex[:10]
    base_branch = "scratch/merge-executor-e2e-base-%s" % token
    feature_branch = "scratch/merge-executor-e2e-feature-%s" % token
    starting_branch = _git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    pr_number = None

    try:
        _git(["fetch", "origin", "main"])
        # Scratch base branch: a disposable integration target, never `main` itself, so the
        # real merge this test performs cannot land anything on `main`.
        _git(["branch", base_branch, "origin/main"])
        _git(["push", "origin", "%s:%s" % (base_branch, base_branch)])

        _git(["branch", feature_branch, base_branch])
        _git(["checkout", feature_branch])
        scratch_file = os.path.join(REPO_ROOT, "tests", "_scratch",
                                    "merge_executor_e2e_%s.txt" % token)
        os.makedirs(os.path.dirname(scratch_file), exist_ok=True)
        with open(scratch_file, "w", encoding="utf-8") as fh:
            fh.write("scratch file for merge_executor live e2e (%s) -- safe to ignore\n" % token)
        _git(["add", scratch_file])
        _git(["commit", "-m", "test(merge-executor): scratch commit for live e2e (%s)" % token])
        _git(["push", "origin", "%s:%s" % (feature_branch, feature_branch)])

        executor = MergeExecutor(repo=LIVE_REPO, runner=subprocess.run)
        pr = executor.ensure_pr(
            branch=feature_branch, base=base_branch,
            title="[test-scratch] merge_executor live e2e (%s)" % token,
            body="Auto-created by tests/test_merge_executor_live_e2e.py against a disposable "
                 "scratch base branch (never `main`). Both branches are deleted at test end.",
        )
        assert pr["number"], "ensure_pr did not return a PR number: %r" % pr
        pr_number = pr["number"]

        # Idempotency: calling ensure_pr again must return the SAME PR, not open a second one.
        pr_again = executor.ensure_pr(branch=feature_branch, base=base_branch, title="x", body="x")
        assert pr_again["number"] == pr_number

        result = executor.merge(pr_number, poll_interval=2.0, mergeable_timeout=60.0)
        assert result.merged is True, "merge did not succeed: %r" % (result.to_dict(),)
        assert result.reconciled is True
        assert result.merge_commit_sha, "no merge commit sha reported"
        assert result.base_ref == base_branch

        # Remote-target reconciliation, proven independently of the executor's own reconcile()
        # call: re-query the PR fresh and confirm the base branch tip really is (or descends
        # from) the reported merge commit.
        reconfirm = executor.reconcile(pr_number)
        assert reconfirm["merged"] is True
        assert reconfirm["merge_commit_sha"] == result.merge_commit_sha

        _git(["fetch", "origin", base_branch])
        merge_base = _git(["merge-base", "--is-ancestor", result.merge_commit_sha,
                           "origin/%s" % base_branch], check=False)
        assert merge_base.returncode == 0, (
            "merge commit %s is not an ancestor of origin/%s -- remote state does not match "
            "the reconciled claim" % (result.merge_commit_sha, base_branch))

        print("MEASURED|merge_executor live e2e: pr=#%d merge_commit=%s base=%s -> merged and "
             "reconciled against the real GitHub API" % (pr_number, result.merge_commit_sha, base_branch))
    finally:
        _git(["checkout", starting_branch], check=False)
        for b in (feature_branch, base_branch):
            _git(["branch", "-D", b], check=False)
            _git(["push", "origin", "--delete", b], check=False)
        # gh pr merge --delete-branch already removed the feature branch remotely on success;
        # the second delete above is a harmless no-op in that case (best-effort cleanup either
        # way -- deletion of an already-gone ref is not an error worth failing the test over).


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_merge_executor_live_e2e")
