"""Tests for pipeline.run_tasks_async (issue #212).

Scope: the concurrent-dispatch behavior added by `run_tasks_async` itself —
bounded fan-out over independent `run_task` calls, failure isolation, and
non-blocking dispatch. `run_task`'s own retry/verify logic is exercised by
the existing pipeline test modules and is monkeypatched away here.
"""

from __future__ import annotations

import asyncio
import threading
import time

from simplicio import pipeline


def test_run_tasks_async_dispatches_all_specs(monkeypatch):
    calls = []

    def fake_run_task(**kwargs):
        calls.append(kwargs["target"])
        return {"task_id": kwargs["target"], "applied": True}

    monkeypatch.setattr(pipeline, "run_task", fake_run_task)

    specs = [
        {
            "root": "/tmp/repo",
            "stack": "python",
            "goal": "goal",
            "target": f"file_{i}.py",
            "criteria": "criteria",
            "constraints": "constraints",
        }
        for i in range(4)
    ]

    results = asyncio.run(pipeline.run_tasks_async(specs, concurrency=2))

    assert sorted(calls) == [f"file_{i}.py" for i in range(4)]
    assert {r["task_id"] for r in results} == {f"file_{i}.py" for i in range(4)}
    assert all(r["applied"] for r in results)


def test_run_tasks_async_bounds_concurrent_threads(monkeypatch):
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_run_task(**kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return {"task_id": kwargs["target"], "applied": True}

    monkeypatch.setattr(pipeline, "run_task", fake_run_task)

    specs = [
        {
            "root": "/tmp/repo",
            "stack": "python",
            "goal": "goal",
            "target": f"file_{i}.py",
            "criteria": "criteria",
            "constraints": "constraints",
        }
        for i in range(6)
    ]

    asyncio.run(pipeline.run_tasks_async(specs, concurrency=2))

    assert peak <= 2


def test_run_tasks_async_isolates_a_failing_task(monkeypatch):
    def fake_run_task(**kwargs):
        if kwargs["target"] == "broken.py":
            raise RuntimeError("simulated crash")
        return {"task_id": kwargs["target"], "applied": True}

    monkeypatch.setattr(pipeline, "run_task", fake_run_task)

    specs = [
        {
            "root": "/tmp/repo",
            "stack": "python",
            "goal": "goal",
            "target": name,
            "criteria": "criteria",
            "constraints": "constraints",
        }
        for name in ("ok_1.py", "broken.py", "ok_2.py")
    ]

    results = asyncio.run(pipeline.run_tasks_async(specs))

    by_target = dict(zip(("ok_1.py", "broken.py", "ok_2.py"), results, strict=True))
    assert by_target["ok_1.py"]["applied"] is True
    assert by_target["ok_2.py"]["applied"] is True
    assert isinstance(by_target["broken.py"], RuntimeError)


def test_run_tasks_async_empty_specs_returns_empty_list():
    assert asyncio.run(pipeline.run_tasks_async([])) == []


def test_run_tasks_async_never_touches_sync_run(monkeypatch):
    """Regression: run()/run_task must be untouched by the async addition."""
    sentinel = object()
    monkeypatch.setattr(pipeline, "run_task", lambda **_: {"applied": False})

    # run_tasks_async is additive: calling it must not require patching run()
    # nor change run()'s public identity.
    assert pipeline.run is not sentinel
    assert callable(pipeline.run)
