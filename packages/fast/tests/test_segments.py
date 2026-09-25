from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simplicio_fast.segments import (
    SegmentStore,
    SegmentStoreError,
    SemanticSegmentPager,
    SemanticSegmentPagerError,
    migrate_snapshot,
)
from simplicio_fast.snapshot import Snapshot, build_snapshot


class SegmentStoreTest(unittest.TestCase):
    def test_publish_is_atomic_and_reads_exact_snapshot_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "class Service:\n    def run(self):\n        return True\n",
                encoding="utf-8",
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            payload = migrate_snapshot(snapshot, store.directory)
            self.assertEqual("simplicio.fast.segments/v1", payload["schema"])
            self.assertEqual("valid", store.validate()["status"])
            with Snapshot(snapshot) as opened:
                for name in opened._sections:
                    self.assertEqual(opened._section_bytes(name), store.read(name))

    def test_manifest_metadata_fails_closed_before_segment_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            store.publish(snapshot)
            manifest = store.read_manifest()
            manifest["generation"] = ""
            store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(SegmentStoreError, "manifest_metadata_invalid"):
                store.read_manifest()

    def test_invalid_segment_entry_bounds_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            store.publish(snapshot)
            manifest = store.read_manifest()
            manifest["segments"][0]["bytes"] = -1
            store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(SegmentStoreError, "segment_entry_invalid"):
                store.validate()

    def test_corruption_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            store.publish(snapshot)
            entry = store.read_manifest()["segments"][0]
            path = store.directory / entry["file"]
            path.write_bytes(path.read_bytes() + b"tamper")
            with self.assertRaisesRegex(SegmentStoreError, "checksum_mismatch"):
                store.validate()

    def test_second_publish_reuses_content_addressed_segments_and_swaps_generation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text("def run():\n    return True\n", encoding="utf-8")
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            first = store.publish(snapshot)
            self.assertEqual(len(first["segments"]), first["segments_written"])
            self.assertEqual(0, first["segments_reused"])
            source.write_text("def run():\n    return False\n", encoding="utf-8")
            build_snapshot(root, snapshot)
            second = store.publish(snapshot)
            self.assertNotEqual(first["generation"], second["generation"])
            self.assertEqual("valid", store.validate()["status"])
            self.assertGreaterEqual(second["segments_reused"], 1)

    def test_existing_content_addressed_segment_corruption_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            store.publish(snapshot)
            entry = store.read_manifest()["segments"][0]
            path = store.directory / entry["file"]
            path.write_bytes(b"corrupt")
            with self.assertRaisesRegex(
                SegmentStoreError, "existing_checksum_mismatch"
            ):
                store.publish(snapshot)

    def test_recover_previous_restores_last_manifest_after_pointer_corruption(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text("def run():\n    return True\n", encoding="utf-8")
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            first = store.publish(snapshot)
            source.write_text("def run():\n    return False\n", encoding="utf-8")
            build_snapshot(root, snapshot)
            second = store.publish(snapshot)
            self.assertNotEqual(first["generation"], second["generation"])

            store.manifest_path.write_text("{", encoding="utf-8")
            recovered = store.recover_previous()
            self.assertEqual(first["generation"], recovered["generation"])
            self.assertEqual(first["generation"], store.read_manifest()["generation"])
            self.assertEqual("valid", store.validate()["status"])

    def test_read_range_enforces_a_bounded_segment_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            store.publish(snapshot)
            expected = store.read("symbols")
            self.assertEqual(expected[1:9], store.read_range("symbols", 1, 8))
            with self.assertRaisesRegex(SegmentStoreError, "segment_range_invalid"):
                store.read_range("symbols", -1, 8)
            with self.assertRaisesRegex(
                SegmentStoreError, "segment_range_out_of_bounds"
            ):
                store.read_range("symbols", len(expected) - 2, 8)

    def test_map_validates_and_reads_one_segment_without_snapshot_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            store.publish(snapshot)
            with Snapshot(snapshot) as opened:
                with store.map("symbols") as mapped:
                    self.assertEqual(opened._section_bytes("symbols"), bytes(mapped))

    def test_semantic_segment_pager_reads_aligned_windows_and_reuses_pages(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            manifest = store.publish(snapshot)
            reader = SemanticSegmentPager(
                store,
                "repo",
                manifest["generation"],
                page_bytes=16,
                max_bytes=32,
                max_pages=4,
            )
            expected = store.read("symbols")
            first = reader.read("symbols", 3, 24)
            second = reader.read("symbols", 3, 24)
            self.assertEqual(expected[3:27], first)
            self.assertEqual(first, second)
            stats = reader.stats()
            self.assertEqual(2, stats["segment_reads"])
            self.assertEqual(2, stats["misses"])
            self.assertGreaterEqual(stats["hits"], 2)

    def test_semantic_segment_pager_fails_closed_on_bounds_and_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            manifest = store.publish(snapshot)
            reader = SemanticSegmentPager(
                store, "repo", manifest["generation"], page_bytes=8
            )
            with self.assertRaises(SemanticSegmentPagerError) as error:
                reader.read("symbols", -1, 1)
            self.assertEqual("segment_range_invalid", error.exception.reason_code)
            with self.assertRaises(SemanticSegmentPagerError) as error:
                reader.read("symbols", 0, 10**9)
            self.assertEqual("segment_range_out_of_bounds", error.exception.reason_code)
            stale = SemanticSegmentPager(store, "repo", "stale-generation")
            with self.assertRaises(SemanticSegmentPagerError) as error:
                stale.read("symbols", 0, 1)
            self.assertEqual("stale_generation", error.exception.reason_code)

    def test_manifest_rejects_duplicate_segment_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            store.publish(snapshot)
            manifest = store.read_manifest()
            manifest["segments"].append(dict(manifest["segments"][0]))
            store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(SegmentStoreError, "manifest_segments_invalid"):
                store.read_manifest()

    def test_manifest_rejects_empty_segment_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            store = SegmentStore(root / "segments")
            store.publish(snapshot)
            manifest = store.read_manifest()
            manifest["segments"] = []
            store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(SegmentStoreError, "manifest_segments_invalid"):
                store.read_manifest()
