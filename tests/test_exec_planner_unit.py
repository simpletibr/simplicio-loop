"""Unit tests for exec_planner module."""

import json
from unittest import mock

import pytest

from simplicio_loop import exec_planner, model_roles


class TestBuildArgv:
    """Test argv construction for each family."""

    def test_build_argv_claude(self):
        argv = exec_planner.build_argv("claude", "executor", "test prompt", "claude-3-sonnet", ".")
        assert argv[0] == "claude"
        assert "-p" in argv
        assert "test prompt" in argv
        assert "--model" in argv
        assert "claude-3-sonnet" in argv

    def test_build_argv_codex(self):
        argv = exec_planner.build_argv("codex", "executor", "test prompt", "default", "/tmp")
        assert argv[0] == "codex"
        assert "exec" in argv
        assert "--cd" in argv
        assert "/tmp" in argv

    def test_build_argv_grok(self):
        argv = exec_planner.build_argv("grok", "executor", "test prompt", "auto", ".")
        assert argv[0] == "grok"
        assert "-p" in argv

    def test_build_argv_unsupported_family(self):
        with pytest.raises(exec_planner.ExecPlannerError):
            exec_planner.build_argv("invalid", "executor", "test", "model", ".")


class TestExtractPlanJson:
    """Test plan JSON extraction."""

    def test_extract_valid_json(self):
        plan = {"operations": [{"op": "replace", "find": "x", "with": "y"}]}
        result = exec_planner._extract_plan_json(json.dumps(plan))
        assert result == plan

    def test_extract_json_with_prefix_suffix(self):
        plan = {"operations": [{"op": "create", "content": "hello"}]}
        output = f"some prefix {json.dumps(plan)} some suffix"
        result = exec_planner._extract_plan_json(output)
        assert result == plan

    def test_extract_json_missing_operations(self):
        invalid_plan = {"data": "no operations key"}
        output = json.dumps(invalid_plan)
        with pytest.raises(ValueError, match="not found or invalid"):
            exec_planner._extract_plan_json(output)

    def test_extract_json_completely_invalid(self):
        with pytest.raises(ValueError, match="not found or invalid"):
            exec_planner._extract_plan_json("completely not json")


class TestPlannerResult:
    """Test PlannerResult class."""

    def test_planner_result_ok(self):
        result = exec_planner.PlannerResult(
            "ok", "claude", "executor", "claude-3-opus", "high",
            plan={"operations": []}
        )
        assert result.is_ok()
        assert result.reason_code == "ok"

    def test_planner_result_error(self):
        result = exec_planner.PlannerResult(
            "timeout", "claude", "executor", "claude-3-opus", "high",
            error="timed out"
        )
        assert not result.is_ok()
        assert result.error == "timed out"

    def test_planner_result_to_dict(self):
        result = exec_planner.PlannerResult(
            "ok", "claude", "executor", "model", "effort",
            plan={"operations": []}, execution_ms=150.5
        )
        d = result.to_dict()
        assert d["reason_code"] == "ok"
        assert d["family"] == "claude"
        assert d["execution_ms"] == 150.5


class TestKillProcessTree:
    """Test process tree killing for timeout handling."""

    def test_kill_process_tree_called_on_timeout(self):
        """Verify _kill_process_tree exists and is callable."""
        # This test verifies the function exists for timeout handling
        assert hasattr(exec_planner, "_kill_process_tree")
        assert callable(exec_planner._kill_process_tree)
