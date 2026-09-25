"""Hosts write only find/replace ops; the loop freezes them right before apply.

Compiling at dispatch (not up front) binds each task's plan to the tree the
previous task left behind, so a serial wave of N host plans never drifts.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from simplicio_loop import runner

pytestmark = pytest.mark.skipif(shutil.which("simplicio-dev-cli") is None,
                                reason="simplicio-dev-cli (bound operator) not installed")


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "ops.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], check=True)
    return tmp_path


def test_minimal_plan_is_compiled_into_a_full_edit_plan(tmp_path):
    repo = _repo(tmp_path)
    plan_path = tmp_path / "edit-plan-1.json"
    plan_path.write_text(json.dumps({"operations": [
        {"path": "ops.py", "find": "    return a + b\n", "replace": "    return a + b  # ok\n"}]}))
    compiled, error = runner._compile_minimal_host_plan(repo, plan_path)
    assert error == ""
    assert compiled["schema"] == "simplicio.dev-cli.edit-plan/v1"
    assert json.loads(plan_path.read_text())["schema"] == "simplicio.dev-cli.edit-plan/v1"


def test_full_plans_are_left_untouched(tmp_path):
    repo = _repo(tmp_path)
    plan_path = tmp_path / "edit-plan-1.json"
    full = {"schema": "simplicio.dev-cli.edit-plan/v1", "operations": []}
    plan_path.write_text(json.dumps(full))
    compiled, error = runner._compile_minimal_host_plan(repo, plan_path)
    assert (compiled, error) == (full, "")


def test_a_bad_anchor_is_reported_not_applied(tmp_path):
    repo = _repo(tmp_path)
    plan_path = tmp_path / "edit-plan-1.json"
    plan_path.write_text(json.dumps({"operations": [{"path": "ops.py", "find": "nope", "replace": "x"}]}))
    compiled, error = runner._compile_minimal_host_plan(repo, plan_path)
    assert compiled is None
    assert "missing_anchor" in error


def test_dispatch_finds_a_minimal_host_plan_in_the_run_dir(tmp_path):
    (tmp_path / "edit-plan-2.json").write_text(json.dumps({"operations": [
        {"path": "ops.py", "find": "a", "replace": "b"}]}))
    plan, path, source = runner._resolve_host_edit_plan(tmp_path, task_index=2, env={})
    assert plan is not None and path.name == "edit-plan-2.json"
    assert source == "run_dir:edit-plan-2.json"
