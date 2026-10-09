"""Unit tests for exec_planner: CLI exec launcher for planning, coordination, execution.

Tests use fake CLI scripts on PATH in a temporary directory.
No real model CLIs are called.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from simplicio_loop import exec_planner, model_roles


@pytest.fixture
def fake_cli_dir():
    """Create a temporary directory with fake CLI scripts on PATH."""
    with tempfile.TemporaryDirectory(prefix="test-cli-") as tmpdir:
        bin_dir = Path(tmpdir) / "bin"
        bin_dir.mkdir()
        
        # Fake claude CLI
        (bin_dir / "claude").write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "json.dump({'operations': [{'path': 'test.txt', 'find': '', 'replace': 'hello'}]}, sys.stdout)\n"
        )
        (bin_dir / "claude").chmod(0o755)
        
        # Fake codex CLI (reads from stdin)
        (bin_dir / "codex").write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "prompt = sys.stdin.read()\n"
            "json.dump({'operations': [{'path': 'test.txt', 'find': '', 'replace': 'hello from codex'}]}, sys.stdout)\n"
        )
        (bin_dir / "codex").chmod(0o755)
        
        # Fake grok CLI
        (bin_dir / "grok").write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "json.dump({'operations': [{'path': 'test.txt', 'find': '', 'replace': 'hello from grok'}]}, sys.stdout)\n"
        )
        (bin_dir / "grok").chmod(0o755)
        
        # Fake gemini CLI
        (bin_dir / "gemini").write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "json.dump({'operations': [{'path': 'test.txt', 'find': '', 'replace': 'hello from gemini'}]}, sys.stdout)\n"
        )
        (bin_dir / "gemini").chmod(0o755)
        
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(bin_dir) + ":" + old_path
        yield bin_dir
        os.environ["PATH"] = old_path


def test_build_argv_claude():
    argv = exec_planner.build_argv("claude", "planning", "test prompt", "claude-opus-5-5", ".")
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "test prompt" in argv
    assert "--model" in argv
    assert "claude-opus-5-5" in argv
    assert "--output-format" in argv
    assert "json" in argv


def test_build_argv_codex():
    argv = exec_planner.build_argv("codex", "execution", "test prompt", "gpt-6-luna", "/tmp")
    assert argv[0] == "codex"
    assert "exec" in argv
    assert "--cd" in argv
    assert "/tmp" in argv
    assert "--model" in argv
    assert "gpt-6-luna" in argv
    assert "-" in argv


def test_build_argv_grok():
    argv = exec_planner.build_argv("grok", "coordination", "test prompt", "grok-4.6", ".")
    assert argv[0] == "grok"
    assert "-p" in argv
    assert "test prompt" in argv
    assert "--model" in argv
    assert "--output-format" in argv


def test_build_argv_gemini():
    argv = exec_planner.build_argv("gemini", "planning", "test prompt", "gemini-3.8-flash", ".")
    assert argv[0] == "gemini"
    assert "-p" in argv
    assert "--model" in argv


def test_build_argv_unknown_family():
    with pytest.raises(exec_planner.ExecPlannerError):
        exec_planner.build_argv("mistral", "planning", "test", "mistral-7b", ".")


def test_planner_result_to_dict():
    result = exec_planner.PlannerResult(
        reason_code="ok",
        family="claude",
        role="planning",
        model="claude-opus-5-5",
        effort="high",
        plan={"operations": []},
        execution_ms=100.5,
    )
    d = result.to_dict()
    assert d["reason_code"] == "ok"
    assert d["family"] == "claude"
    assert d["execution_ms"] == 100.5


def test_extract_plan_json_raw():
    output = '{"operations": [{"path": "test.txt", "find": "", "replace": "hello"}]}'
    plan = exec_planner._extract_plan_json(output)
    assert "operations" in plan
    assert len(plan["operations"]) == 1


def test_extract_plan_json_invalid():
    with pytest.raises(ValueError):
        exec_planner._extract_plan_json("this is not json")


def test_get_families_default():
    if "SIMPLICIO_EXEC_FAMILIES" in os.environ:
        del os.environ["SIMPLICIO_EXEC_FAMILIES"]
    families = exec_planner._get_families()
    assert families == exec_planner.DEFAULT_FAMILIES
