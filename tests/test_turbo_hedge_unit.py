"""3.45.2: the turbo hedge only fires on real tails, not on the 3-8 s calls providers normally take."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from simplicio_loop import turbo_provider

ROOT = Path(__file__).resolve().parents[1]
# Measured on 12 CLI calls of 3.45.0/3.45.1 (deepseek-v4.1-flash on OpenRouter): the slowest normal call and the one real tail.
SLOWEST_NORMAL_CALL_S = 8.04
REAL_TAIL_S = 19.64


class _VirtualClockLoop(asyncio.SelectorEventLoop):
    """An event loop whose clock jumps to the next timer: a 9.9 s call takes no wall time."""

    def __init__(self) -> None:
        super().__init__()
        self._now = 0.0

    def time(self) -> float:
        return self._now

    def _run_once(self) -> None:
        if not self._ready and self._scheduled:
            self._now = max(self._now, self._scheduled[0]._when)
        super()._run_once()


def _run_with_a_call_of(seconds: float, monkeypatch) -> tuple[dict, list[str]]:
    """complete() with the default hedge delay while every request takes `seconds` of loop time."""
    sessions: list[str] = []

    async def post(body, key, session_id, timeout):
        sessions.append(session_id)
        await asyncio.sleep(seconds)
        return {"ok": True, "content": "{}", "provider": "AtlasCloud", "latency_s": seconds}

    monkeypatch.setattr(turbo_provider, "_post", post)
    with asyncio.Runner(loop_factory=_VirtualClockLoop) as runner:
        reply = runner.run(turbo_provider.complete("simplicio", [], session_id="s"))
    return reply, sessions


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
    reply, sessions = _run_with_a_call_of(5.0, monkeypatch)
    assert reply["ok"] and reply["hedged"] is False
    assert sessions == ["s"]  # one request, one bill: no duplicate went out


@pytest.mark.parametrize("seconds", [1.7, SLOWEST_NORMAL_CALL_S, 9.9])
def test_every_normal_call_up_to_the_slowest_measured_is_not_hedged(default_hedge, monkeypatch, seconds):
    reply, sessions = _run_with_a_call_of(seconds, monkeypatch)
    assert reply["hedged"] is False
    assert sessions == ["s"]


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
