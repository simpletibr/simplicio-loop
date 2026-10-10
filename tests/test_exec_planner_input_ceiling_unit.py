"""The exec planner does not send a request above the input-token ceiling (#1608, part C)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from simplicio_loop import exec_planner
from simplicio_loop.input_ceiling import ENV_NAME, TOML_KEY, CeilingConfigError, InputCeilingExceeded


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """The repo being worked on; the process cwd is ANOTHER directory."""
    root = tmp_path / "repo"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv(ENV_NAME, raising=False)
    return root


def _write_toml(root, body):
    (root / ".simplicio-loop").mkdir(exist_ok=True)
    (root / ".simplicio-loop" / "loop.toml").write_text(body, encoding="utf-8")


def test_a_prompt_under_the_ceiling_is_sent(repo, monkeypatch):
    """A request with a prompt under the ceiling is sent."""
    calls = []
    
    async def mock_run(*args, **kwargs):
        calls.append((args, kwargs))
        return json.dumps({"operations": []}), "", 0
    
    async def test_impl():
        monkeypatch.setattr("simplicio_loop.exec_planner._run_subprocess", mock_run)
        monkeypatch.setattr("simplicio_loop.exec_planner._find_cli", lambda x: f"/usr/bin/{x}")
        
        result = await exec_planner.run_planner(
            "claude", "coordination", "test prompt", repo_root=repo, cwd=str(repo)
        )
        assert len(calls) == 1, f"Expected 1 request, got {len(calls)}"
        assert result.reason_code != "cli_missing"
    
    asyncio.run(test_impl())


def test_a_prompt_over_the_ceiling_is_not_sent(repo, monkeypatch):
    """A request with a prompt over the ceiling is not sent."""
    calls = []
    
    async def mock_run(*args, **kwargs):
        calls.append((args, kwargs))
        return "{}", "", 0
    
    async def test_impl():
        monkeypatch.setattr("simplicio_loop.exec_planner._run_subprocess", mock_run)
        monkeypatch.setattr("simplicio_loop.exec_planner._find_cli", lambda x: f"/usr/bin/{x}")
        monkeypatch.setenv(ENV_NAME, "1000")
        
        result = await exec_planner.run_planner(
            "claude", "coordination", "word " * 5000, repo_root=repo, cwd=str(repo)
        )
        assert result.reason_code == "input_ceiling_exceeded", f"Got {result.reason_code}: {result.error}"
        assert len(calls) == 0, f"Expected 0 requests, got {len(calls)}"
    
    asyncio.run(test_impl())


def test_the_ceiling_of_loop_toml_applies(repo, monkeypatch):
    """The ceiling from loop.toml is applied."""
    _write_toml(repo, f"{TOML_KEY} = 1000\n")
    calls = []
    
    async def mock_run(*args, **kwargs):
        calls.append((args, kwargs))
        return "{}", "", 0
    
    async def test_impl():
        monkeypatch.setattr("simplicio_loop.exec_planner._run_subprocess", mock_run)
        monkeypatch.setattr("simplicio_loop.exec_planner._find_cli", lambda x: f"/usr/bin/{x}")
        
        result = await exec_planner.run_planner(
            "claude", "coordination", "word " * 5000, repo_root=repo, cwd=str(repo)
        )
        assert result.reason_code == "input_ceiling_exceeded"
        assert len(calls) == 0
    
    asyncio.run(test_impl())


def test_a_bad_ceiling_fails_loud_without_sending(repo, monkeypatch):
    """A bad ceiling in env fails loud without sending."""
    calls = []
    
    async def mock_run(*args, **kwargs):
        calls.append((args, kwargs))
        return "{}", "", 0
    
    async def test_impl():
        monkeypatch.setattr("simplicio_loop.exec_planner._run_subprocess", mock_run)
        monkeypatch.setattr("simplicio_loop.exec_planner._find_cli", lambda x: f"/usr/bin/{x}")
        monkeypatch.setenv(ENV_NAME, "abc")
        
        result = await exec_planner.run_planner(
            "claude", "coordination", "test", repo_root=repo, cwd=str(repo)
        )
        assert result.reason_code == "ceiling_invalid"
        assert len(calls) == 0
    
    asyncio.run(test_impl())


def test_the_loop_toml_of_the_cwd_is_not_the_one_read(repo, monkeypatch):
    """A call that names its repo never reads the loop.toml of the cwd."""
    _write_toml(Path.cwd(), f"{TOML_KEY} = 1\n")
    calls = []
    
    async def mock_run(*args, **kwargs):
        calls.append((args, kwargs))
        return json.dumps({"operations": []}), "", 0
    
    async def test_impl():
        monkeypatch.setattr("simplicio_loop.exec_planner._run_subprocess", mock_run)
        monkeypatch.setattr("simplicio_loop.exec_planner._find_cli", lambda x: f"/usr/bin/{x}")
        
        result = await exec_planner.run_planner(
            "claude", "coordination", "test", repo_root=repo, cwd=str(repo)
        )
        assert result.is_ok(), f"Should use repo ceiling (98k), not cwd (1): {result.reason_code}"
        assert len(calls) == 1
    
    asyncio.run(test_impl())
