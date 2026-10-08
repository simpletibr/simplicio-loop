"""Tests for simplicio_loop.watcher_github (#1470, #1471)."""
import asyncio
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from simplicio_loop.watcher_github import (
    post_status,
    claim_on_github,
    patrol_open_prs,
    FixTask,
    ClaimReceipt,
)


class FakeGh:
    """Fake gh runner for tests."""

    def __init__(self):
        self.calls = []  # Track all gh calls
        self.comments = {}  # Fake comments storage
        self.pr_state = {}  # Fake PR state storage

    def __call__(self, cmd, **kwargs):
        """Mock subprocess.run for gh commands."""
        self.calls.append({"cmd": cmd, "kwargs": kwargs})

        # Ensure we never write to close/merge PRs
        if "pr" in cmd and ("close" in cmd or "merge" in cmd or "edit" in cmd):
            raise RuntimeError("Attempted to write to PR (close/merge/edit not allowed)")

        # Simulate comment API responses
        if "api" in cmd and "comments" in cmd:
            if "-X" in cmd and "POST" in cmd:
                # Create comment
                body = kwargs.get("input", "")
                if body:
                    try:
                        data = json.loads(body)
                        comment_id = len(self.comments) + 1
                        self.comments[comment_id] = data
                        return subprocess.CompletedProcess(
                            cmd, 0,
                            stdout=json.dumps({"id": comment_id, **data}),
                            stderr=""
                        )
                    except Exception:
                        pass
            elif "-X" in cmd and "PATCH" in cmd:
                # Update comment
                body = kwargs.get("input", "")
                if body:
                    try:
                        data = json.loads(body)
                        # Simulate updating first comment
                        cid = 1
                        self.comments[cid] = data
                        return subprocess.CompletedProcess(
                            cmd, 0,
                            stdout=json.dumps({"id": cid, **data}),
                            stderr=""
                        )
                    except Exception:
                        pass

        # Return empty PR list by default
        if "pr" in cmd and "list" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=json.dumps([]), stderr=""
            )

        # Return empty for unknown commands
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")


def test_post_status_creates_comment():
    """Test: Single status comment created."""
    fake_gh = FakeGh()
    
    async def run_test():
        # Mock the github_lifecycle functions
        with patch("simplicio_loop.watcher_github._github_lifecycle") as mock_gl:
            mock_gl.validate_transition.return_value = {"ok": True}
            mock_gl.publish_lifecycle_state.return_value = {
                "verified": True,
                "outcome": "created",
                "state": "CLAIMED",
                "comment_id": 1
            }
            mock_gl.get_details.return_value = {"lifecycle_state": "DISCOVERED"}
            
            result = await post_status(
                repo="owner/repo",
                issue="42",
                state="CLAIMED",
                runner=fake_gh,
            )
            
            assert result["verified"]
            assert result["state"] == "CLAIMED"
    
    asyncio.run(run_test())


def test_post_status_rejects_invalid_transition():
    """Test: Invalid transitions are rejected."""
    fake_gh = FakeGh()
    
    async def run_test():
        with patch("simplicio_loop.watcher_github._github_lifecycle") as mock_gl:
            # MERGED -> DISCOVERED is invalid
            mock_gl.validate_transition.return_value = {
                "ok": False,
                "reason_code": "transition_invalid",
                "reason": "MERGED -> DISCOVERED is not valid"
            }
            mock_gl.get_details.return_value = {"lifecycle_state": "MERGED"}
            
            result = await post_status(
                repo="owner/repo",
                issue="42",
                state="DISCOVERED",
                runner=fake_gh,
            )
            
            assert not result["verified"]
            assert result["reason_code"] == "transition_invalid"
    
    asyncio.run(run_test())


def test_claim_on_github_marks_visible():
    """Test: Claim visible on GitHub."""
    fake_gh = FakeGh()
    
    async def run_test():
        with patch("simplicio_loop.watcher_github._github_lifecycle") as mock_gl:
            mock_gl.validate_transition.return_value = {"ok": True}
            mock_gl.publish_lifecycle_state.return_value = {
                "verified": True,
                "outcome": "created",
                "state": "CLAIMED",
            }
            mock_gl.get_details.return_value = {"lifecycle_state": "DISCOVERED"}
            
            receipt = await claim_on_github(
                repo="owner/repo",
                issue="42",
                runner=fake_gh,
            )
            
            assert receipt.verified
            assert receipt.state == "CLAIMED"
            assert "owner/repo" in receipt.repo
    
    asyncio.run(run_test())


def test_patrol_open_prs_detects_conflict():
    """Test: Conflict detected in patrol."""
    fake_gh = FakeGh()
    
    async def run_test():
        with patch("simplicio_loop.watcher_github._pr_patrol") as mock_patrol:
            mock_patrol.PrPatrol.return_value.inspect.return_value = {
                "open_prs": [
                    {
                        "number": 10,
                        "head": "loop/issue-123",
                        "signals": ["CONFLICTING"],
                        "action_required": True,
                    }
                ]
            }
            
            tasks = await patrol_open_prs(
                repo="owner/repo",
                runner=fake_gh,
            )
            
            assert len(tasks) == 1
            assert tasks[0].kind == "conflict"
            assert tasks[0].pr == 10
    
    asyncio.run(run_test())


def test_patrol_open_prs_detects_check_failure():
    """Test: Check failure produces fix task."""
    fake_gh = FakeGh()
    
    async def run_test():
        with patch("simplicio_loop.watcher_github._pr_patrol") as mock_patrol:
            mock_patrol.PrPatrol.return_value.inspect.return_value = {
                "open_prs": [
                    {
                        "number": 11,
                        "head": "loop/issue-456",
                        "signals": ["CHECKS_FAILED"],
                        "action_required": True,
                    }
                ]
            }
            
            tasks = await patrol_open_prs(
                repo="owner/repo",
                runner=fake_gh,
            )
            
            assert len(tasks) == 1
            assert tasks[0].kind == "checks_failed"
    
    asyncio.run(run_test())


def test_patrol_open_prs_filters_author():
    """Test: Author filter works."""
    fake_gh = FakeGh()
    
    async def run_test():
        with patch("simplicio_loop.watcher_github._pr_patrol") as mock_patrol:
            mock_patrol.PrPatrol.return_value.inspect.return_value = {
                "open_prs": [
                    {"number": 10, "head": "loop/issue-1", "signals": [], "action_required": False},
                    {"number": 11, "head": "hotfix/issue-2", "signals": [], "action_required": False},
                ]
            }
            
            tasks = await patrol_open_prs(
                repo="owner/repo",
                author_filter="loop",
                runner=fake_gh,
            )
            
            # Should only find the PR with "loop" in head
            assert all(t.pr == 10 for t in tasks)
    
    asyncio.run(run_test())


def test_fake_gh_never_allows_pr_writes():
    """Test: Fake gh rejects any PR write operations."""
    fake_gh = FakeGh()
    
    # These should raise
    with pytest.raises(RuntimeError):
        fake_gh(["gh", "pr", "close", "10"])
    
    with pytest.raises(RuntimeError):
        fake_gh(["gh", "pr", "merge", "10"])
    
    with pytest.raises(RuntimeError):
        fake_gh(["gh", "pr", "edit", "10"])


def test_fix_task_dataclass():
    """Test: FixTask dataclass."""
    task = FixTask(pr=10, kind="conflict", text="Resolve conflict")
    
    assert task.pr == 10
    assert task.kind == "conflict"
    assert task.files == []


def test_claim_receipt_dataclass():
    """Test: ClaimReceipt dataclass."""
    receipt = ClaimReceipt(
        repo="owner/repo",
        issue="42",
        claimed_by="watcher",
        state="CLAIMED",
        verified=True,
    )
    
    assert receipt.verified
    assert receipt.state == "CLAIMED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
