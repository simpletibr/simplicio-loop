"""The exec planner does not send a request above the input-token ceiling (#1608, part C)."""
from __future__ import annotations

import ast
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


def test_the_fallback_passes_the_repo_root_to_every_family(repo, monkeypatch):
    calls = []

    async def mock_run(*args, **kwargs):
        calls.append(args)
        return "{}", "", 0

    monkeypatch.setattr("simplicio_loop.exec_planner._run_subprocess", mock_run)
    monkeypatch.setattr("simplicio_loop.exec_planner._find_cli", lambda x: f"/usr/bin/{x}")
    monkeypatch.setenv(ENV_NAME, "1000")

    result = asyncio.run(exec_planner.run_planner_with_fallback(
        "coordination", "word " * 5000, cwd=str(repo), families=["claude", "codex"], repo_root=repo))
    assert result.reason_code == "input_ceiling_exceeded"
    assert calls == []


PRODUCTION_ROOT = Path(exec_planner.__file__).resolve().parent
PLANNER_CALLEES = {"run_planner", "run_planner_with_fallback"}


def _callee_name(call):
    func = call.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None


def _names_a_repo_root(call):
    return any(kw.arg == "repo_root" and not (isinstance(kw.value, ast.Constant) and kw.value.value is None)
               for kw in call.keywords)


def test_every_production_planner_call_names_the_repo_root():
    """A call without repo_root skips the ceiling, so each caller in the package must pass the repo it works in."""
    sites = [(path, node)
             for path in sorted(PRODUCTION_ROOT.rglob("*.py"))
             for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
             if isinstance(node, ast.Call) and _callee_name(node) in PLANNER_CALLEES]
    assert len(sites) >= 3, "the scan must find the known production callers"
    omitted = [f"{path.relative_to(PRODUCTION_ROOT)}:{node.lineno}" for path, node in sites if not _names_a_repo_root(node)]
    assert omitted == []


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
