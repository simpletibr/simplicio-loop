"""Parte de #1601: the watcher-mode makespan of 1, 2 and 3 items of ONE repo, real tick, fake runner (a 0.4 s turbo each).

Parallel items finish in about the time of the slowest one. The serial sum is what one-item-per-repo costs. Run with -s for the table.
"""
from __future__ import annotations

import pytest

from .fakes import FakeRun, baseline, issue, run_tick
from .test_tick_parallel import REPO, body, pinned


@pytest.mark.parametrize("items", [1, 2, 3])
def test_items_of_one_repo_finish_in_about_the_slowest_one(env, monkeypatch, items):
    pinned(monkeypatch, 3)
    fake = env(FakeRun({REPO: [issue(i, body=body(f"f{i}.py")) for i in range(1, items + 1)]}, diff=False, delay=0.4, meet=1))
    baseline()
    run_tick()
    spans = fake.turbo_spans
    makespan = max(end for _, end in spans) - min(start for start, _ in spans)
    serial = sum(end - start for start, end in spans)
    print(f"\nMEASURE items={items} max_concurrent={fake.max_turbo} makespan={makespan:.2f}s serial_sum={serial:.2f}s")
    assert fake.max_turbo == items
    slowest = max(end - start for start, end in spans)
    assert makespan < slowest * 1.5, f"makespan {makespan:.2f}s vs slowest turbo {slowest:.2f}s (serial sum {serial:.2f}s)"
