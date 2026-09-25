import tempfile
import unittest
import hashlib
import random
from pathlib import Path
from unittest.mock import patch

from simplicio_fast.snapshot import (
    LEGACY_FILE_RECORD,
    LEGACY_HEADER,
    LEGACY_SYMBOL_RECORD,
    MAGIC,
    SourceEncodingError,
    Snapshot,
    SnapshotBuildTimeout,
    SnapshotTooLarge,
    SourceParseError,
    StaleSnapshotError,
    build_snapshot,
    source_files,
)
import simplicio_fast.snapshot as snapshot_module


class SnapshotTest(unittest.TestCase):
    def test_invalid_python_raises_typed_parse_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "broken.py"
            source.write_text("def broken(:\n    pass\n", encoding="utf-8")
            output = root / "project.sfast"

            with self.assertRaises(SourceParseError) as raised:
                build_snapshot(root, output)

            error = raised.exception
            self.assertEqual("source_parse_failed", error.code)
            self.assertEqual("broken.py", error.path)
            self.assertEqual(1, error.line)
            self.assertIsNotNone(error.column)
            self.assertIn("fix the source syntax", error.recovery)
            self.assertFalse(output.exists())

    def test_source_files_prunes_ignored_directories_before_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("def run():\n    return True\n")
            (root / "node_modules" / "nested").mkdir(parents=True)
            (root / "node_modules" / "nested" / "ignored.py").write_text(
                "def ignored():\n    pass\n"
            )
            (root / ".git" / "objects").mkdir(parents=True)
            (root / ".git" / "objects" / "ignored.py").write_text(
                "def ignored():\n    pass\n"
            )

            self.assertEqual([root / "app.py"], source_files(root))

    def test_snapshot_publish_retries_transient_windows_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("def run():\n    return True\n")
            output = root / "snapshot.sfast"
            original_replace = snapshot_module.os.replace
            calls = 0

            def flaky_replace(source: Path, destination: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError(5, "access denied")
                original_replace(source, destination)

            with patch.object(snapshot_module.os, "replace", side_effect=flaky_replace):
                build_snapshot(root, output)
            self.assertGreaterEqual(calls, 2)
            self.assertTrue(output.is_file())

    def test_binary_snapshot_query_and_incremental_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.py"
            source.write_text("class User:\n    def save(self):\n        return True\n")
            output = root / ".index/project.sfast"

            cold = build_snapshot(root, output)
            self.assertEqual(1, cold.parsed_files)
            self.assertEqual(("sample.py",), cold.parsed_paths)
            self.assertEqual(("cold_build",), cold.reason_codes)
            with Snapshot(output) as snapshot:
                matches = snapshot.find("save")
                self.assertEqual("User.save", matches[0].qualified_name)
                context = snapshot.context(root, "save")
                self.assertEqual("User.save", context[0].symbol)
                self.assertIn("def save", context[0].content)
                self.assertEqual(64, len(context[0].source_sha256))
                self.assertEqual(64, len(snapshot.sha256))
                self.assertEqual(f"SFAST001:{snapshot.sha256}", snapshot.generation)

            with patch.object(
                snapshot_module, "_build_v2", side_effect=AssertionError("republish")
            ):
                warm = build_snapshot(root, output)
            self.assertEqual(0, warm.parsed_files)
            self.assertEqual(1, warm.reused_files)
            self.assertEqual((), warm.parsed_paths)
            self.assertEqual(("sample.py",), warm.reused_paths)
            self.assertEqual((), warm.changed_paths)
            self.assertEqual(("no_change",), warm.reason_codes)

            source.write_text(
                source.read_text() + "\ndef deactivate():\n    return False\n"
            )
            with Snapshot(output) as snapshot:
                with self.assertRaises(StaleSnapshotError):
                    snapshot.context(root, "save")
            changed = build_snapshot(root, output)
            self.assertEqual(1, changed.parsed_files)
            self.assertEqual(("sample.py",), changed.parsed_paths)
            self.assertEqual(("sample.py",), changed.changed_paths)
            self.assertEqual(("source_changed",), changed.reason_codes)
            with Snapshot(output) as snapshot:
                self.assertEqual(1, len(snapshot.find("deactivate")))

    def test_v2_indexes_relations_and_context_budgets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "import helpers\n\nclass Service:\n    def run(self):\n        return helpers.go()\n"
            )
            output = root / "project.sfast"
            metrics = build_snapshot(root, output)
            self.assertEqual(2, metrics.format_version)
            with Snapshot(output) as snapshot:
                self.assertEqual("SFAST001/v2", snapshot.stats()["format"])
                self.assertEqual(
                    "Service.run", snapshot.find_exact("Service.run")[0].qualified_name
                )
                self.assertTrue(
                    any(item.kind == "call" for item in snapshot.impact("go"))
                )
                spans = snapshot.context(root, "run", max_bytes=6, max_tokens=2)
                self.assertLessEqual(
                    sum(len(item.content.encode()) for item in spans), 6
                )
                self.assertLessEqual(sum(item.tokens for item in spans), 2)
                self.assertEqual(4, spans[0].start_line)
                self.assertEqual(4, spans[0].end_line)
                self.assertEqual((4, 5), spans[0].omitted_ranges[0])
                self.assertEqual("partial", spans[0].fidelity)
                self.assertTrue(spans[0].needs_broader_context)
                self.assertNotEqual(
                    spans[0].source_sha256, spans[0].content_sha256
                )

                line_limited = snapshot.context(root, "run", max_lines=1)
                self.assertEqual(4, line_limited[0].start_line)
                self.assertEqual(4, line_limited[0].end_line)
                self.assertEqual((5, 5), line_limited[0].omitted_ranges[0])
                self.assertEqual("partial", line_limited[0].fidelity)

    def test_context_reads_each_matching_source_file_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text(
                "def run_one():\n    return 1\n\ndef run_two():\n    return 2\n"
            )
            output = root / "project.sfast"
            build_snapshot(root, output)
            original_read_bytes = Path.read_bytes
            reads = 0

            def read_bytes(path: Path) -> bytes:
                nonlocal reads
                if path.resolve() == source.resolve():
                    reads += 1
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", read_bytes):
                with Snapshot(output) as snapshot:
                    spans = snapshot.context(root, "run", max_results=10)

            self.assertGreaterEqual(len(spans), 2)
            self.assertEqual(1, reads)

    def test_context_cut_reports_fixture_range_and_utf8_content_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "guard.py"
            source.write_text(
                "def idempotency(user):\n"
                "    if not user:\n"
                "        return False\n"
                "    return True\n",
                encoding="utf-8",
            )
            output = root / "project.sfast"
            build_snapshot(root, output)
            with Snapshot(output) as snapshot:
                span = snapshot.context(root, "idempotency", max_bytes=24)[0]
                self.assertEqual((1, 4), (span.requested_start_line, span.requested_end_line))
                self.assertEqual(2, span.end_line)
                self.assertEqual("partial", span.fidelity)
                self.assertEqual(((2, 4),), span.omitted_ranges)
                self.assertTrue(span.needs_broader_context)
                self.assertNotEqual(span.source_sha256, span.content_sha256)

            source.write_text(
                "def café():\n    return True\n", encoding="utf-8"
            )
            build_snapshot(root, output)
            with Snapshot(output) as snapshot:
                span = snapshot.context(root, "café", max_bytes=8)[0]
                self.assertEqual("def caf", span.content)
                self.assertEqual("partial", span.fidelity)
                self.assertNotIn("�", span.content)

    def test_async_imports_and_repository_derived_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text(
                '[remote "origin"]\n    url = https://example.invalid/repo.git\n'
            )
            (root / "module.py").write_text(
                "from package import helper\nfrom .local import value\n\nasync def load(item):\n    return helper(item)\n"
            )
            output = root / "project.sfast"
            build_snapshot(root, output)
            with Snapshot(output) as snapshot:
                loaded = snapshot.find_exact("load")[0]
                self.assertEqual("async_function", loaded.kind)
                self.assertTrue(loaded.signature)
                self.assertEqual(64, len(loaded.symbol_id))
                self.assertTrue(
                    any(item.kind == "import" for item in snapshot.relations())
                )

    def test_corruption_and_truncation_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text("def hello():\n    return True\n")
            output = root / "project.sfast"
            build_snapshot(root, output)
            original = output.read_bytes()
            output.write_bytes(original[:-1])
            with self.assertRaises(ValueError):
                Snapshot(output)

            rng = random.Random(2)
            for _ in range(20):
                mutated = bytearray(original)
                mutated[rng.randrange(len(mutated))] ^= 1 << rng.randrange(8)
                output.write_bytes(mutated)
                with self.assertRaises(ValueError):
                    Snapshot(output)
            output.write_bytes(original)
            corrupted = bytearray(original)
            corrupted[-1] ^= 0xFF
            output.write_bytes(corrupted)
            with self.assertRaises(ValueError):
                Snapshot(output)

    def test_reads_frozen_v1_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            strings = b"sample.pyA"
            files_offset = LEGACY_HEADER.size
            symbols_offset = files_offset + LEGACY_FILE_RECORD.size
            strings_offset = symbols_offset + LEGACY_SYMBOL_RECORD.size
            total_size = strings_offset + len(strings)
            payload = bytearray(total_size)
            LEGACY_HEADER.pack_into(
                payload,
                0,
                MAGIC,
                1,
                1,
                1,
                files_offset,
                symbols_offset,
                strings_offset,
                total_size,
            )
            LEGACY_FILE_RECORD.pack_into(
                payload, files_offset, 0, 9, 1, 0, hashlib.sha256(b"x").digest()
            )
            LEGACY_SYMBOL_RECORD.pack_into(payload, symbols_offset, 9, 1, 0, 1, 1, 2)
            payload[strings_offset:] = strings
            output = root / "legacy.sfast"
            output.write_bytes(payload)
            with Snapshot(output) as snapshot:
                self.assertEqual(1, snapshot.format_version)
                self.assertEqual("A", snapshot.find_exact("A")[0].name)

    def test_python_encoding_policy_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            latin = root / "latin.py"
            latin.write_bytes(b"# coding: latin-1\nclass Caf\xe9:\n    pass\n")
            output = root / "project.sfast"

            build_snapshot(root, output)
            with Snapshot(output) as snapshot:
                self.assertEqual("Café", snapshot.find_exact("Café")[0].name)

            invalid = root / "invalid.py"
            invalid.write_bytes(b"\xff\xfe\x00\x01")
            with self.assertRaises(SourceEncodingError) as raised:
                build_snapshot(root, output)
            self.assertEqual("source_encoding_unreadable", raised.exception.code)
            self.assertIn("invalid.py", str(raised.exception))

    def test_build_recovers_from_truncated_snapshot_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text("def recovered():\n    return True\n")
            output = root / "project.sfast"
            output.write_bytes(b"truncated")
            metrics = build_snapshot(root, output)
            self.assertEqual(("snapshot_invalidated",), metrics.reason_codes)
            self.assertEqual(("sample.py",), metrics.parsed_paths)
            with Snapshot(output) as snapshot:
                self.assertEqual(1, len(snapshot.find("recovered")))
            self.assertEqual([], list(root.glob("*.tmp")))

    def test_incremental_receipt_reports_added_and_deleted_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_text("def a():\n    return True\n")
            output = root / "project.sfast"
            build_snapshot(root, output)
            (root / "b.py").write_text("def b():\n    return True\n")
            (root / "a.py").unlink()

            metrics = build_snapshot(root, output)

            self.assertEqual(("a.py", "b.py"), metrics.changed_paths)
            self.assertEqual(("source_added", "source_deleted"), metrics.reason_codes)
            self.assertEqual(("b.py",), metrics.parsed_paths)
            self.assertEqual((), metrics.reused_paths)

    def test_bounded_build_preserves_previous_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.py"
            source.write_text("def original():\n    return True\n")
            output = root / "project.sfast"
            build_snapshot(root, output)
            before = output.read_bytes()
            source.write_text("def changed():\n    return True\n")
            with self.assertRaises(SnapshotBuildTimeout) as raised:
                build_snapshot(root, output, timeout_seconds=0)
            self.assertEqual(1, raised.exception.progress["files_total"])
            self.assertEqual(0, raised.exception.progress["files_processed"])
            self.assertEqual(1, raised.exception.progress["files_remaining"])
            self.assertEqual(0, raised.exception.progress["parsed_files"])
            self.assertEqual(0, raised.exception.progress["reused_files"])
            self.assertTrue(raised.exception.progress["previous_snapshot_preserved"])
            self.assertEqual(before, output.read_bytes())

    def test_oversized_source_fails_before_parse_and_preserves_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.py"
            source.write_text("def original():\n    return True\n")
            output = root / "project.sfast"
            build_snapshot(root, output)
            before = output.read_bytes()
            source.write_text("x" * 32)
            with self.assertRaisesRegex(ValueError, "source_file_too_large"):
                build_snapshot(root, output, max_file_bytes=4)
            self.assertEqual(before, output.read_bytes())

    def test_snapshot_size_bound_fails_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text("def bounded():\n    return True\n")
            output = root / "project.sfast"
            with patch("simplicio_fast.snapshot.MAX_SNAPSHOT_BYTES", 64):
                with self.assertRaises(SnapshotTooLarge):
                    build_snapshot(root, output)
            self.assertFalse(output.exists())

    def test_bounded_reverse_invalidation_closure_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.py").write_text("def target():\n    return True\n")
            (root / "caller.py").write_text(
                "from target import target\n\ndef caller():\n    return target()\n"
            )
            (root / "top.py").write_text(
                "from caller import caller\n\ndef top():\n    return caller()\n"
            )
            output = root / "project.sfast"
            build_snapshot(root, output)
            with Snapshot(output) as snapshot:
                first = snapshot.invalidation_closure(["target.py"])
                second = snapshot.invalidation_closure(["target.py"])
                bounded = snapshot.invalidation_closure(
                    ["target.py"], max_symbols=2, max_files=1
                )
                missing = snapshot.invalidation_closure(["missing.py"])
            self.assertEqual(first, second)
            self.assertEqual("invalidated", first["status"])
            self.assertEqual(
                ["caller.py", "target.py", "top.py"], first["affected_files"]
            )
            self.assertIn("top", first["affected_symbols"])
            self.assertEqual("truncated", bounded["status"])
            self.assertTrue(bounded["truncated"])
            self.assertLessEqual(len(bounded["affected_symbol_ids"]), 2)
            self.assertEqual("no_op", missing["status"])
            self.assertEqual("no_changed_symbols", missing["reason_code"])

    def test_validation_cache_skips_source_reads_and_emits_phase_timings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.rs"
            source.write_text("pub fn sample() -> bool { true }\n", encoding="utf-8")
            output = root / "project.sfast"
            build_snapshot(root, output)
            original_read_bytes = Path.read_bytes
            source_reads = []

            def tracked_read_bytes(path):
                if path.resolve() == source.resolve():
                    source_reads.append(path.resolve())
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", tracked_read_bytes):
                metrics = build_snapshot(root, output)

            self.assertEqual([], source_reads)
            self.assertEqual(1, metrics.metadata_reused_files)
            self.assertEqual(0, metrics.parsed_files)
            self.assertEqual(
                {
                    "previous_snapshot_load",
                    "discovery",
                    "unchanged_validation",
                    "parsing",
                    "publication",
                },
                set(metrics.phase_timings_ms),
            )
            self.assertTrue(
                all(value >= 0 for value in metrics.phase_timings_ms.values())
            )

    def test_validation_cache_rehashes_same_size_change_and_invalid_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.rs"
            source.write_text("pub fn value() -> i32 { 1 }\n", encoding="utf-8")
            output = root / "project.sfast"
            build_snapshot(root, output)
            source.write_text("pub fn value() -> i32 { 2 }\n", encoding="utf-8")

            changed = build_snapshot(root, output)

            self.assertEqual(("sample.rs",), changed.parsed_paths)
            cache = output.with_name(f"{output.name}.validation.json")
            cache.write_text("{broken", encoding="utf-8")
            original_read_bytes = Path.read_bytes
            source_reads = []

            def tracked_read_bytes(path):
                if path.resolve() == source.resolve():
                    source_reads.append(path.resolve())
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", tracked_read_bytes):
                recovered = build_snapshot(root, output)

            self.assertEqual([source.resolve()], source_reads)
            self.assertEqual(0, recovered.metadata_reused_files)
            self.assertEqual(1, recovered.reused_files)

    def test_fresh_validation_cache_rehashes_when_metadata_clock_is_frozen(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.rs"
            source.write_text("pub fn value() -> i32 { 1 }\n", encoding="utf-8")
            output = root / "project.sfast"
            frozen_identity = {
                "size": source.stat().st_size,
                "mtime_ns": 1,
                "ctime_ns": 1,
            }
            with patch(
                "simplicio_fast.snapshot._file_identity",
                return_value=frozen_identity,
            ):
                build_snapshot(root, output)
                source.write_text(
                    "pub fn value() -> i32 { 2 }\n",
                    encoding="utf-8",
                )
                changed = build_snapshot(root, output)

            self.assertEqual(("sample.rs",), changed.parsed_paths)
            self.assertEqual(0, changed.metadata_reused_files)

    def test_timeout_receipt_includes_phase_timings_with_previous_snapshot(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.rs"
            source.write_text("pub fn before() {}\n", encoding="utf-8")
            output = root / "project.sfast"
            build_snapshot(root, output)
            before = output.read_bytes()
            source.write_text("pub fn after_() {}\n", encoding="utf-8")

            with self.assertRaises(SnapshotBuildTimeout) as raised:
                build_snapshot(root, output, timeout_seconds=0)

            self.assertTrue(raised.exception.progress["previous_snapshot_preserved"])
            self.assertIn("phase_timings_ms", raised.exception.progress)
            self.assertEqual(before, output.read_bytes())


    def test_v1_snapshot_survives_failed_v2_publish_and_migrates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text("class New: pass\n", encoding="utf-8")
            strings = b"sample.pyA"
            files_offset = LEGACY_HEADER.size
            symbols_offset = files_offset + LEGACY_FILE_RECORD.size
            strings_offset = symbols_offset + LEGACY_SYMBOL_RECORD.size
            payload = bytearray(strings_offset + len(strings))
            LEGACY_HEADER.pack_into(
                payload,
                0,
                MAGIC,
                1,
                1,
                1,
                files_offset,
                symbols_offset,
                strings_offset,
                len(payload),
            )
            LEGACY_FILE_RECORD.pack_into(
                payload, files_offset, 0, 9, 1, 0, hashlib.sha256(b"x").digest()
            )
            LEGACY_SYMBOL_RECORD.pack_into(payload, symbols_offset, 9, 1, 0, 1, 1, 2)
            payload[strings_offset:] = strings
            output = root / "project.sfast"
            output.write_bytes(payload)
            before = output.read_bytes()

            with patch.object(
                snapshot_module, "_build_v2", side_effect=RuntimeError("publish failed")
            ):
                with self.assertRaises(RuntimeError):
                    build_snapshot(root, output)

            self.assertEqual(before, output.read_bytes())
            with Snapshot(output) as snapshot:
                self.assertEqual(1, snapshot.format_version)
                self.assertEqual("A", snapshot.find_exact("A")[0].name)

            metrics = build_snapshot(root, output)
            self.assertEqual(2, metrics.format_version)
            with Snapshot(output) as snapshot:
                self.assertEqual(2, snapshot.format_version)
                self.assertEqual("SFAST001/v2", snapshot.stats()["format"])

if __name__ == "__main__":
    unittest.main()
