from __future__ import annotations

import multiprocessing
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from simplicio_fast.hbp_codec import verify_chain
from simplicio_fast.prism_arena import (
    HEADER,
    MAGIC,
    RECORD,
    ArenaError,
    PrismArena,
    PrismWorkDelta,
    _decode_catalog,
    encode_base,
)


FILES = {
    "src/a.py": b"def a():\n    return 1\n",
    "src/b.py": b"def b():\n    return 2\n",
}


def _process_overlay(
    storage: str, repo: str, generation: str, task: str, queue: object
) -> None:
    arena = PrismArena(storage, repo, generation, expected_source_hash="source-1")
    slot = arena.open_slot(
        f"slot-{task}", "prism", fence=f"f-{task}", max_overlay_bytes=1024
    )
    overlay = arena.create_overlay(slot, task, 1, f"wt-{task}", fence=f"f-{task}")
    arena.apply_delta(
        slot,
        overlay,
        PrismWorkDelta(writes={"src/a.py": task.encode()}),
    )
    queue.put(
        {
            "handle": arena.base_handle_id,
            "value": arena.read(slot, overlay, "src/a.py"),
            "base": arena.base_read(slot, "src/a.py"),
            "receipt": arena.receipts()[-1].event_hash,
        }
    )
    arena.close()


class PrismArenaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = Path(self.temporary.name) / "arena"
        self.arena = PrismArena.publish(self.storage, "org/repo", "source-1", FILES)

    def tearDown(self) -> None:
        self.arena.close()
        self.temporary.cleanup()

    def slot(self, name: str = "slot-1", fence: str = "f1"):
        return self.arena.open_slot(name, "prism", fence=fence)

    def overlay(self, slot, task: str = "task-1", attempt: int = 1):
        return self.arena.create_overlay(
            slot, task, attempt, f"wt-{task}", fence=slot.fence
        )

    def test_base_is_one_shared_mmap_handle_for_generation(self) -> None:
        other = PrismArena(
            self.storage,
            "org/repo",
            self.arena.generation,
            expected_source_hash="source-1",
        )
        try:
            self.assertEqual(self.arena.base_handle_id, other.base_handle_id)
            self.assertEqual(2, other.metrics()["base_refcount"])
            self.assertGreaterEqual(other.metrics()["base_reuse_count"], 1)
        finally:
            other.close()

    def test_ten_overlays_are_independent_and_eleventh_fails(self) -> None:
        slot = self.slot()
        overlays = []
        for index in range(10):
            overlay = self.overlay(slot, f"task-{index}")
            self.arena.apply_delta(
                slot,
                overlay,
                PrismWorkDelta(writes={"src/a.py": str(index).encode()}),
            )
            overlays.append(overlay)
        self.assertEqual(
            [str(index).encode() for index in range(10)],
            [self.arena.read(slot, overlay, "src/a.py") for overlay in overlays],
        )
        with self.assertRaises(ArenaError) as caught:
            self.overlay(slot, "task-10")
        self.assertEqual("overlay_limit_exceeded", caught.exception.reason_code)

    def test_same_file_in_two_overlays_never_leaks(self) -> None:
        slot = self.slot()
        first = self.overlay(slot, "task-a")
        second = self.overlay(slot, "task-b")
        self.arena.apply_delta(slot, first, PrismWorkDelta(writes={"src/a.py": b"A"}))
        self.arena.apply_delta(slot, second, PrismWorkDelta(writes={"src/a.py": b"B"}))
        self.assertEqual(b"A", self.arena.read(slot, first, "src/a.py"))
        self.assertEqual(b"B", self.arena.read(slot, second, "src/a.py"))
        self.assertEqual(FILES["src/a.py"], self.arena.base_read(slot, "src/a.py"))

    def test_delete_and_rename_are_overlay_only(self) -> None:
        slot = self.slot()
        overlay = self.overlay(slot)
        self.arena.apply_delta(
            slot,
            overlay,
            PrismWorkDelta(
                deletes=("src/b.py",), renames={"src/a.py": "src/renamed.py"}
            ),
        )
        self.assertIsNone(self.arena.read(slot, overlay, "src/a.py"))
        self.assertIsNone(self.arena.read(slot, overlay, "src/b.py"))
        self.assertEqual(
            FILES["src/a.py"],
            self.arena.read(slot, overlay, "src/renamed.py"),
        )
        self.assertEqual(FILES["src/a.py"], self.arena.base_read(slot, "src/a.py"))

    def test_child_slot_reuses_handle_not_copy(self) -> None:
        parent = self.slot("parent")
        child = self.arena.open_slot(
            "child", "child-prism", fence="child-f", parent=parent
        )
        self.assertEqual(parent.base_handle_id, child.base_handle_id)
        self.assertEqual((child,), self.arena.child_slots(parent))

    def test_refresh_keeps_old_generation_readable_until_close(self) -> None:
        slot = self.slot()
        refreshed = self.arena.refresh(
            "source-2", {**FILES, "src/c.py": b"def c(): pass\n"}
        )
        try:
            new_slot = refreshed.open_slot("new", "prism", fence="new-f")
            self.assertNotEqual(self.arena.generation, refreshed.generation)
            self.assertEqual(FILES["src/a.py"], self.arena.base_read(slot, "src/a.py"))
            self.assertEqual(
                b"def c(): pass\n", refreshed.base_read(new_slot, "src/c.py")
            )
            self.assertTrue(self.arena.metrics()["draining"])
            self.assertEqual(1, self.arena.active_readers)
        finally:
            refreshed.close()

    def test_source_drift_has_explicit_source_scan_fallback(self) -> None:
        with self.assertRaises(ArenaError) as caught:
            PrismArena(
                self.storage,
                "org/repo",
                self.arena.generation,
                expected_source_hash="different",
            )
        self.assertEqual("source_stale", caught.exception.reason_code)
        self.assertEqual("source_scan", caught.exception.receipt()["fallback"])

    def test_corrupt_and_truncated_snapshots_fail_closed(self) -> None:
        self.arena.close()
        data = self.arena.base_path.read_bytes()
        self.arena.base_path.write_bytes(data[:-1])
        with self.assertRaises(ArenaError) as truncated:
            PrismArena(self.storage, "org/repo", self.arena.generation)
        self.assertEqual("snapshot_corrupt", truncated.exception.reason_code)
        self.arena.base_path.write_bytes(b"X" * len(data))
        with self.assertRaises(ArenaError) as corrupt:
            PrismArena(self.storage, "org/repo", self.arena.generation)
        self.assertEqual("snapshot_corrupt", corrupt.exception.reason_code)

    def test_crashed_writer_temporary_file_is_never_published(self) -> None:
        leftover = self.arena.generation_dir / ".base.sfa.crashed.tmp"
        leftover.write_bytes(b"partial")
        opened = PrismArena.open_current(
            self.storage, "org/repo", expected_source_hash="source-1"
        )
        try:
            slot = opened.open_slot("reader", "prism", fence="reader-f")
            self.assertEqual(FILES["src/a.py"], opened.base_read(slot, "src/a.py"))
        finally:
            opened.close()

    def test_cleanup_removes_only_abandoned_overlay(self) -> None:
        slot = self.slot()
        overlay = self.overlay(slot)
        self.arena.close_overlay(slot, overlay)
        dry = self.arena.cleanup_abandoned(apply=False)
        self.assertEqual([overlay.overlay_id], dry["candidates"])
        self.assertTrue(self.arena.base_path.exists())
        result = self.arena.cleanup_abandoned(apply=True)
        self.assertEqual([overlay.overlay_id], result["removed"])
        self.assertTrue(self.arena.base_path.exists())

    def test_hbp_is_internal_persistence_and_json_is_export_only(self) -> None:
        slot = self.slot()
        overlay = self.overlay(slot)
        self.arena.apply_delta(
            slot, overlay, PrismWorkDelta(writes={"src/a.py": b"changed"})
        )
        rows = [receipt.hbp_row for receipt in self.arena.receipts()]
        self.assertEqual(self.arena.receipts()[-1].event_hash, verify_chain(rows))
        self.assertFalse(list(self.storage.rglob("*.json")))
        exported = self.arena.export_receipts()
        self.assertEqual(
            "simplicio.fast.prism-arena-receipt/v1", exported[-1]["schema"]
        )

    def test_overlay_budget_is_enforced_before_publication(self) -> None:
        slot = self.arena.open_slot(
            "bounded",
            "prism",
            fence="bounded-f",
            max_overlay_bytes=3,
            max_overlay_files=1,
        )
        overlay = self.overlay(slot, "bounded-task")
        with self.assertRaises(ArenaError) as bytes_error:
            self.arena.apply_delta(slot, overlay, PrismWorkDelta(writes={"x": b"four"}))
        self.assertEqual(
            "overlay_byte_budget_exceeded", bytes_error.exception.reason_code
        )
        self.arena.apply_delta(slot, overlay, PrismWorkDelta(writes={"x": b"one"}))
        with self.assertRaises(ArenaError) as files_error:
            self.arena.apply_delta(slot, overlay, PrismWorkDelta(writes={"y": b"two"}))
        self.assertEqual(
            "overlay_file_budget_exceeded", files_error.exception.reason_code
        )

    def test_stale_fence_and_expired_lease_are_rejected(self) -> None:
        slot = self.slot()
        with self.assertRaises(ArenaError) as fence:
            self.arena.create_overlay(slot, "task", 1, "wt-task", fence="old-fence")
        self.assertEqual("fence_stale", fence.exception.reason_code)
        self.arena._leases[slot.lease_id].expires_at = 0
        with self.assertRaises(ArenaError) as lease:
            self.arena.base_read(slot, "src/a.py")
        self.assertEqual("lease_stale", lease.exception.reason_code)

    def test_invalid_paths_and_contents_are_rejected(self) -> None:
        with self.assertRaises(ArenaError):
            encode_base({"../escape": b"x"})
        with self.assertRaises(ArenaError):
            encode_base({"x": "not-bytes"})  # type: ignore[dict-item]
        with self.assertRaises(ArenaError):
            encode_base({("x" * 65536): b"x"})
        slot = self.slot()
        overlay = self.overlay(slot)
        with self.assertRaises(ArenaError):
            self.arena.apply_delta(
                slot, overlay, PrismWorkDelta(writes={"/escape": b"x"})
            )
        with self.assertRaises(ArenaError):
            self.arena.apply_delta(
                slot, overlay, PrismWorkDelta(renames={"missing": "new"})
            )
        with self.assertRaises(ArenaError) as content:
            self.arena.apply_delta(
                slot,
                overlay,
                PrismWorkDelta(writes={"x": "not-bytes"}),  # type: ignore[dict-item]
            )
        self.assertEqual("overlay_content_invalid", content.exception.reason_code)

    def test_binary_decoder_rejects_every_structural_corruption_class(self) -> None:
        empty_hash = __import__("hashlib").sha256(b"").digest()

        def record(path: bytes, content: bytes = b"", digest: bytes = empty_hash):
            return RECORD.pack(len(path), len(content)) + path + digest + content

        blobs = [
            b"",
            HEADER.pack(b"WRONG!!!", 0),
            HEADER.pack(MAGIC, 1),
            HEADER.pack(MAGIC, 1) + RECORD.pack(1, 5) + b"x",
            HEADER.pack(MAGIC, 1) + record(b"\xff"),
            HEADER.pack(MAGIC, 2) + record(b"x") + record(b"x"),
            HEADER.pack(MAGIC, 1) + record(b"x", b"value", b"0" * 32),
            encode_base({"x": b"value"}) + b"trailing",
        ]
        for blob in blobs:
            with self.subTest(size=len(blob)):
                with self.assertRaises(ArenaError):
                    _decode_catalog(blob)  # type: ignore[arg-type]

    def test_identity_limits_cross_arena_and_fence_guards(self) -> None:
        with self.assertRaises(ArenaError) as identity:
            self.arena.open_slot("../slot", "prism", fence="f")
        self.assertEqual("identity_invalid", identity.exception.reason_code)
        with self.assertRaises(ArenaError) as limits:
            self.arena.open_slot("slot", "prism", fence="", ttl_seconds=0)
        self.assertEqual("slot_limits_invalid", limits.exception.reason_code)
        slot = self.slot()
        with self.assertRaises(ArenaError) as duplicate:
            self.arena.open_slot("slot-1", "prism", fence="different")
        self.assertEqual("fence_stale", duplicate.exception.reason_code)
        with self.assertRaises(ArenaError) as ttl:
            self.arena.renew_slot(slot, 0)
        self.assertEqual("lease_ttl_invalid", ttl.exception.reason_code)
        stale = replace(slot, arena_id="different")
        with self.assertRaises(ArenaError) as generation:
            self.arena.base_read(stale, "src/a.py")
        self.assertEqual("slot_generation_stale", generation.exception.reason_code)

    def test_missing_metadata_current_and_base_have_distinct_reason_codes(self) -> None:
        with self.assertRaises(ArenaError) as metadata:
            PrismArena(self.storage, "org/repo", "0" * 64)
        self.assertEqual("snapshot_metadata_corrupt", metadata.exception.reason_code)
        with self.assertRaises(ArenaError) as current:
            PrismArena.open_current(Path(self.temporary.name) / "missing", "org/repo")
        self.assertEqual("current_generation_corrupt", current.exception.reason_code)
        self.arena.close()
        data = self.arena.base_path.read_bytes()
        self.arena.base_path.unlink()
        with self.assertRaises(ArenaError) as missing:
            PrismArena(self.storage, "org/repo", self.arena.generation)
        self.assertEqual("snapshot_missing", missing.exception.reason_code)
        self.arena.base_path.write_bytes(data)

    def test_republish_is_idempotent_and_new_source_gets_new_generation(self) -> None:
        other = PrismArena.publish(
            self.storage, "org/repo", "source-1", dict(reversed(list(FILES.items())))
        )
        try:
            self.assertEqual(self.arena.generation, other.generation)
        finally:
            other.close()
        refreshed = PrismArena.publish(self.storage, "org/repo", "source-other", FILES)
        try:
            self.assertNotEqual(self.arena.generation, refreshed.generation)
            self.assertEqual(self.arena.base_hash, refreshed.base_hash)
        finally:
            refreshed.close()

    def test_closed_overlay_missing_object_and_closed_arena_fail_closed(self) -> None:
        slot = self.slot()
        overlay = self.overlay(slot)
        self.arena.apply_delta(
            slot, overlay, PrismWorkDelta(writes={"src/a.py": b"changed"})
        )
        object_hash = str(overlay.records["src/a.py"])
        (overlay.path / "objects" / object_hash).unlink()
        with self.assertRaises(ArenaError) as missing:
            self.arena.read(slot, overlay, "src/a.py")
        self.assertEqual("overlay_corrupt", missing.exception.reason_code)
        self.arena.close_overlay(slot, overlay)
        with self.assertRaises(ArenaError) as stale:
            self.arena.read(slot, overlay, "src/a.py")
        self.assertEqual("overlay_stale", stale.exception.reason_code)
        self.arena.close()
        with self.assertRaises(ArenaError) as closed:
            self.arena.metrics()
        self.assertEqual("arena_closed", closed.exception.reason_code)

    def test_context_manager_closes_handle_and_double_close_is_safe(self) -> None:
        with PrismArena(self.storage, "org/repo", self.arena.generation) as opened:
            self.assertEqual(self.arena.base_handle_id, opened.base_handle_id)
        opened.close()

    def test_overlay_object_corruption_is_detected(self) -> None:
        slot = self.slot()
        overlay = self.overlay(slot)
        self.arena.apply_delta(
            slot, overlay, PrismWorkDelta(writes={"src/a.py": b"changed"})
        )
        object_hash = overlay.records["src/a.py"]
        self.assertIsNotNone(object_hash)
        (overlay.path / "objects" / str(object_hash)).write_bytes(b"corrupt")
        with self.assertRaises(ArenaError) as caught:
            self.arena.read(slot, overlay, "src/a.py")
        self.assertEqual("overlay_corrupt", caught.exception.reason_code)

    def test_delta_updates_only_affected_records_and_dirty_spans(self) -> None:
        slot = self.slot()
        overlay = self.overlay(slot)
        self.arena.apply_delta(
            slot,
            overlay,
            PrismWorkDelta(
                writes={"src/a.py": b"changed"},
                dirty_spans={"src/a.py": ((1, 2),)},
            ),
        )
        self.assertEqual({"src/a.py"}, set(overlay.records))
        self.assertEqual(((1, 2),), overlay.dirty_spans["src/a.py"])
        self.assertEqual(FILES["src/b.py"], self.arena.read(slot, overlay, "src/b.py"))

    def test_idempotent_open_slot_and_overlay_do_not_duplicate(self) -> None:
        slot = self.slot()
        self.assertIs(slot, self.slot())
        overlay = self.overlay(slot)
        self.assertIs(overlay, self.overlay(slot))
        self.assertEqual(1, self.arena.metrics()["active_overlays"])

    def test_release_and_renew_lifecycle(self) -> None:
        slot = self.slot()
        renewed = self.arena.renew_slot(slot, ttl_seconds=10)
        self.assertGreater(renewed.expires_at, time.time())
        overlay = self.overlay(slot)
        self.arena.release_slot(slot)
        self.assertFalse(overlay.active)
        with self.assertRaises(ArenaError):
            self.arena.base_read(slot, "src/a.py")

    def test_metrics_report_pages_cache_rss_io_and_reuse(self) -> None:
        slot = self.slot()
        overlay = self.overlay(slot)
        self.assertEqual(FILES["src/a.py"], self.arena.base_read(slot, "src/a.py"))
        self.assertIsNone(self.arena.base_read(slot, "missing"))
        self.arena.apply_delta(
            slot, overlay, PrismWorkDelta(writes={"src/a.py": b"changed"})
        )
        self.assertEqual(b"changed", self.arena.read(slot, overlay, "src/a.py"))
        metric = self.arena.metrics()
        self.assertGreaterEqual(metric["pages"]["read"], 1)
        self.assertEqual(1, metric["cache"]["base_hits"])
        self.assertEqual(1, metric["cache"]["overlay_hits"])
        self.assertEqual(1, metric["cache"]["misses"])
        self.assertGreater(metric["rss_kib"], 0)
        self.assertGreater(metric["io"]["read_bytes"], 0)
        self.assertEqual(7, metric["io"]["write_bytes"])

    def test_multiprocess_multiworktree_isolation_and_shared_file_identity(
        self,
    ) -> None:
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        workers = [
            context.Process(
                target=_process_overlay,
                args=(
                    str(self.storage),
                    "org/repo",
                    self.arena.generation,
                    task,
                    queue,
                ),
            )
            for task in ("a", "b")
        ]
        for worker in workers:
            worker.start()
        results = [queue.get(timeout=15) for _ in workers]
        for worker in workers:
            worker.join(timeout=15)
            self.assertEqual(0, worker.exitcode)
        self.assertEqual({b"a", b"b"}, {result["value"] for result in results})
        self.assertEqual({FILES["src/a.py"]}, {result["base"] for result in results})
        self.assertEqual(
            {self.arena.base_handle_id}, {result["handle"] for result in results}
        )
        self.assertTrue(all(len(result["receipt"]) == 64 for result in results))

    def test_base_encoding_is_deterministic_and_base_never_changes(self) -> None:
        before = self.arena.base_path.read_bytes()
        self.assertEqual(
            encode_base(FILES), encode_base(dict(reversed(list(FILES.items()))))
        )
        slot = self.slot()
        for index in range(10):
            overlay = self.overlay(slot, f"property-{index}")
            self.arena.apply_delta(
                slot,
                overlay,
                PrismWorkDelta(writes={"src/a.py": os.urandom(index + 1)}),
            )
        self.assertEqual(before, self.arena.base_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
