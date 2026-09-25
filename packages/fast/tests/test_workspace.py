import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path

from simplicio_fast.adapters import negotiate, parse_path
from simplicio_fast.workspace import GenerationId, StaleSnapshotError, WorkspaceStore


class WorkspaceGenerationTest(unittest.TestCase):
    def test_default_storage_is_inside_simplicio_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = WorkspaceStore(root)
            self.assertEqual((root / ".simplicio" / "fast").resolve(), store.storage)

    def test_generation_and_worktree_ids_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            GenerationId("not-a-digest")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text(
                "def main():\n    return True\n", encoding="utf-8"
            )
            store = WorkspaceStore(root)
            base = store.build_base()
            with self.assertRaises(ValueError):
                store.create_overlay("../other", base.generation_id)

    def test_base_overlay_merge_and_generation_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text(
                "class Service:\n    def base(self):\n        return True\n",
                encoding="utf-8",
            )
            (root / "service.ts").write_text(
                "export class TypeScriptService {}\n", encoding="utf-8"
            )
            store = WorkspaceStore(root)
            base = store.build_base()
            self.assertEqual(base, store.build_base())
            self.assertEqual(64, len(base.generation_id))
            self.assertEqual("base", base.kind)

            source.write_text(
                source.read_text(encoding="utf-8") + "\ndef one():\n    return 1\n",
                encoding="utf-8",
            )
            first = store.create_overlay("slot-one", base.generation_id)
            with store.open(
                base.generation_id,
                worktree_id="slot-one",
                overlay_generation=first.overlay_generation,
            ) as view:
                self.assertEqual("Service.base", view.find("base")[0].qualified_name)
                result = view.find("one")[0]
                self.assertEqual(base.generation_id, result.base_generation)
                self.assertEqual(first.overlay_generation, result.overlay_generation)

            source.write_text(
                source.read_text(encoding="utf-8").replace(
                    "def one():\n    return 1", ""
                ),
                encoding="utf-8",
            )
            source.write_text(
                source.read_text(encoding="utf-8") + "\ndef two():\n    return 2\n",
                encoding="utf-8",
            )
            second = store.create_overlay("slot-two", base.generation_id)
            with store.open(
                base.generation_id,
                worktree_id="slot-one",
                overlay_generation=first.overlay_generation,
            ) as first_view:
                self.assertEqual(1, len(first_view.find("one")))
                self.assertEqual([], first_view.find("two"))
            with store.open(
                base.generation_id,
                worktree_id="slot-two",
                overlay_generation=second.overlay_generation,
            ) as second_view:
                self.assertEqual([], second_view.find("one"))
                self.assertEqual(1, len(second_view.find("two")))

    def test_refresh_validates_previous_overlay_and_records_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text("def one():\n    return 1\n", encoding="utf-8")
            store = WorkspaceStore(root)
            base = store.build_base()
            first = store.refresh("slot", base.generation_id)
            source.write_text(
                "def one():\n    return 1\n\ndef two():\n    return 2\n",
                encoding="utf-8",
            )
            second = store.refresh("slot", base.generation_id, first.overlay_generation)
            self.assertNotEqual(first.overlay_generation, second.overlay_generation)
            with self.assertRaisesRegex(ValueError, "overlay base generation"):
                store.refresh("slot", "0" * 64, first.overlay_generation)
            receipts = sorted(
                (root / ".simplicio" / "fast" / "receipts").glob("*-refresh.json")
            )
            self.assertTrue(receipts)
            self.assertEqual(
                first.overlay_generation,
                json.loads(receipts[-1].read_text())["previous_overlay_generation"],
            )
            receipt_files = list(
                (root / ".simplicio" / "fast" / "receipts").glob("*.json")
            )
            self.assertGreaterEqual(len(receipt_files), 3)

    def test_lease_protects_generation_from_gc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text(
                "def main():\n    return True\n", encoding="utf-8"
            )
            store = WorkspaceStore(root)
            base = store.build_base()
            lease = store.pin(base.generation_id, "test", ttl_seconds=60)
            report = store.gc()
            self.assertIn(base.generation_id, report["protected"])
            self.assertNotIn(base.generation_id, report["candidates"])
            store.release_lease(lease.lease_id)
            report = store.gc()
            self.assertIn(base.generation_id, report["candidates"])
            store.gc(apply=True)
            self.assertFalse(
                (root / ".simplicio" / "fast" / "base" / base.generation_id).exists()
            )

    def test_pinned_context_releases_and_expired_leases_are_collected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text(
                "def main():\n    return True\n", encoding="utf-8"
            )
            store = WorkspaceStore(root)
            base = store.build_base()
            with store.pinned(base.generation_id, "context") as lease:
                self.assertTrue(
                    (
                        root
                        / ".simplicio"
                        / "fast"
                        / "leases"
                        / f"{lease.lease_id}.json"
                    ).exists()
                )
            self.assertFalse(
                (
                    root / ".simplicio" / "fast" / "leases" / f"{lease.lease_id}.json"
                ).exists()
            )
            expired = store.pin(base.generation_id, "expired", ttl_seconds=-1)
            report = store.gc(apply=True)
            self.assertNotIn(base.generation_id, report["protected"])
            self.assertFalse(
                (
                    root / ".simplicio" / "fast" / "leases" / f"{expired.lease_id}.json"
                ).exists()
            )

    def test_context_reports_delivered_range_and_content_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.py"
            source.write_text(
                "def main():\n    return True\n    return False\n",
                encoding="utf-8",
            )
            store = WorkspaceStore(root)
            base = store.build_base()
            with store.open(base.generation_id) as view:
                spans = view.context("main", max_bytes=8)

            span = spans[0]
            self.assertEqual(1, span.start_line)
            self.assertEqual(1, span.end_line)
            self.assertEqual(1, span.requested_start_line)
            self.assertEqual(3, span.requested_end_line)
            self.assertEqual("partial", span.fidelity)
            self.assertTrue(span.needs_broader_context)
            self.assertEqual((1, 3), span.omitted_ranges[0])
            self.assertNotEqual(span.source_sha256, span.content_sha256)
            self.assertEqual(
                len(span.content.encode()), span.end_byte - span.start_byte
            )

    def test_context_many_applies_token_budget_and_deduplicates_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.py"
            source.write_text(
                "def main():\n    return True\n    return False\n",
                encoding="utf-8",
            )
            store = WorkspaceStore(root)
            base = store.build_base()
            with store.open(base.generation_id) as view:
                spans = view.context_many(("main", "ain"), max_tokens=2)
            assert len(spans) == 1
            assert spans[0].fidelity == "partial"
            assert spans[0].needs_broader_context
            assert spans[0].tokens <= 2
            assert spans[0].source_sha256 != spans[0].content_sha256

    def test_context_many_rejects_stale_source_after_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.py"
            source.write_text("def main():\n    return True\n", encoding="utf-8")
            store = WorkspaceStore(root)
            base = store.build_base()
            source.write_text("def main():\n    return False\n", encoding="utf-8")
            with store.open(base.generation_id) as view:
                with self.assertRaises(StaleSnapshotError):
                    view.context_many(("main",))

    def test_watch_refresh_is_debounced_and_writes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.py"
            source.write_text("def main():\n    return True\n", encoding="utf-8")
            store = WorkspaceStore(root)
            base = store.build_base()
            first, state = store.watch_once("slot", base.generation_id)
            self.assertIsNotNone(first)
            second, _ = store.watch_once("slot", base.generation_id, state)
            self.assertIsNone(second)
            temporary_files = list((root / ".simplicio" / "fast").rglob("*.tmp"))
            self.assertEqual([], temporary_files)

    def test_adapters_preserve_language_symbols_and_explicit_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ts = root / "api.ts"
            ts.write_text(
                "import { Client } from './client';\nexport interface Api {}\nexport function load() {}\n",
                encoding="utf-8",
            )
            symbols = parse_path(ts, "api.ts")
            self.assertEqual(
                {"import", "interface", "function"}, {item.kind for item in symbols}
            )
            self.assertEqual("fallback", negotiate("typescript").status)
            self.assertEqual("unavailable", negotiate("kotlin").status)

    def test_concurrent_overlay_publication_is_collision_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text("def main():\n    return True\n")
            store = WorkspaceStore(root)
            base = store.build_base()

            def publish(index: int):
                return store.create_overlay(f"slot-{index}", base.generation_id)

            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                overlays = list(executor.map(publish, range(20)))
            self.assertEqual(20, len(overlays))
            for overlay in overlays:
                path = (
                    root
                    / ".simplicio"
                    / "fast"
                    / "overlays"
                    / overlay.worktree_id
                    / f"{overlay.overlay_generation}.json"
                )
                self.assertEqual(
                    overlay.overlay_generation,
                    json.loads(path.read_text())["overlay_generation"],
                )
            self.assertEqual([], list((root / ".simplicio" / "fast").rglob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
