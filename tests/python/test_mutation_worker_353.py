from concurrent.futures import ThreadPoolExecutor

import pytest

from simplicio.mutation_worker import MutationBlocked, MutationWorker


def plan(root=None, key="k"):
    return {
        "schema": "simplicio.mechanical-plan/v1",
        "plan_id": "p",
        "source_hash": "s",
        "idempotency_key": key,
        "effect_set": ["write"],
        "operations": [{"path": "app.py"}],
        "hookwall_pre": {"verdict": "proceed", "plan_id": "p"},
    }


def test_receipt_retry_and_concurrency(tmp_path):
    worker = MutationWorker(tmp_path)
    calls = []

    def effect(_):
        calls.append(1)
        return {"status": "ok", "applied": True, "before_hash": "a", "after_hash": "b"}

    receipt = worker.execute(plan(tmp_path), effect)
    assert worker.execute(plan(tmp_path), effect) == receipt
    assert len(calls) == 1 and receipt["receipt_hash"]


def test_crash_path_and_hookwall_fail_closed(tmp_path):
    worker = MutationWorker(tmp_path)
    with pytest.raises(RuntimeError):
        worker.execute(plan(tmp_path), lambda _: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(MutationBlocked, match="RECOVERY_REQUIRED"):
        worker.execute(plan(tmp_path), lambda _: {})
    bad = plan(tmp_path, "bad")
    bad["operations"][0]["path"] = "../escape"
    with pytest.raises(MutationBlocked, match="PATH_ESCAPE"):
        worker.execute(bad, lambda _: {})
    blocked = plan(tmp_path, "blocked")
    blocked["hookwall_pre"]["verdict"] = "block"
    with pytest.raises(MutationBlocked):
        worker.execute(blocked, lambda _: {})


def test_twenty_duplicate_writers_execute_once(tmp_path):
    worker = MutationWorker(tmp_path)
    calls = []

    def run():
        try:
            return worker.execute(
                plan(tmp_path),
                lambda _: (
                    calls.append(1)
                    or {"status": "ok", "applied": True, "before_hash": "a", "after_hash": "b"}
                ),
            )
        except MutationBlocked:
            return None

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(lambda _: run(), range(20)))
    assert len(calls) == 1
