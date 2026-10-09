"""Gap tests for simplicio_loop map service git defaults (#1574): default_branch_ref priority."""

from __future__ import annotations

import subprocess
from pathlib import Path

from simplicio_loop.map_service_git import (
    default_branch_ref,
    resolve_default_base,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _repo(root: Path, branch: str = "main") -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", branch)
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    (root / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def test_b1_main_and_master_both_exist_locally_prefer_main(tmp_path):
    """Both `main` and `master` exist locally (no origin): branch should be "main".
    
    Mutant: swap the tuple `("main", "master")` into `("master", "main")` in default_branch_ref.
    """
    root = _repo(tmp_path / "repo", branch="main")
    # Create a master branch too
    _git(root, "branch", "master")
    
    result = default_branch_ref(str(root))
    assert result is not None
    assert result[0] == "main", f"Expected 'main' but got {result[0]}"
    assert "main" in result[1]


def test_b2_refs_loop_order_remote_before_local(tmp_path):
    """The loop in default_branch_ref checks remote refs before local refs.
    
    When both local main and remote origin/main exist, and refs/remotes/origin/HEAD is not set,
    the loop checks them in order ("refs/remotes/origin/main", "refs/heads/main").
    The first match (remote ref) is returned.
    
    Mutant: swap the order to ("refs/heads/main", "refs/remotes/origin/main") in the loop.
    This would make it return the local ref instead of the remote ref.
    """
    root = _repo(tmp_path / "repo", branch="main")
    
    # Create a bare origin
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    
    # Add origin and push main to it
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "push", "-q", "origin", "main")
    # Do NOT call `_git(root, "remote", "set-head", "origin", "main")`
    # so that refs/remotes/origin/HEAD is not set and the loop is executed
    
    # Fetch to set up remote tracking
    _git(root, "fetch", "origin", "main")
    
    # With the current code, it checks refs/remotes/origin/main first
    result = default_branch_ref(str(root))
    assert result is not None
    branch, ref = result
    assert branch == "main"
    # The current code checks refs/remotes/origin/main before refs/heads/main
    assert ref == "refs/remotes/origin/main", f"Expected refs/remotes/origin/main but got {ref}"
