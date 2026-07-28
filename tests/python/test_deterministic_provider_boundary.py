"""The Python adapter must never execute an LLM provider."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock

import pytest

from simplicio import providers
from simplicio.commands import smoke


def test_generate_blocks_every_route_without_touching_process_or_network(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "deepseek/deepseek-chat")
    monkeypatch.setenv("SIMPLICIO_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("SIMPLICIO_API_KEY", "sk-or-test")
    socket_factory = Mock(side_effect=AssertionError("network must not be opened"))
    subprocess_runner = Mock(side_effect=AssertionError("provider subprocess must not run"))
    monkeypatch.setattr("socket.socket", socket_factory)
    monkeypatch.setattr("subprocess.run", subprocess_runner)

    with pytest.raises(providers.ProviderExecutionError) as error:
        providers.generate("do not send this")

    assert error.value.receipt["reason_code"] == "llm_execution_disabled"
    assert error.value.receipt["status"] == "blocked"
    socket_factory.assert_not_called()
    subprocess_runner.assert_not_called()


def test_planner_blocks_even_when_local_and_remote_configuration_is_present(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_PLANNER", "anthropic/claude-opus")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("SIMPLICIO_LOCAL_INFERENCE", "enabled")

    with pytest.raises(providers.ProviderExecutionError) as error:
        providers.planner_complete("do not send this")

    assert error.value.receipt["surface"] == "planner_complete"
    assert error.value.receipt["reason_code"] == "llm_execution_disabled"


def test_provider_module_contains_no_provider_execution_symbols():
    source = Path(providers.__file__).read_text(encoding="utf-8").lower()
    forbidden = (
        "import anthropic",
        "import openai",
        "from openai",
        "from llama_cpp",
        "subprocess.run",
        "anthropic.anthropic",
        "openai(",
    )
    assert [token for token in forbidden if token in source] == []


def test_smoke_is_deterministic_and_reports_disabled_policy(capsys):
    assert smoke.run(Namespace(json=True, root=".")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["provider"].startswith("provider=disabled")
    assert "LLM execution disabled" in payload["reply"]
