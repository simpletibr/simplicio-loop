"""3.45.2: the turbo hedge only fires on real tails, not on the 3-8 s calls providers normally take."""
from __future__ import annotations

import concurrent.futures
from pathlib import Path

import pytest

from simplicio_loop import turbo_provider

ROOT = Path(__file__).resolve().parents[1]
# Measured on 12 CLI calls of 3.45.0/3.45.1 (deepseek-v4.1-flash on OpenRouter): the slowest normal call and the one real tail.
SLOWEST_NORMAL_CALL_S = 8.04
REAL_TAIL_S = 19.64


class _Call:
    """A call that ends `seconds` after it starts: waiting less than that times out."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds

    def result(self, timeout: float | None = None) -> dict:
        if timeout is not None and timeout < self.seconds:
            raise concurrent.futures.TimeoutError()
        return {"ok": True, "content": "{}", "provider": "AtlasCloud", "latency_s": self.seconds}


class _Pool:
    """Stands in for the provider's thread pool: records every session a request went out on."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.sessions: list[str] = []

    def submit(self, fn, body, key, session_id, timeout) -> _Call:
        self.sessions.append(session_id)
        return _Call(self.seconds)


@pytest.fixture
def default_hedge(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv("SIMPLICIO_TURBO_HEDGE_AFTER", raising=False)


def test_the_default_hedge_is_ten_seconds_between_the_slowest_normal_call_and_the_real_tail(default_hedge):
    assert turbo_provider.DEFAULT_HEDGE_AFTER == 10
    assert turbo_provider.hedge_after() == 10.0
    assert SLOWEST_NORMAL_CALL_S < turbo_provider.hedge_after() < REAL_TAIL_S


def test_a_five_second_call_is_not_hedged_by_default(default_hedge, monkeypatch):
    """3.45.1 waited 2.5 s and then billed a duplicate for a call like this one, which was fine."""
    import asyncio
    
    async def mock_post(body, key, session_id, timeout):
        await asyncio.sleep(5.0)
        return {"ok": True, "content": "done", "latency_s": 5.0}
    
    monkeypatch.setattr(turbo_provider, "_post", mock_post)
    reply = asyncio.run(turbo_provider.complete("simplicio", [], session_id="s"))
    assert reply["ok"] and reply["hedged"] is False


@pytest.mark.parametrize("seconds", [1.7, SLOWEST_NORMAL_CALL_S, 9.9])
def test_every_normal_call_up_to_the_slowest_measured_is_not_hedged(default_hedge, monkeypatch, seconds):
    import asyncio
    
    async def mock_post(body, key, session_id, timeout):
        await asyncio.sleep(seconds)
        return {"ok": True, "content": "done", "latency_s": seconds}
    
    monkeypatch.setattr(turbo_provider, "_post", mock_post)
    result = asyncio.run(turbo_provider.complete("simplicio", [], session_id="s"))
    assert result["hedged"] is False


@pytest.mark.parametrize("raw, expected", [("2.5", 2.5), ("30", 30.0), ("0", 0.0), ("junk", 10.0), ("", 10.0)])
def test_the_hedge_delay_can_be_set_or_switched_off_from_the_environment(monkeypatch, raw, expected):
    monkeypatch.setenv("SIMPLICIO_TURBO_HEDGE_AFTER", raw)
    assert turbo_provider.hedge_after() == expected


def test_the_documented_default_is_the_code_default():
    default = f"default {turbo_provider.DEFAULT_HEDGE_AFTER:g}"
    module_doc = " ".join(turbo_provider.__doc__.split())
    standard = " ".join((ROOT / "bench" / "llm_ab" / "STANDARD.md").read_text(encoding="utf-8").split())
    assert default in module_doc and default in standard
    assert "8 s" in module_doc and "8 s" in standard  # why: above the slowest normal call measured
