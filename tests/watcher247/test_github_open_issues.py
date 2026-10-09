"""Tests for github.open_issues() using REST API (gh 2.46 fix).

Problema (#1589, B2): `gh issue list --json` fails with "Unknown JSON field: authorAssociation"
on gh 2.46.0 (Ubuntu). Solution: use `gh api repos/{ORG}/{repo}/issues` instead.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from simplicio_loop.watcher247 import config, github, state


def test_open_issues_uses_rest_api_not_issue_list(monkeypatch):
    """Verify gh_json is called with 'api' endpoint, not 'issue list'."""
    calls = []

    async def fake_gh_json(args, timeout=60):
        calls.append(args)
        # Simulate REST API response with a PR that should be discarded
        return [
            {
                "number": 1,
                "title": "Fix thing",
                "body": "Fix description",
                "created_at": "2026-10-01T00:00:00Z",
                "labels": [{"name": "loop:auto"}],
                "user": {"login": "owner"},
                "author_association": "OWNER",
                # PR row should be discarded
                "pull_request": {"url": "https://github.com/org/repo/pull/1"},
            },
            {
                "number": 2,
                "title": "Another issue",
                "body": "Another description",
                "created_at": "2026-10-01T00:00:00Z",
                "labels": [],
                "user": {"login": "contributor"},
                "author_association": "CONTRIBUTOR",
            },
        ]

    monkeypatch.setattr(github, "gh_json", fake_gh_json)

    result = asyncio.run(github.open_issues("test-repo"))

    # Verify the correct endpoint was called
    assert len(calls) == 1
    args = calls[0]
    assert args[0] == "api"
    assert "-X" in args
    assert "GET" in args
    repo_path = f"repos/{config.ORG}/test-repo/issues"
    assert repo_path in " ".join(args)
    assert "state=open" in " ".join(args)
    assert "authorAssociation" not in " ".join(args)  # Old field should not be requested
    assert "--paginate" in args and "per_page=100" in args  # PRs share the pages with issues: read them all

    # Verify PR is discarded
    assert len(result) == 1
    assert result[0]["number"] == 2
    assert "pull_request" not in result[0]

    # Verify output shape is preserved (maintains contracts)
    assert result[0]["number"] == 2
    assert result[0]["title"] == "Another issue"
    assert result[0]["body"] == "Another description"
    assert result[0]["user"]["login"] == "contributor"
    assert result[0]["author_association"] == "CONTRIBUTOR"


def test_open_issues_handles_disabled_issues_error(monkeypatch):
    """Verify 'Issues are disabled' error marks repo and returns []."""
    mark_calls = []

    async def fake_gh_json(args, timeout=60):
        raise RuntimeError("Issues are disabled for this repository (HTTP 410)")

    async def fake_mark_issues_disabled(repo):
        mark_calls.append(repo)

    monkeypatch.setattr(github, "gh_json", fake_gh_json)
    monkeypatch.setattr(state, "mark_issues_disabled", fake_mark_issues_disabled)

    result = asyncio.run(github.open_issues("test-repo"))

    assert result == []
    assert mark_calls == ["test-repo"]


def test_open_issues_case_insensitive_disabled_check(monkeypatch):
    """Verify both 'Issues are disabled' and 'disabled issues' patterns are caught."""
    for error_msg in [
        "Issues are disabled for this repository",
        "Issues Are Disabled For This Repository",
    ]:
        mark_calls = []

        async def fake_gh_json(args, timeout=60):
            raise RuntimeError(error_msg)

        async def fake_mark_issues_disabled(repo):
            mark_calls.append(repo)

        monkeypatch.setattr(github, "gh_json", fake_gh_json)
        monkeypatch.setattr(state, "mark_issues_disabled", fake_mark_issues_disabled)

        result = asyncio.run(github.open_issues("test-repo"))

        assert result == [], f"Failed for error message: {error_msg}"
        assert len(mark_calls) == 1, f"Failed for error message: {error_msg}"


def test_open_issues_other_errors_propagate(monkeypatch):
    """Verify other RuntimeErrors are re-raised."""

    async def fake_gh_json(args, timeout=60):
        raise RuntimeError("Some other error")

    monkeypatch.setattr(github, "gh_json", fake_gh_json)

    with pytest.raises(RuntimeError, match="Some other error"):
        asyncio.run(github.open_issues("test-repo"))


def test_open_issues_preserves_output_contract(monkeypatch):
    """Verify the output maintains the contract expected by intake_gate."""

    async def fake_gh_json(args, timeout=60):
        return [
            {
                "number": 42,
                "title": "Test issue",
                "body": "Test body",
                "created_at": "2026-10-01T12:34:56Z",
                "labels": [{"name": "bug"}, {"name": "urgent"}],
                "user": {"login": "testuser"},
                "author_association": "OWNER",
            },
        ]

    monkeypatch.setattr(github, "gh_json", fake_gh_json)

    result = asyncio.run(github.open_issues("test-repo"))

    assert len(result) == 1
    issue = result[0]

    # Verify intake_gate contract
    assert issue["number"] == 42
    assert issue["title"] == "Test issue"
    assert issue["body"] == "Test body"
    assert issue["user"]["login"] == "testuser"
    assert issue["author_association"] == "OWNER"
    assert issue["labels"] == [{"name": "bug"}, {"name": "urgent"}]
    assert issue["created_at"] == "2026-10-01T12:34:56Z"


def _rest_pages(rows):
    """A `gh api repos/.../issues` stand-in that pages like GitHub: `per_page` (default 30), the first page only
    without --paginate, every page merged into one array with it. `served` counts the pages it handed out."""
    served = []

    async def run(argv, **_kwargs):
        size = next((int(a.split("=")[1]) for a in argv if a.startswith("per_page=")), 30)
        pages = [rows[i:i + size] for i in range(0, len(rows), size)]
        wanted = pages if "--paginate" in argv else pages[:1]
        served.extend(wanted)
        return github.proc.Result(0, json.dumps([row for page in wanted for row in page]))

    return run, served


def test_open_issues_reads_past_the_prs_that_share_the_pages(monkeypatch):
    """/issues mixes PRs and issues: 120 PRs ahead of 25 issues must not hide the issues, nor cost one request per item."""
    prs = [{"number": 1000 + n, "pull_request": {}, "labels": [], "user": {"login": "o"}} for n in range(120)]
    issues = [{"number": n, "labels": [{"name": "loop:auto"}], "user": {"login": "o"}, "author_association": "OWNER"}
              for n in range(1, 26)]
    run, served = _rest_pages(prs + issues)
    monkeypatch.setattr(github.proc, "run", run)

    found = asyncio.run(github.open_issues("test-repo"))

    assert [row["number"] for row in found] == list(range(1, 26))
    assert len(served) == 2  # 145 items at 100 per page; per_page=1 or the default 30 would take 145 or 5
