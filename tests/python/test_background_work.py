"""Durable background worker tests for issue #408."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from simplicio_mapper import background_work
from simplicio_mapper.background_work import (
    BACKGROUND_SCHEMA,
    BackgroundQueue,
    BackgroundWorkError,
    run_background_cli,
    run_worker,
    validate_candidate,
)


class BackgroundWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        (self.root / "src").mkdir()
        for name in ("one.py", "two.py", "three.py"):
            (self.root / "src" / name).write_text(f"print('{name}')\n", encoding="utf-8")
        self.cache = Path(self.temp.name) / "cache"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def payload(self, task: str = "task") -> dict:
        return {
            "generation_id": "a" * 64,
            "generation_inputs": {
                "tree": "",
                "revision": "",
                "scope": ".",
                "targets": ["src/one.py"],
                "task": task,
                "config": "cfg",
                "mapper_version": "0.26.2",
            },
            "repository": {"root": str(self.root)},
        }

    def test_dedup_and_queue_receipt(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        first = queue.enqueue(self.payload(), start=False)
        second = queue.enqueue(self.payload(), start=False)
        self.assertEqual(first["work_id"], second["work_id"])
        self.assertEqual(first["dedup_key"], second["dedup_key"])
        self.assertEqual(BACKGROUND_SCHEMA, first["schema"])
        self.assertTrue(queue.queue_log.is_file())
        self.assertTrue(queue.events.is_file())

    def test_lease_heartbeat_fence_and_reclaim(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        item = queue.enqueue(self.payload("lease"), start=False)
        claimed = queue.claim(item["work_id"], lease_seconds=0.01)
        self.assertIsNotNone(claimed)
        with self.assertRaises(BackgroundWorkError):
            queue.heartbeat(item["work_id"], "bad-token")
        time.sleep(0.03)
        self.assertEqual(1, queue.doctor()["recovered_leases"])
        self.assertEqual("queued", queue.status(item["work_id"])["state"])

    def test_checkpoint_resume_and_atomic_promotion(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        item = queue.enqueue(self.payload("resume"), start=False)
        self.assertEqual(75, run_worker(item["work_id"], self.cache, lease_seconds=2.0, chunk_size=1, stop_after_chunks=1))
        checkpoint = json.loads(queue._checkpoint(item["work_id"]).read_text(encoding="utf-8"))
        self.assertEqual(1, checkpoint["cursor"])
        time.sleep(2.1)
        self.assertEqual(0, run_worker(item["work_id"], self.cache, chunk_size=1))
        self.assertEqual("promoted", queue.status(item["work_id"])["state"])
        self.assertEqual("atomic", queue.status(item["work_id"])["metrics"]["promotion"])

    def test_cancel_prevents_promotion(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        item = queue.enqueue(self.payload("cancel"), start=False)
        queue.cancel(item["work_id"])
        self.assertEqual("cancelled", queue.status(item["work_id"])["state"])
        self.assertEqual(0, run_worker(item["work_id"], self.cache))
        self.assertFalse(queue.promotion.exists())

    def test_candidate_validation_is_fail_closed(self) -> None:
        candidate = {"schema": BACKGROUND_SCHEMA, "work_id": "w", "complete": True, "records": [{"path": "b"}, {"path": "a"}], "records_digest": "0" * 64, "scanned_count": 2}
        with self.assertRaises(BackgroundWorkError):
            validate_candidate(candidate, "w")

    def test_promotion_retains_rollback_and_gc_respects_pin(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        first = queue.enqueue(self.payload("first"), start=False)
        self.assertEqual(0, run_worker(first["work_id"], self.cache, chunk_size=1))
        old = queue.status(first["work_id"])["candidate_generation_id"]
        newer = self.payload("second")
        newer["generation_id"] = "b" * 64
        second = queue.enqueue(newer, start=False)
        self.assertEqual(0, run_worker(second["work_id"], self.cache, chunk_size=1))
        self.assertIn(old, queue.status(second["work_id"])["metrics"]["rollback_retained"])
        pin = self.cache / queue.repo_key / "pins" / "attempt.json"
        pin.parent.mkdir(parents=True, exist_ok=True)
        pin.write_text(json.dumps({"generation_id": old}), encoding="utf-8")
        self.assertIn(old, queue.gc(0)["retained_generation_ids"])

    def test_five_concurrent_enqueue_requests_deduplicate(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        for _trial in range(5):
            results: list[dict] = []
            threads = [
                threading.Thread(target=lambda: results.append(queue.enqueue(self.payload("same"), start=False)))
                for _ in range(5)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(1, len({result["work_id"] for result in results}))

    def test_cli_json_status_cancel_doctor(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        item = queue.enqueue(self.payload("cli"), start=False)
        for command in (
            ["status", str(self.root), "--work-id", item["work_id"], "--cache-root", str(self.cache), "--json"],
            ["cancel", str(self.root), "--work-id", item["work_id"], "--cache-root", str(self.cache), "--json"],
            ["doctor", str(self.root), "--cache-root", str(self.cache), "--json"],
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, run_background_cli(command))
            self.assertEqual(BACKGROUND_SCHEMA, json.loads(output.getvalue())["schema"])

    def test_null_metrics_have_reason_code(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        item = queue.enqueue(self.payload("metrics"), start=False)
        self.assertEqual(0, run_worker(item["work_id"], self.cache, chunk_size=1))
        metrics = queue.status(item["work_id"])["metrics"]
        self.assertIsNone(metrics["rss_bytes"])
        self.assertEqual("RSS_METRIC_UNAVAILABLE", metrics["rss_reason_code"])

    def test_low_level_fail_closed_and_language_paths(self) -> None:
        with self.assertRaises(BackgroundWorkError):
            background_work._read(self.cache / "missing.json")
        invalid = self.cache / "invalid.json"
        invalid.parent.mkdir(parents=True, exist_ok=True)
        invalid.write_text("[]", encoding="utf-8")
        with self.assertRaises(BackgroundWorkError):
            background_work._read(invalid)
        invalid.write_text("not-json", encoding="utf-8")
        with self.assertRaises(BackgroundWorkError):
            background_work._read(invalid)
        self.assertEqual("python", background_work._language("x.py"))
        self.assertEqual("javascript", background_work._language("x.jsx"))
        self.assertEqual("other", background_work._language("x.unknown"))
        with self.assertRaises(BackgroundWorkError):
            background_work._record(self.root, "src")
        self.assertEqual("", background_work._tree(self.root / "missing"))

    def test_invalid_payload_resume_and_terminal_transitions(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        with self.assertRaises(BackgroundWorkError):
            queue.enqueue({}, start=False)
        item = queue.enqueue(self.payload("transitions"), start=False)
        claimed = queue.claim(item["work_id"])
        self.assertIsNotNone(claimed)
        running = queue.cancel(item["work_id"])
        self.assertTrue(running["cancellation"]["requested"])
        queued = queue.resume(item["work_id"], start=False)
        self.assertEqual("queued", queued["state"])
        self.assertEqual("queued", queue.status(item["work_id"])["state"])

    def test_corrupt_listing_doctor_and_unpinned_gc(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        queue.enqueue(self.payload("doctor"), start=False)
        corrupt = queue.root / "bad.json"
        corrupt.write_text("{", encoding="utf-8")
        listing = queue.status()
        self.assertTrue(any(row.get("reason_code") == "CORRUPT_STATE" for row in listing["items"]))
        diagnosis = queue.doctor()
        self.assertFalse(diagnosis["ok"])
        generation = queue.generations / "unretained.json"
        generation.parent.mkdir(parents=True, exist_ok=True)
        generation.write_text("{}", encoding="utf-8")
        self.assertEqual(1, queue.gc(0)["deleted"])

    def test_candidate_promotion_fences_and_retains_active_pointer(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        item = queue.enqueue(self.payload("fence"), start=False)
        claimed = queue.claim(item["work_id"])
        assert claimed is not None
        candidate = {
            "schema": BACKGROUND_SCHEMA,
            "work_id": item["work_id"],
            "generation_id": "c" * 64,
            "records": [],
            "records_digest": background_work._sha([]),
            "scanned_count": 0,
            "complete": True,
        }
        with self.assertRaises(BackgroundWorkError):
            queue.promote(item["work_id"], candidate, "wrong-token")
        promoted = queue.promote(item["work_id"], candidate, claimed["lease"]["token"])
        self.assertEqual("promoted", promoted["state"])
        self.assertEqual("c" * 64, json.loads(queue.promotion.read_text(encoding="utf-8"))["active_generation_id"])

    def test_missing_worker_and_stale_tree_are_fail_closed(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        with self.assertRaises(BackgroundWorkError):
            run_worker("missing", self.cache)
        original_tree = background_work._tree
        background_work._tree = lambda _repo: "unexpected-tree"
        try:
            payload = self.payload("stale")
            payload["generation_inputs"]["tree"] = "expected-tree"
            item = queue.enqueue(payload, start=False)
            self.assertEqual(1, run_worker(item["work_id"], self.cache))
            self.assertEqual("STALE_GIT_TREE", queue.status(item["work_id"])["reason_code"])
        finally:
            background_work._tree = original_tree
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        payload = self.payload("stale-after-scan")
        payload["generation_inputs"]["tree"] = "expected-tree"
        item = queue.enqueue(payload, start=False)
        values = iter(("expected-tree", "changed-after-scan"))
        background_work._tree = lambda _repo: next(values)
        try:
            self.assertEqual(1, run_worker(item["work_id"], self.cache))
            self.assertEqual("STALE_GIT_TREE", queue.status(item["work_id"])["reason_code"])
        finally:
            background_work._tree = original_tree

    def test_start_records_spawn_receipt_without_waiting(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        item = queue.enqueue(self.payload("spawn"), start=False)
        fake_process = type("FakeProcess", (), {"pid": 4321})()
        with patch("simplicio_mapper.background_work.subprocess.Popen", return_value=fake_process):
            started = queue.start(item["work_id"])
        self.assertTrue(started["spawn"]["started"])
        self.assertEqual(4321, started["spawn"]["pid"])
        self.assertEqual("queued", started["state"])

    def test_foreground_status_p95_under_threaded_load(self) -> None:
        queue = BackgroundQueue.for_repo(self.root, self.cache)
        item = queue.enqueue(self.payload("foreground-load"), start=False)
        worker = threading.Thread(target=lambda: run_worker(item["work_id"], self.cache, chunk_size=1))
        worker.start()
        latencies = []
        for _ in range(10):
            began = time.perf_counter()
            queue.status(item["work_id"])
            latencies.append((time.perf_counter() - began) * 1000)
        worker.join(timeout=15)
        self.assertFalse(worker.is_alive())
        p95 = sorted(latencies)[8]
        self.assertLess(p95, 250.0)
        self.assertEqual("promoted", queue.status(item["work_id"])["state"])


if __name__ == "__main__":
    unittest.main()
