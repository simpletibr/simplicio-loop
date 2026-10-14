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
    compiled, reason_code, error = runner._compile_minimal_host_plan(repo, plan_path)
    assert reason_code == ""
    assert error == ""
    assert compiled["schema"] == "simplicio.dev-cli.edit-plan/v1"
    assert json.loads(plan_path.read_text())["schema"] == "simplicio.dev-cli.edit-plan/v1"


def test_full_plans_are_left_untouched(tmp_path):
    repo = _repo(tmp_path)
    plan_path = tmp_path / "edit-plan-1.json"
    full = {"schema": "simplicio.dev-cli.edit-plan/v1", "operations": []}
    plan_path.write_text(json.dumps(full))
    compiled, reason_code, error = runner._compile_minimal_host_plan(repo, plan_path)
    assert (compiled, reason_code, error) == (full, "", "")


def test_a_bad_anchor_is_reported_not_applied(tmp_path):
    repo = _repo(tmp_path)
    plan_path = tmp_path / "edit-plan-1.json"
    plan_path.write_text(json.dumps({"operations": [{"path": "ops.py", "find": "nope", "replace": "x"}]}))
    compiled, reason_code, error = runner._compile_minimal_host_plan(repo, plan_path)
    assert compiled is None
    # simplicio-dev-cli's own `missing_anchor` error code -> a precise,
    # deterministic reason instead of the generic plan_compile_failed blob.
    assert reason_code == "plan_find_not_found"
    assert "ops.py" in error
    assert "nope" in error


def test_an_ambiguous_anchor_is_reported_not_applied(tmp_path):
    repo = _repo(tmp_path)
    (repo / "ops.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef add2(a, b):\n    return a + b\n", encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-aqm", "dup"], check=True)
    plan_path = tmp_path / "edit-plan-1.json"
    plan_path.write_text(json.dumps({"operations": [
        {"path": "ops.py", "find": "    return a + b\n", "replace": "x"}]}))
    compiled, reason_code, error = runner._compile_minimal_host_plan(repo, plan_path)
    assert compiled is None
    # simplicio-dev-cli's own `ambiguous_anchor` error code -> a precise,
    # deterministic reason instead of the generic plan_compile_failed blob.
    assert reason_code == "plan_find_not_unique"
    assert "ops.py" in error


def test_path_outside_authorized_targets_is_reported_precisely(tmp_path):
    repo = _repo(tmp_path)
    (repo / "other.py").write_text("x = 1\n", encoding="utf-8")
    plan = {"operations": [{"path": "other.py", "find": "x = 1\n", "replace": "x = 2\n"}]}
    issue = runner._validate_minimal_host_plan_paths(plan, repo, ["ops.py"])
    assert issue is not None
    assert issue["reason_code"] == "plan_path_not_authorized"
    assert "other.py" in issue["message"]
    assert "ops.py" in issue["message"]


def test_path_that_does_not_exist_is_reported_precisely(tmp_path):
    repo = _repo(tmp_path)
    plan = {"operations": [{"path": "missing.py", "find": "x", "replace": "y"}]}
    issue = runner._validate_minimal_host_plan_paths(plan, repo, ["missing.py"])
    assert issue is not None
    assert issue["reason_code"] == "plan_path_not_found"
    assert "missing.py" in issue["message"]


def test_valid_paths_have_no_issue(tmp_path):
    repo = _repo(tmp_path)
    plan = {"operations": [{"path": "ops.py", "find": "x", "replace": "y"}]}
    assert runner._validate_minimal_host_plan_paths(plan, repo, ["ops.py"]) is None
    # No authorized_targets recorded for this task -- existence still checked.
    assert runner._validate_minimal_host_plan_paths(plan, repo, []) is None


def test_dispatch_finds_a_minimal_host_plan_in_the_run_dir(tmp_path):
    (tmp_path / "edit-plan-2.json").write_text(json.dumps({"operations": [
        {"path": "ops.py", "find": "a", "replace": "b"}]}))
    plan, path, source = runner._resolve_host_edit_plan(tmp_path, task_index=2, env={})
    assert plan is not None and path.name == "edit-plan-2.json"
    assert source == "run_dir:edit-plan-2.json"


def test_schema_find_replace_plan_is_still_compiled(tmp_path):
    """Issue #1364: a schema does not skip compile when ops are still find/replace."""
    repo = _repo(tmp_path)
    plan_path = tmp_path / "edit-plan-1.json"
    plan_path.write_text(json.dumps({
        "schema": "simplicio.dev-cli.edit-plan/v1",
        "operations": [{
            "path": "ops.py",
            "find": "    return a + b\n",
            "replace": "    return a + b  # ok\n",
        }],
    }))
    compiled, reason_code, error = runner._compile_minimal_host_plan(repo, plan_path)
    assert reason_code == ""
    assert error == ""
    ops = compiled["operations"]
    assert ops and "op" in ops[0]
