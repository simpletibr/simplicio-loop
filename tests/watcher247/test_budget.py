"""Daily cap: per-UTC-day counters persisted atomically in the state dir."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import pytest

from simplicio_loop.watcher247 import budget, config, state


@pytest.fixture
def clock(tmp_path, monkeypatch):
    original = config.STATE_DIR
    config.set_state_dir(tmp_path)
    monkeypatch.delenv("SIMPLICIO_247_MAX_ISSUES_PER_DAY", raising=False)
    monkeypatch.delenv("SIMPLICIO_247_MAX_PRS_PER_DAY", raising=False)
    now = {"at": datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)}
    monkeypatch.setattr(state, "now", lambda: now["at"])
    yield now
    config.set_state_dir(original)


def stored():
    return json.loads(config.BUDGET.read_text())


def test_defaults_are_20_issues_and_10_prs(clock):
    assert budget.max_issues_per_day() == 20
    assert budget.max_prs_per_day() == 10


def test_ceilings_come_from_env(clock, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_MAX_ISSUES_PER_DAY", "3")
    monkeypatch.setenv("SIMPLICIO_247_MAX_PRS_PER_DAY", "2")
    assert budget.max_issues_per_day() == 3
    assert budget.max_prs_per_day() == 2


def test_invalid_env_falls_back_to_default(clock, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_MAX_ISSUES_PER_DAY", "lots")
    assert budget.max_issues_per_day() == 20


def test_counts_are_persisted_per_utc_day(clock):
    asyncio.run(budget.record("issues"))
    asyncio.run(budget.record("issues"))
    asyncio.run(budget.record("model_calls"))
    asyncio.run(budget.record("prs"))
    assert stored() == {"day": "2026-10-09", "issues": 2, "model_calls": 1, "prs": 1}


def test_unknown_counter_is_rejected(clock):
    with pytest.raises(ValueError):
        asyncio.run(budget.record("merges"))


def test_issues_ceiling_reached(clock, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_MAX_ISSUES_PER_DAY", "2")
    asyncio.run(budget.record("issues"))
    assert asyncio.run(budget.reached()) is None
    assert asyncio.run(budget.issues_left()) == 1
    asyncio.run(budget.record("issues"))
    assert asyncio.run(budget.reached()) == "issues"
    assert asyncio.run(budget.issues_left()) == 0


def test_prs_ceiling_reached(clock, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_MAX_PRS_PER_DAY", "1")
    asyncio.run(budget.record("prs"))
    assert asyncio.run(budget.reached()) == "prs"


def test_counters_reset_at_utc_midnight(clock, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_MAX_ISSUES_PER_DAY", "1")
    asyncio.run(budget.record("issues"))
    assert asyncio.run(budget.reached()) == "issues"
    clock["at"] = datetime(2026, 10, 10, 0, 0, 0, tzinfo=timezone.utc)
    assert asyncio.run(budget.reached()) is None
    snap = asyncio.run(budget.snapshot())
    assert snap["day"] == "2026-10-10" and snap["issues"] == 0 and snap["prs"] == 0


def test_last_second_of_the_day_still_counts_to_that_day(clock):
    clock["at"] = datetime(2026, 10, 9, 23, 59, 59, tzinfo=timezone.utc)
    asyncio.run(budget.record("issues"))
    assert stored()["day"] == "2026-10-09"


def test_concurrent_records_are_not_lost(clock):
    async def many():
        await asyncio.gather(*(budget.record("model_calls") for _ in range(25)))

    asyncio.run(many())
    assert stored()["model_calls"] == 25


def test_write_is_atomic_and_leaves_previous_file_on_failure(clock, monkeypatch):
    asyncio.run(budget.record("issues"))
    before = config.BUDGET.read_text()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(budget.os, "replace", boom)
    with pytest.raises(OSError):
        asyncio.run(budget.record("issues"))
    monkeypatch.undo()
    assert config.BUDGET.read_text() == before
    assert [p.name for p in config.STATE_DIR.iterdir() if p.name.startswith("budget.json.")] == []


def test_write_goes_through_a_temp_file_then_rename(clock, monkeypatch):
    seen = []
    real = os.replace

    def spy(src, dst):
        seen.append((os.path.basename(src), os.path.basename(dst)))
        return real(src, dst)

    monkeypatch.setattr(budget.os, "replace", spy)
    asyncio.run(budget.record("issues"))
    assert seen and seen[0][1] == "budget.json" and seen[0][0].startswith("budget.json.")
