"""Per-call usage-event logging (issue #88 AC3/AC4).

`generate()`/`planner_complete()` used to run zero `runs.jsonl` events per
provider call. This is opt-in via `SIMPLICIO_LOG_ROOT` (providers.py has no
notion of "project root" otherwise) and labels whether the token count came
from a real provider `usage` field or the canonical estimator.
"""
import json

import pytest

from simplicio import providers
from simplicio._cache import reset_for_tests


@pytest.fixture(autouse=True)
def isolated_completion_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("SIMPLICIO_BUST_CACHE", "1")
    monkeypatch.delenv("SIMPLICIO_DISABLE_RUN_LOG", raising=False)
    reset_for_tests()
    yield
    reset_for_tests()


def _read_events(root):
    path = root / ".simplicio" / "runs.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_no_log_root_means_no_event(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_LOG_ROOT", raising=False)
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    from unittest.mock import MagicMock, patch

    r = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=r):
        providers.generate("x")

    assert not (tmp_path / ".simplicio" / "runs.jsonl").exists()


def test_shell_out_call_logs_estimated_usage_event(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOG_ROOT", str(tmp_path))
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    from unittest.mock import MagicMock, patch

    r = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=r):
        providers.generate("write hello")

    events = _read_events(tmp_path)
    assert len(events) == 1
    event = events[0]
    assert event["mode"] == "provider_call"
    assert event["provider_id"] == "claude-cli"
    assert event["cache_hit"] is False
    assert event["usage_source"] == "estimated"
    assert event["tokens"]["completion"] >= 1


def test_cache_hit_logs_cache_hit_true(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)
    monkeypatch.delenv("SIMPLICIO_BUST_CACHE", raising=False)  # need the real cache here
    reset_for_tests()

    from unittest.mock import MagicMock, patch

    r = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=r):
        monkeypatch.delenv("SIMPLICIO_LOG_ROOT", raising=False)
        providers.generate("write hello")  # populates the cache, no log root yet

        monkeypatch.setenv("SIMPLICIO_LOG_ROOT", str(tmp_path))
        providers.generate("write hello")  # now a cache hit, with a log root

    events = _read_events(tmp_path)
    assert len(events) == 1
    assert events[0]["cache_hit"] is True


def test_openai_compatible_call_logs_provider_usage_when_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOG_ROOT", str(tmp_path))
    monkeypatch.setenv("SIMPLICIO_MODEL", "glm-4.6")
    monkeypatch.setenv("SIMPLICIO_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("SIMPLICIO_API_KEY", "k")

    def fake_openai(model, base, key, prompt, feedback, max_tokens):
        return "diff", {"prompt_tokens": 123, "completion_tokens": 45}

    monkeypatch.setattr(providers, "_openai_compatible_generate", fake_openai)
    providers.generate("change y")

    events = _read_events(tmp_path)
    assert len(events) == 1
    event = events[0]
    assert event["usage_source"] == "provider"
    assert event["tokens"]["prompt"] == 123
    assert event["tokens"]["completion"] == 45


def test_planner_complete_local_llama_logs_event(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOG_ROOT", str(tmp_path))
    monkeypatch.setenv("SIMPLICIO_PLANNER", "local-llama/default")

    monkeypatch.setattr(providers, "_local_generate", lambda *a, **k: "plan-json")
    out = providers.planner_complete("build a plan")
    assert out == "plan-json"

    events = _read_events(tmp_path)
    assert len(events) == 1
    assert events[0]["provider_id"] == "planner:local-llama"
    assert events[0]["surface"] == "planner_complete"
