"""endpoint_compare (verify): detects HTTP endpoint changes from the diff.

Applies only when the diff touches routes, handlers or API definitions.
Reuses existing endpoint-diff tools or records route signatures (old vs new).
"""
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import points


def test_endpoint_compare_applies_on_routes_diff(point_contract, make_ctx, tmp_path):
    """When diff touches routes/handlers, the point runs and records endpoint changes."""
    clone = tmp_path / "repo"
    clone.mkdir()
    (clone / "routes").mkdir()
    (clone / "routes" / "api.py").write_text("@app.route('/old')", encoding="utf-8")
    
    # Initialize git repo and create a diff
    subprocess.run(["git", "init"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=clone, check=True, capture_output=True)
    
    # Modify route
    (clone / "routes" / "api.py").write_text("@app.route('/new')", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    
    ctx = make_ctx(clone=clone, verify="ok")
    result = point_contract("endpoint_compare", ctx, expect="ok")
    assert "endpoints" in result.evidence or "changed_routes" in result.evidence


def test_endpoint_compare_skipped_when_no_routes_touched(point_contract, make_ctx, tmp_path):
    """When diff does not touch routes/handlers, the point is skipped."""
    clone = tmp_path / "repo"
    clone.mkdir()
    (clone / "src").mkdir()
    (clone / "src" / "utils.py").write_text("def helper(): pass", encoding="utf-8")
    
    # Initialize git repo
    subprocess.run(["git", "init"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=clone, check=True, capture_output=True)
    
    # Modify utility file, not routes
    (clone / "src" / "utils.py").write_text("def helper(x): return x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    
    ctx = make_ctx(clone=clone, verify="ok")
    result = point_contract("endpoint_compare", ctx, expect="skipped")
    assert result.reason_code == "no_routes_touched"
