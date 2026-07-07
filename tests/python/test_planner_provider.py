"""Unit tests for the planner provider routing in simplicio.providers."""

from __future__ import annotations

import importlib

import pytest

import simplicio.providers as P


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in (
        "SIMPLICIO_PLANNER",
        "HF_TOKEN",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "SIMPLICIO_API_KEY",
        "SIMPLICIO_BASE_URL",
        "SIMPLICIO_MODEL",
    ):
        monkeypatch.delenv(v, raising=False)
    importlib.reload(P)


def test_default_planner_is_deepseek_hf() -> None:
    # default route demands HF_TOKEN; without it must raise
    with pytest.raises(SystemExit) as exc:
        P.planner_cfg()
    assert "HF_TOKEN" in str(exc.value)


def test_deepseek_hf_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-stub")
    cfg = P.planner_cfg()
    assert cfg["model"] == "deepseek-ai/DeepSeek-V3.1"
    assert cfg["base"] == "https://router.huggingface.co/v1"
    assert cfg["key"] == "hf-stub"
    assert cfg["native_anthropic"] is False
    assert cfg["shell_out"] is False


def test_deepseek_direct_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PLANNER", "deepseek/deepseek-v4-pro")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-stub")
    cfg = P.planner_cfg()
    assert cfg["model"] == "deepseek-v4-pro"
    assert cfg["base"] == "https://api.deepseek.com/v1"


def test_openai_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PLANNER", "openai/gpt-5.5")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stub")
    cfg = P.planner_cfg()
    assert cfg["model"] == "gpt-5.5"
    assert cfg["base"] == "https://api.openai.com/v1"


def test_openrouter_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PLANNER", "openrouter/qwen/qwen3.7-max")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-stub")
    cfg = P.planner_cfg()
    assert cfg["model"] == "qwen/qwen3.7-max"
    assert cfg["base"] == "https://openrouter.ai/api/v1"


def test_anthropic_native_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PLANNER", "anthropic/claude-opus-4-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stub")
    cfg = P.planner_cfg()
    assert cfg["model"] == "claude-opus-4-8"
    assert cfg["native_anthropic"] is True
    assert cfg["base"] is None


def test_hf_generic_route_for_non_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PLANNER", "hf/Qwen/Qwen3-Coder-Next")
    monkeypatch.setenv("HF_TOKEN", "hf-stub")
    cfg = P.planner_cfg()
    assert cfg["model"] == "Qwen/Qwen3-Coder-Next"
    assert cfg["base"] == "https://router.huggingface.co/v1"


def test_shell_out_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PLANNER", "claude-cli/sonnet")
    cfg = P.planner_cfg()
    assert cfg["shell_out"] is True
    assert cfg["model"].startswith("claude-cli/")


def test_local_llama_planner_runs_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None, str, int]] = []

    def fake_local_generate(
        prompt: str,
        feedback: str | None,
        model: str,
        max_tokens: int,
    ) -> str:
        calls.append((prompt, feedback, model, max_tokens))
        return "local plan"

    monkeypatch.setenv("SIMPLICIO_MODEL", "local-llama/default")
    monkeypatch.setenv("SIMPLICIO_PLANNER", "local-llama/default")
    monkeypatch.setenv("SIMPLICIO_BUST_CACHE", "1")
    monkeypatch.setattr(P, "_local_generate", fake_local_generate)

    assert P.planner_complete("plan this", max_tokens=123) == "local plan"
    assert len(calls) == 1
    sent_prompt, sent_feedback, sent_model, sent_max = calls[0]
    assert sent_prompt.startswith(P.LLM_DIRECTIVES)
    assert "plan this" in sent_prompt
    assert (sent_feedback, sent_model, sent_max) == (None, "local-llama/default", 123)


def test_missing_credentials_clearly_signaled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLICIO_PLANNER", "deepseek/deepseek-v4-pro")
    with pytest.raises(SystemExit) as exc:
        P.planner_cfg()
    assert "DEEPSEEK_API_KEY" in str(exc.value)


def test_planner_info_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-stub")
    info = P.planner_info()
    assert "deepseek-ai/DeepSeek-V3.1" in info
    assert "key=set" in info
