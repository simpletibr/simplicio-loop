"""transform_guard (verify): ensures removed symbols are not referenced elsewhere.

Applies only when task text contains refactor, rename, migrate or transform keywords.
Uses git grep to verify no dangling references remain.
"""
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import points


def test_transform_guard_applies_on_refactor_task(point_contract, make_ctx, tmp_path):
    """When task mentions refactor, the point checks for dangling references."""
    clone = tmp_path / "repo"
    clone.mkdir()
    (clone / "old_module.py").write_text("def old_function(): pass\n", encoding="utf-8")
    (clone / "main.py").write_text("from old_module import old_function\n", encoding="utf-8")
    
    # Initialize git repo
    subprocess.run(["git", "init"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=clone, check=True, capture_output=True)
    
    # Remove the old function but leave the import
    (clone / "old_module.py").write_text("# module removed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    
    task_text = "refactor: rename old_function to new_function"
    ctx = make_ctx(clone=clone, task_text=task_text, verify="ok")
    result = point_contract("transform_guard", ctx, expect="ok")
    assert "symbols_checked" in result.evidence


def test_transform_guard_skipped_when_task_is_not_transform(point_contract, make_ctx, tmp_path):
    """When task is not a refactor/rename/migrate, the point is skipped."""
    clone = tmp_path / "repo"
    clone.mkdir()
    (clone / "main.py").write_text("print('hello')", encoding="utf-8")
    
    subprocess.run(["git", "init"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=clone, check=True, capture_output=True)
    
    (clone / "main.py").write_text("print('world')", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    
    task_text = "fix: update greeting message"
    ctx = make_ctx(clone=clone, task_text=task_text, verify="ok")
    result = point_contract("transform_guard", ctx, expect="skipped")
    assert result.reason_code == "not_applicable"


def test_transform_guard_ok_when_removed_symbols_replaced(point_contract, make_ctx, tmp_path):
    """When removed symbols are properly replaced, the point returns ok."""
    clone = tmp_path / "repo"
    clone.mkdir()
    (clone / "old_module.py").write_text("def old_function(): pass\n", encoding="utf-8")
    (clone / "main.py").write_text("from old_module import old_function\n", encoding="utf-8")
    
    subprocess.run(["git", "init"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=clone, check=True, capture_output=True)
    
    # Remove old and replace with new
    (clone / "old_module.py").write_text("def new_function(): pass\n", encoding="utf-8")
    (clone / "main.py").write_text("from old_module import new_function\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    
    task_text = "refactor: rename old_function to new_function"
    ctx = make_ctx(clone=clone, task_text=task_text, verify="ok")
    result = point_contract("transform_guard", ctx, expect="ok")
    assert result.status == "ok"
