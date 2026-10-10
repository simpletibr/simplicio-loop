"""The OpenRouter operator does not send a request above the input-token ceiling (#1608, part C)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from simplicio_loop import openrouter_operator
from simplicio_loop.input_ceiling import ENV_NAME, TOML_KEY, CeilingConfigError, InputCeilingExceeded


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """The repo being worked on; the process cwd is ANOTHER directory, so a cwd fallback cannot pass by accident."""
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


def _mock_response(content):
    """A mock response that returns the given content."""
    response = MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = None
    response.read.return_value = json.dumps(content).encode("utf-8")
    return response


def test_a_prompt_under_the_ceiling_is_sent(repo, monkeypatch):
    """A request with a prompt under the ceiling is sent."""
    target_file = repo / "test.txt"
    target_file.write_text("old content")
    
    calls = []
    
    def mock_urlopen(request, timeout):
        calls.append(request)
        return _mock_response({
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({
                        "files": {
                            "test.txt": "new content"
                        }
                    })
                }
            }],
            "usage": {
                "prompt_tokens": 1000,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0
            }
        })
    
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.setenv("SIMPLICIO_MODEL", "anthropic/claude-opus")
    
    task = {"id": "T-1", "goal": "edit the file"}
    mapper_context = {"mapper_generation": "g1"}
    result = openrouter_operator.request_mechanical_plan(
        task=task, target="test.txt", repo_path=repo, 
        mapper_context=mapper_context, run_id="run-1", 
        task_index=1, attempt=1
    )
    assert len(calls) == 1, f"Expected 1 request, got {len(calls)}"


def test_a_prompt_over_the_ceiling_is_not_sent(repo, monkeypatch):
    """A request with a prompt over the ceiling is not sent."""
    calls = []
    
    def mock_urlopen(request, timeout):
        calls.append(request)
        return _mock_response({"choices": []})
    
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.setenv("SIMPLICIO_MODEL", "anthropic/claude-opus")
    monkeypatch.setenv(ENV_NAME, "1000")
    
    task = {"id": "T-1", "goal": "word " * 5000, "type": "creation"}
    mapper_context = {"mapper_generation": "g1"}
    with pytest.raises(InputCeilingExceeded):
        openrouter_operator.request_mechanical_plan(
            task=task, target="test.txt", repo_path=repo,
            mapper_context=mapper_context, run_id="run-1",
            task_index=1, attempt=1
        )
    assert len(calls) == 0, f"Expected 0 requests, got {len(calls)}"


def test_the_ceiling_of_loop_toml_applies(repo, monkeypatch):
    """The ceiling from loop.toml is applied."""
    _write_toml(repo, f"{TOML_KEY} = 1000\n")
    calls = []
    
    def mock_urlopen(request, timeout):
        calls.append(request)
        return _mock_response({"choices": []})
    
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.setenv("SIMPLICIO_MODEL", "anthropic/claude-opus")
    
    task = {"id": "T-1", "goal": "word " * 5000, "type": "creation"}
    mapper_context = {"mapper_generation": "g1"}
    with pytest.raises(InputCeilingExceeded):
        openrouter_operator.request_mechanical_plan(
            task=task, target="test.txt", repo_path=repo,
            mapper_context=mapper_context, run_id="run-1",
            task_index=1, attempt=1
        )
    assert len(calls) == 0, f"Expected 0 requests, got {len(calls)}"


def test_a_bad_ceiling_fails_loud_without_sending(repo, monkeypatch):
    """A bad ceiling in env fails loud without sending."""
    calls = []
    
    def mock_urlopen(request, timeout):
        calls.append(request)
        return _mock_response({"choices": []})
    
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.setenv("SIMPLICIO_MODEL", "anthropic/claude-opus")
    monkeypatch.setenv(ENV_NAME, "abc")
    
    task = {"id": "T-1", "goal": "test", "type": "creation"}
    mapper_context = {"mapper_generation": "g1"}
    with pytest.raises(CeilingConfigError):
        openrouter_operator.request_mechanical_plan(
            task=task, target="test.txt", repo_path=repo,
            mapper_context=mapper_context, run_id="run-1",
            task_index=1, attempt=1
        )
    assert len(calls) == 0, f"Expected 0 requests, got {len(calls)}"


def test_the_loop_toml_of_the_cwd_is_not_the_one_read(repo, monkeypatch):
    """A call that names its repo never reads the loop.toml of the cwd."""
    _write_toml(Path.cwd(), f"{TOML_KEY} = 1\n")
    calls = []
    
    def mock_urlopen(request, timeout):
        calls.append(request)
        return _mock_response({
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({
                        "files": {
                            "test.txt": "content"
                        }
                    })
                }
            }],
            "usage": {
                "prompt_tokens": 1000,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0
            }
        })
    
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.setenv("SIMPLICIO_MODEL", "anthropic/claude-opus")
    
    task = {"id": "T-1", "goal": "test", "type": "creation"}
    mapper_context = {"mapper_generation": "g1"}
    result = openrouter_operator.request_mechanical_plan(
        task=task, target="test.txt", repo_path=repo,
        mapper_context=mapper_context, run_id="run-1",
        task_index=1, attempt=1
    )
    assert len(calls) == 1, "Should use repo ceiling (98k), not cwd (1)"
