"""Deterministic, offline unit coverage for ``simplicio_loop.merge_executor.MergeExecutor``.

Uses a scripted fake ``runner`` (no network, no real `gh`) to prove: idempotent PR creation,
mergeable-state polling (success / conflict / timeout), a full merge + remote reconciliation
happy path, a merge command that fails, and a merge command that exits 0 but the remote
re-query disagrees (the "don't trust the exit code" gap #288 calls out).

See ``tests/test_merge_executor_live_e2e.py`` for the real, non-mocked `gh`-backed e2e against
disposable scratch branches.
"""
import json
import os
import subprocess
import sys

from simplicio_loop.merge_executor import MergeExecutor, MergeExecutorError


class ScriptedRunner:
    """Replays canned ``subprocess.CompletedProcess`` results for successive ``gh`` calls,
    recording every invocation so tests can assert on exactly what was run."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if not self._responses:
            raise AssertionError("ScriptedRunner ran out of scripted responses for %r" % argv)
        returncode, stdout, stderr = self._responses.pop(0)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def _pr_view_json(**fields):
    return json.dumps(fields)


def test_ensure_pr_creates_new_when_none_exists():
    runner = ScriptedRunner([
        (0, "[]", ""),  # pr list --head branch -> none
        (0, "https://github.com/o/r/pull/42\n", ""),  # pr create
    ])
    ex = MergeExecutor(repo="o/r", runner=runner)
    pr = ex.ensure_pr(branch="feat/x", base="main", title="t", body="b")
    assert pr["number"] == 42
    assert pr["state"] == "OPEN"
    assert any(call[:2] == ["gh", "pr"] and "create" in call for call in runner.calls)


def test_ensure_pr_is_idempotent_when_open_pr_exists():
    runner = ScriptedRunner([
        (0, json.dumps([{"number": 7, "url": "https://github.com/o/r/pull/7", "state": "OPEN",
                         "mergeable": "UNKNOWN", "mergeStateStatus": ""}]), ""),
    ])
    ex = MergeExecutor(repo="o/r", runner=runner)
    pr = ex.ensure_pr(branch="feat/x", base="main", title="t", body="b")
    assert pr["number"] == 7
    # Only the `pr list` lookup ran -- no second `pr create` for an already-open PR.
    assert len(runner.calls) == 1


def test_poll_mergeable_returns_as_soon_as_clean():
    runner = ScriptedRunner([
        (0, _pr_view_json(state="OPEN", mergeable="UNKNOWN", mergeStateStatus="UNKNOWN"), ""),
        (0, _pr_view_json(state="OPEN", mergeable="MERGEABLE", mergeStateStatus="CLEAN"), ""),
    ])
    ticks = {"n": 0}

    def fake_sleep(_seconds):
        ticks["n"] += 1

    ex = MergeExecutor(repo="o/r", runner=runner)
    result = ex.poll_mergeable(42, poll_interval=0.01, timeout=5.0, sleep=fake_sleep)
    assert result["mergeable"] == "MERGEABLE"
    assert ticks["n"] == 1  # slept exactly once, between the two polls


def test_poll_mergeable_returns_immediately_on_conflict():
    runner = ScriptedRunner([
        (0, _pr_view_json(state="OPEN", mergeable="CONFLICTING", mergeStateStatus="DIRTY"), ""),
    ])
    ex = MergeExecutor(repo="o/r", runner=runner)
    result = ex.poll_mergeable(42, sleep=lambda s: None)
    assert result["mergeable"] == "CONFLICTING"


def test_poll_mergeable_gives_up_at_timeout():
    # Clock advances by 10s per read regardless of polling; deadline (timeout=5) is exceeded
    # after the first check, so it must return the last-seen (still UNKNOWN) state.
    clock_state = {"t": 0.0}

    def fake_clock():
        clock_state["t"] += 10.0
        return clock_state["t"]

    runner = ScriptedRunner([
        (0, _pr_view_json(state="OPEN", mergeable="UNKNOWN", mergeStateStatus="UNKNOWN"), ""),
    ])
    ex = MergeExecutor(repo="o/r", runner=runner)
    result = ex.poll_mergeable(42, timeout=5.0, sleep=lambda s: None, clock=fake_clock)
    assert result["mergeable"] == "UNKNOWN"
    assert len(runner.calls) == 1  # gave up after the single scripted check


def test_merge_happy_path_reconciles_true():
    runner = ScriptedRunner([
        (0, _pr_view_json(state="OPEN", mergeable="MERGEABLE", mergeStateStatus="CLEAN"), ""),  # poll
        (0, "", ""),  # pr merge
        (0, _pr_view_json(state="MERGED", mergeCommit={"oid": "abc123"}, baseRefName="main"), ""),  # reconcile
        (0, "[]", ""),  # post-merge patrol: no remaining open PRs
    ])
    ex = MergeExecutor(repo="o/r", runner=runner)
    result = ex.merge(42, sleep=lambda s: None)
    assert result.merged is True
    assert result.reconciled is True
    assert result.reason_code == "OK"
    assert result.merge_commit_sha == "abc123"
    assert result.base_ref == "main"
    assert result.post_merge_patrol["reason"] == "post_merge"
    assert result.post_merge_patrol["action_required"] == []
    merge_calls = [c for c in runner.calls if "merge" in c]
    assert merge_calls and "--squash" in merge_calls[0] and "--delete-branch" in merge_calls[0]


def test_merge_refuses_when_conflicting():
    runner = ScriptedRunner([
        (0, _pr_view_json(state="OPEN", mergeable="CONFLICTING", mergeStateStatus="DIRTY"), ""),
    ])
    ex = MergeExecutor(repo="o/r", runner=runner)
    result = ex.merge(42, sleep=lambda s: None)
    assert result.merged is False
    assert result.reason_code == "CONFLICTING"
    # No merge command was attempted against a conflicting PR.
    assert not any("merge" in c and "view" not in c for c in runner.calls[1:])


def test_merge_command_failure_reported_not_raised():
    runner = ScriptedRunner([
        (0, _pr_view_json(state="OPEN", mergeable="MERGEABLE", mergeStateStatus="CLEAN"), ""),
        (1, "", "GraphQL: Pull request is not mergeable"),
    ])
    ex = MergeExecutor(repo="o/r", runner=runner)
    result = ex.merge(42, sleep=lambda s: None)
    assert result.merged is False
    assert result.reason_code == "MERGE_COMMAND_FAILED"
    assert "not mergeable" in result.detail


def test_merge_command_exits_zero_but_reconcile_disagrees():
    """The gap #288 names explicitly: a command exiting 0 is not proof of the remote state.
    Here `gh pr merge` reports success but the re-query still shows the PR OPEN (e.g. a
    branch-protection webhook silently reverted it) -- must NOT be reported as merged."""
    runner = ScriptedRunner([
        (0, _pr_view_json(state="OPEN", mergeable="MERGEABLE", mergeStateStatus="CLEAN"), ""),
        (0, "", ""),  # pr merge claims success
        (0, _pr_view_json(state="OPEN", mergeCommit=None, baseRefName="main"), ""),  # but still OPEN
    ])
    ex = MergeExecutor(repo="o/r", runner=runner)
    result = ex.merge(42, sleep=lambda s: None)
    assert result.merged is False
    assert result.reason_code == "RECONCILE_MISMATCH"


def test_post_merge_patrol_records_conflicted_sibling_without_undoing_merge():
    runner = ScriptedRunner([
        (0, _pr_view_json(state="OPEN", mergeable="MERGEABLE", mergeStateStatus="CLEAN"), ""),
        (0, "", ""),
        (0, _pr_view_json(state="MERGED", mergeCommit={"oid": "abc123"}, baseRefName="main"), ""),
        (0, json.dumps([{
            "number": 9, "url": "https://github.com/o/r/pull/9", "headRefName": "feat/other",
            "baseRefName": "main", "isDraft": False, "mergeable": "CONFLICTING",
            "mergeStateStatus": "DIRTY", "reviewDecision": "", "statusCheckRollup": [],
        }]), ""),
    ])
    result = MergeExecutor(repo="o/r", runner=runner).merge(42, sleep=lambda _s: None)
    assert result.merged is True
    assert result.post_merge_patrol["action_required"][0]["number"] == 9
    assert "CONFLICTING" in result.post_merge_patrol["action_required"][0]["signals"]


def test_post_merge_patrol_failure_is_explicitly_unverified():
    runner = ScriptedRunner([
        (0, _pr_view_json(state="OPEN", mergeable="MERGEABLE", mergeStateStatus="CLEAN"), ""),
        (0, "", ""),
        (0, _pr_view_json(state="MERGED", mergeCommit={"oid": "abc123"}, baseRefName="main"), ""),
        (1, "", "gh: authentication required"),
    ])
    result = MergeExecutor(repo="o/r", runner=runner).merge(42, sleep=lambda _s: None)
    assert result.merged is True
    assert result.post_merge_patrol["status"] == "unverified"
    assert result.post_merge_patrol["reason_code"] == "POST_MERGE_PATROL_FAILED"


def test_find_existing_pr_swallows_list_failure_returns_none():
    # `pr list` uses check=False internally -- a transport failure there is treated as "no
    # existing PR found" rather than raised, since ensure_pr's next step (pr create) will
    # surface any real auth/network problem loudly instead.
    runner = ScriptedRunner([(1, "", "gh: authentication required")])
    ex = MergeExecutor(repo="o/r", runner=runner)
    assert ex.find_existing_pr("feat/x") is None


def test_gh_transport_failure_on_create_raises_merge_executor_error():
    runner = ScriptedRunner([
        (0, "[]", ""),  # pr list -> none existing
        (1, "", "gh: authentication required"),  # pr create fails hard
    ])
    ex = MergeExecutor(repo="o/r", runner=runner)
    try:
        ex.ensure_pr(branch="feat/x", base="main", title="t", body="b")
        raise AssertionError("expected MergeExecutorError")
    except MergeExecutorError as exc:
        assert exc.reason_code == "GH_CLI_FAILED"



def test_ensure_pr_converts_sanitize_runtime_error_to_merge_executor_error():
    """When sanitize raises RuntimeError (closing word survived), convert it to MergeExecutorError."""
    import unittest.mock as mock
    import simplicio_loop.merge_executor as me_module
    
    runner = ScriptedRunner([
        (0, "[]", ""),  # pr list -> none existing
    ])
    ex = MergeExecutor(repo="o/r", runner=runner)
    
    # Monkeypatch sanitize to raise RuntimeError
    original_sanitize = me_module.sanitize
    def failing_sanitize(text, what):
        raise RuntimeError(f"{what} still has a GitHub closing word after rewrite: refusing to publish")
    
    me_module.sanitize = failing_sanitize
    try:
        try:
            ex.ensure_pr(branch="feat/x", base="main", title="Fixes #5", body="Closes #6")
            raise AssertionError("expected MergeExecutorError")
        except MergeExecutorError as exc:
            assert exc.reason_code == "CLOSING_WORD_REFUSED", f"got {exc.reason_code}"
            assert "PR title" in str(exc) or "PR body" in str(exc)
        except RuntimeError as e:
            raise AssertionError(f"should convert RuntimeError to MergeExecutorError, got: {e}")
    finally:
        me_module.sanitize = original_sanitize

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_merge_executor")
