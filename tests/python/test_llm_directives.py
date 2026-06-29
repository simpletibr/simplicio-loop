"""Operating-constraints directives injected into every LLM contact.

No-thinking / No-internet / tools-only-necessary / skills-only-necessary must
be prepended to the prompt on every doer and planner provider path, opt-out via
SIMPLICIO_NO_LLM_DIRECTIVES=1.
"""
from unittest.mock import patch

import pytest

from simplicio import providers
from simplicio._cache import reset_for_tests


@pytest.fixture(autouse=True)
def isolated_completion_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SIMPLICIO_BUST_CACHE", "1")
    reset_for_tests()
    yield
    reset_for_tests()


def test_directive_block_covers_the_four_constraints() -> None:
    block = providers.LLM_DIRECTIVES.lower()
    assert "no thinking" in block
    assert "no internet" in block
    assert "tools:" in block and "strictly necessary" in block
    assert "skills:" in block


def test_apply_directives_is_idempotent() -> None:
    once = providers._apply_directives("do x")
    twice = providers._apply_directives(once)
    assert once.startswith(providers.LLM_DIRECTIVES)
    assert "do x" in once
    assert once == twice  # never stacks the header twice


def test_apply_directives_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_NO_LLM_DIRECTIVES", "1")
    assert providers._apply_directives("do x") == "do x"


def test_generate_prepends_directives_on_shellout(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    class _R:
        returncode = 0
        stdout = "ok"
        stderr = ""

    with patch("subprocess.run", return_value=_R()) as run:
        providers.generate("write hello")

    sent = run.call_args[0][0][2]
    assert sent.startswith(providers.LLM_DIRECTIVES)
    assert "write hello" in sent


def test_generate_opt_out_sends_raw_prompt(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.setenv("SIMPLICIO_NO_LLM_DIRECTIVES", "1")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    class _R:
        returncode = 0
        stdout = "ok"
        stderr = ""

    with patch("subprocess.run", return_value=_R()) as run:
        providers.generate("write hello")

    assert run.call_args[0][0][2] == "write hello"


def test_generate_prepends_directives_on_openai_compatible(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_MODEL", "glm-4.6")
    monkeypatch.setenv("SIMPLICIO_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("SIMPLICIO_API_KEY", "k")
    seen = {}

    def fake_oai(model, base, key, prompt, feedback, max_tokens):
        seen["prompt"] = prompt
        return "diff"

    monkeypatch.setattr(providers, "_openai_compatible_generate", fake_oai)
    providers.generate("change y")

    assert seen["prompt"].startswith(providers.LLM_DIRECTIVES)
    assert "change y" in seen["prompt"]
