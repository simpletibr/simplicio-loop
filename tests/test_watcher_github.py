"""Tests for simplicio_loop.watcher_github (#1470, #1471).

The real github_lifecycle, pr_patrol and scripts.pr_evidence code runs. Only the `gh`
subprocess boundary is faked: FakeGh keeps issues, comments and PRs in memory, records every
argv and refuses every PR write.
"""
import asyncio
import json
import re
import subprocess

import pytest

from simplicio_loop.github_lifecycle import LIFECYCLE_COMMENT_MARKER, GitHubTransportError
from simplicio_loop.watcher_github import (
    ClaimReceipt,
    FixTask,
    claim_on_github,
    patrol_open_prs,
    post_status,
)

REPO = "acme/widgets"
PR_WRITE_SUBCOMMANDS = {"close", "merge", "edit", "ready", "reopen", "review", "comment"}


class FakeGh:
    """In-memory `gh`: the injected runner for every primitive under test."""

    def __init__(self, prs=(), pr_views=None, pr_inline=None):
        self.calls = []
        self.comments = {}  # issue number -> [comment dict]
        self.next_id = 1001
        self.prs = list(prs)
        self.pr_views = pr_views or {}
        self.pr_inline = pr_inline or {}
        self.pr_writes = []  # attempted PR writes (each one also raises)
        self.api_writes = []  # (method, path) of every non-GET api call
        self.fail = False

    def issue_comments(self, issue):
        return self.comments.setdefault(int(issue), [])

    def marker_comments(self, issue):
        return [c for c in self.issue_comments(issue) if LIFECYCLE_COMMENT_MARKER in c["body"]]

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        assert argv[0] == "gh", argv
        if argv[1] == "pr":
            return self._pr(argv)
        assert argv[1] == "api", argv
        return self._api(argv, kwargs.get("input"))

    @staticmethod
    def _ok(argv, payload):
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    def _pr(self, argv):
        sub = argv[2]
        if sub in PR_WRITE_SUBCOMMANDS:
            self.pr_writes.append(list(argv))
            raise RuntimeError("PR write blocked: %s" % " ".join(argv))
        if sub == "list":
            return self._ok(argv, self.prs)
        if sub == "view":
            return self._ok(argv, self.pr_views[int(argv[3])])
        raise AssertionError("unexpected gh call: %r" % (argv,))

    def _api(self, argv, payload):
        args = argv[2:]
        method = args[args.index("-X") + 1] if "-X" in args else "GET"
        path = next(a for a in args if a.startswith("repos/"))
        route, _, query = path.partition("?")
        if self.fail:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        if method != "GET":
            self.api_writes.append((method, path))
            if "/pulls/" in route:
                self.pr_writes.append(list(argv))
                raise RuntimeError("PR write blocked: %s" % " ".join(argv))
        found = re.fullmatch(r"repos/[^/]+/[^/]+/issues/(\d+)/comments", route)
        if found:
            comments = self.issue_comments(found.group(1))
            if method == "POST":
                comment = {"id": self.next_id, "body": json.loads(payload)["body"]}
                self.next_id += 1
                comments.append(comment)
                return self._ok(argv, comment)
            if "page=" in query and "page=1" not in query:
                return self._ok(argv, [])
            return self._ok(argv, comments)
        found = re.fullmatch(r"repos/[^/]+/[^/]+/issues/comments/(\d+)", route)
        if found:
            wanted = int(found.group(1))
            comment = next(c for cs in self.comments.values() for c in cs if c["id"] == wanted)
            if method == "PATCH":
                comment["body"] = json.loads(payload)["body"]
            return self._ok(argv, comment)
        found = re.fullmatch(r"repos/[^/]+/[^/]+/issues/(\d+)", route)
        if found:
            return self._ok(argv, {
                "number": int(found.group(1)), "title": "an issue", "body": "body", "state": "open",
                "html_url": "https://github.com/%s/issues/%s" % (REPO, found.group(1)),
                "labels": [], "assignees": [], "user": {"login": "author"},
                "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z",
            })
        found = re.fullmatch(r"repos/[^/]+/[^/]+/pulls/(\d+)/comments", route)
        if found:
            return self._ok(argv, self.pr_inline.get(int(found.group(1)), []))
        raise AssertionError("unexpected gh call: %r" % (argv,))


def run(coro):
    return asyncio.run(coro)


def status(gh, **kwargs):
    kwargs.setdefault("issue", "42")
    return run(post_status(repo=REPO, runner=gh, **kwargs))


def claim(gh, owner, issue="42"):
    return run(claim_on_github(repo=REPO, issue=issue, owner=owner, runner=gh))


def pr_row(number, head, *, mergeable="MERGEABLE", merge_state="BLOCKED", review="", checks=()):
    """One row shaped like `gh pr list --json number,url,headRefName,...` output."""
    return {
        "number": number, "url": "https://github.com/%s/pull/%s" % (REPO, number),
        "headRefName": head, "baseRefName": "main", "isDraft": False, "mergeable": mergeable,
        "mergeStateStatus": merge_state, "reviewDecision": review, "statusCheckRollup": list(checks),
    }


def check(name, conclusion):
    return {"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": conclusion,
            "detailsUrl": "https://github.com/%s/actions/runs/1" % REPO}


def patrol_gh():
    return FakeGh(
        prs=[
            pr_row(10, "loop/issue-1470", review="CHANGES_REQUESTED"),
            pr_row(11, "loop/issue-1471", merge_state="UNSTABLE",
                   checks=[check("unit", "FAILURE"), check("lint", "SUCCESS")]),
            pr_row(12, "loop/issue-9", mergeable="CONFLICTING", merge_state="DIRTY"),
            pr_row(13, "loop/issue-5", merge_state="CLEAN", review="APPROVED",
                   checks=[check("unit", "SUCCESS")]),
            pr_row(14, "hotfix/typo", review="CHANGES_REQUESTED"),
        ],
        pr_views={
            10: {"reviews": [
                    {"author": {"login": "alice"}, "state": "CHANGES_REQUESTED",
                     "body": "Handle the empty list case"},
                    {"author": {"login": "bob"}, "state": "APPROVED", "body": ""}],
                 "files": [{"path": "simplicio_loop/x.py"}, {"path": "tests/test_x.py"}],
                 "statusCheckRollup": []},
            11: {"reviews": [], "files": [{"path": "simplicio_loop/y.py"}],
                 "statusCheckRollup": [check("unit", "FAILURE"), check("lint", "SUCCESS")]},
            12: {"reviews": [], "files": [{"path": "simplicio_loop/z.py"}], "statusCheckRollup": []},
            14: {"reviews": [{"author": {"login": "carol"}, "state": "CHANGES_REQUESTED", "body": "typo"}],
                 "files": [{"path": "README.md"}], "statusCheckRollup": []},
        },
        pr_inline={10: [{"path": "simplicio_loop/x.py", "line": 42, "body": "This raises on []"}]},
    )


def patrol(gh, **kwargs):
    return run(patrol_open_prs(repo=REPO, runner=gh, **kwargs))


def task_for(tasks, pr, kind):
    return next(t for t in tasks if t.pr == pr and t.kind == kind)


def test_second_post_status_updates_the_same_comment_in_place():
    gh = FakeGh()
    first = status(gh, state="CLAIMED", agent_id="session-a")
    assert first["verified"] and first["action"] == "created"
    assert len(gh.issue_comments(42)) == 1 and len(gh.marker_comments(42)) == 1
    assert "| Estado | CLAIMED |" in gh.marker_comments(42)[0]["body"]

    second = status(gh, state="PLANNED", detail="plan ready")
    assert second["verified"] and second["action"] == "updated"
    assert second["comment_id"] == first["comment_id"]
    assert len(gh.issue_comments(42)) == 1
    body = gh.marker_comments(42)[0]["body"]
    assert "| Estado | PLANNED |" in body and "plan ready" in body
    assert "| Agente | session-a |" in body  # owner survives an update that omits agent_id
    assert [w[0] for w in gh.api_writes] == ["POST", "PATCH"]


def test_invalid_transition_is_rejected_with_reason_code():
    gh = FakeGh()
    status(gh, state="CLAIMED", agent_id="session-a")
    writes_before = list(gh.api_writes)

    refused = status(gh, state="MERGED")
    assert refused["verified"] is False and refused["outcome"] == "blocked"
    assert refused["reason_code"] == "transition_invalid"
    assert refused["previous_state"] == "CLAIMED" and "CLAIMED -> MERGED" in refused["reason"]
    assert gh.api_writes == writes_before  # nothing was written
    assert "| Estado | CLAIMED |" in gh.marker_comments(42)[0]["body"]

    # an explicit regression reason code is the only way back
    status(gh, state="PLANNED")
    status(gh, state="IN_PROGRESS")
    assert status(gh, state="CLAIMED")["reason_code"] == "transition_invalid"
    assert status(gh, state="CLAIMED", reason_code="LEASE_REASSIGNED")["verified"] is True


def test_transport_failure_propagates_instead_of_reading_as_discovered():
    gh = FakeGh()
    gh.fail = True
    with pytest.raises(GitHubTransportError):
        status(gh, state="CLAIMED", agent_id="session-a")
    assert gh.api_writes == []


def test_claim_is_visible_on_the_issue_and_a_second_owner_skips():
    gh = FakeGh()
    mine = claim(gh, "session-a")
    assert isinstance(mine, ClaimReceipt)
    assert (mine.verified, mine.claimed_by, mine.state, mine.reason) == (True, "session-a", "CLAIMED", "claimed")
    body = gh.marker_comments(42)[0]["body"]
    assert "| Estado | CLAIMED |" in body and "| Agente | session-a |" in body
    writes_after_claim = list(gh.api_writes)

    other = claim(gh, "session-b")
    assert (other.verified, other.claimed_by, other.reason) == (False, "session-a", "claimed_by_other")
    again = claim(gh, "session-a")
    assert (again.verified, again.reason) == (True, "already_claimed")
    assert gh.api_writes == writes_after_claim  # the skip and the repeat wrote nothing
    assert len(gh.issue_comments(42)) == 1
    assert "| Agente | session-a |" in gh.marker_comments(42)[0]["body"]


def test_requested_changes_become_a_review_comment_task():
    gh = patrol_gh()
    task = task_for(patrol(gh), 10, "review_comment")
    assert isinstance(task, FixTask)
    assert "alice: Handle the empty list case" in task.text
    assert "simplicio_loop/x.py:42 This raises on []" in task.text
    assert "bob" not in task.text  # an approving review is not feedback to fix
    assert task.files == ["simplicio_loop/x.py"]
    assert any(call[1:3] == ["pr", "list"] for call in gh.calls)  # final=True opened the cadence gate


def test_failing_check_becomes_a_checks_failed_task():
    task = task_for(patrol(patrol_gh()), 11, "checks_failed")
    assert "unit" in task.text and "lint" not in task.text
    assert task.files == ["simplicio_loop/y.py"]


def test_conflicting_pr_becomes_a_conflict_task():
    task = task_for(patrol(patrol_gh()), 12, "conflict")
    assert "conflicts with main" in task.text and "merge the base" in task.text
    assert task.files == ["simplicio_loop/z.py"]


def test_patrol_skips_clean_and_non_loop_prs():
    tasks = patrol(patrol_gh())
    assert sorted((t.pr, t.kind) for t in tasks) == [
        (10, "review_comment"), (11, "checks_failed"), (12, "conflict")]
    assert {t.pr for t in patrol(patrol_gh(), branch_filter="")} == {10, 11, 12, 14}


def test_fake_gh_blocks_and_records_pr_writes():
    gh = FakeGh()
    for sub in ("close", "merge", "edit"):
        with pytest.raises(RuntimeError):
            gh(["gh", "pr", sub, "10"])
    assert len(gh.pr_writes) == 3


def test_watcher_makes_zero_pr_write_calls():
    gh = patrol_gh()
    patrol(gh)
    status(gh, state="CLAIMED", agent_id="session-a")
    status(gh, state="PLANNED")
    claim(gh, "session-b", issue="43")
    assert gh.pr_writes == []
    assert all(call[1] == "api" or call[1:3] in (["pr", "list"], ["pr", "view"]) for call in gh.calls)
    # the patrol alone is pure reads: no api write of any kind
    reader = patrol_gh()
    patrol(reader)
    assert reader.api_writes == [] and reader.pr_writes == []


def test_fix_tasks_do_not_share_a_files_list():
    first, second = FixTask(1, "conflict", "a"), FixTask(2, "conflict", "b")
    first.files.append("x.py")
    assert second.files == []
