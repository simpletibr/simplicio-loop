from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from simplicio_fast.catalog import AddressCatalog, CatalogResolutionError, SCHEMA


class AddressCatalogTest(unittest.TestCase):
    def _catalog(
        self, root: Path, generation: str = "SFAST001:generation"
    ) -> AddressCatalog:
        return AddressCatalog(root, generation)

    def test_handles_are_deterministic_and_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = "a" * 64
            source = "b" * 64
            first = self._catalog(root)
            second = self._catalog(root)
            a = first.register("symbol", canonical, b"class User", source_sha256=source)
            b = second.register(
                "symbol", canonical, b"class User", source_sha256=source
            )
            self.assertEqual(a.handle, b.handle)
            self.assertNotEqual(
                a.handle,
                self._catalog(root, "SFAST001:other")._make_handle("symbol", canonical),
            )
            self.assertEqual(SCHEMA, first.stat()["schema"])

    def test_resolution_fails_closed_for_scope_state_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._catalog(root)
            entry = catalog.register(
                "span", "c" * 64, b"context", source_sha256="d" * 64
            )
            self.assertEqual(
                b"context",
                catalog.resolve(entry.handle, generation=catalog.generation).payload,
            )
            for kwargs, reason in (
                ({"generation": "SFAST001:stale"}, "stale_generation"),
                ({"repository": root / "other"}, "cross_repo_handle"),
                ({"payload_sha256": "e" * 64}, "payload_digest_mismatch"),
            ):
                with self.assertRaises(CatalogResolutionError) as error:
                    catalog.resolve(entry.handle, **kwargs)
                self.assertEqual(reason, error.exception.reason_code)
            catalog.tombstone(entry.handle)
            with self.assertRaises(CatalogResolutionError) as error:
                catalog.resolve(entry.handle)
            self.assertEqual("tombstoned", error.exception.reason_code)

    def test_binary_round_trip_verifies_and_detects_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = self._catalog(root)
            catalog.register(
                "file",
                "f" * 64,
                b"hello",
                source_sha256=hashlib.sha256(b"source").hexdigest(),
            )
            catalog.register(
                "test", "1" * 64, b"pytest", source_sha256="2" * 64, state="held"
            )
            path = root / "catalog.sfc"
            receipt = catalog.save(path)
            self.assertEqual("valid", receipt["status"])
            loaded = AddressCatalog.load(path)
            self.assertEqual(catalog.stat(), loaded.stat())
            self.assertEqual("valid", loaded.verify()["status"])
            corrupted = bytearray(path.read_bytes())
            corrupted[-1] ^= 1
            with self.assertRaises(CatalogResolutionError):
                AddressCatalog.from_bytes(bytes(corrupted))

    def test_bounded_resolution_preserves_guards_and_payload_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = self._catalog(Path(directory))
            first = catalog.register("span", "a" * 64, b"first", source_sha256="b" * 64)
            second = catalog.register(
                "span", "c" * 64, b"second", source_sha256="d" * 64
            )
            complete = catalog.resolve_many_bounded(
                [first.handle, second.handle], max_entries=2, max_bytes=32
            )
            self.assertEqual("resolution_complete", complete["reason_code"])
            self.assertEqual(
                [first.handle, second.handle],
                [item["handle"] for item in complete["references"]],
            )
            self.assertEqual(
                [b"first", b"second"],
                [item["payload"] for item in complete["materialized"]],
            )
            limited = catalog.resolve_many_bounded(
                [first.handle, second.handle],
                max_entries=2,
                max_bytes=len(first.payload) + len(second.payload) - 1,
            )
            self.assertTrue(limited["truncated"])
            self.assertEqual(1, limited["entries_materialized"])
            self.assertEqual("resolution_bounded", limited["reason_code"])
            with self.assertRaises(CatalogResolutionError) as error:
                catalog.resolve_many_bounded(
                    [first.handle], generation="SFAST001:stale"
                )
            self.assertEqual("stale_generation", error.exception.reason_code)

    def test_validation_and_resolution_error_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                AddressCatalog(root, "")
            catalog = self._catalog(root)
            canonical = "e" * 64
            source = "f" * 64
            entry = catalog.register(
                "symbol", canonical, b"payload", source_sha256=source
            )
            self.assertEqual(b"payload", entry.record()["payload"])
            self.assertNotIn("payload", entry.record(include_payload=False))
            self.assertIs(
                entry,
                catalog.register("symbol", canonical, b"payload", source_sha256=source),
            )
            with self.assertRaises(CatalogResolutionError) as error:
                catalog.register("symbol", canonical, b"changed", source_sha256=source)
            self.assertEqual("canonical_id_reuse", error.exception.reason_code)
            with self.assertRaises(CatalogResolutionError) as error:
                catalog.resolve("missing")
            self.assertEqual("handle_not_found", error.exception.reason_code)
            with self.assertRaises(CatalogResolutionError) as error:
                catalog.resolve(entry.handle, namespace="file")
            self.assertEqual("namespace_mismatch", error.exception.reason_code)
            with self.assertRaises(ValueError):
                catalog.resolve_many_bounded([entry.handle], max_entries=0)
            with self.assertRaises(ValueError):
                catalog.resolve_many_bounded([entry.handle], max_bytes=0)
            self.assertEqual([entry], catalog.resolve_many([entry.handle]))
            with self.assertRaises(ValueError):
                catalog.tombstone(entry.handle, state="active")
            with self.assertRaises(CatalogResolutionError) as error:
                catalog.tombstone("missing")
            self.assertEqual("handle_not_found", error.exception.reason_code)
