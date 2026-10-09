"""Tests for fast binary snapshot mmap integration (Issue #652).

Integrates the SFAST v2 binary format (.sfast/HBP) using mmap, atomic write
with whole-file SHA-256 checksum, section directory validation, and resilient
safe degradation on corrupted snapshots.
"""

from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.store.snapshot import (
    ENDIAN_MARKER,
    HEADER,
    MAGIC,
    MAPPER_HANDOFF_SCHEMA,
    REQUIRED_SECTIONS,
    VERSION,
    CorruptSnapshotError,
    Snapshot,
    build_snapshot,
    build_snapshot_from_artifacts,
    is_snapshot_valid,
    load_snapshot_safe,
)


class FastSnapshotMmapTest(unittest.TestCase):
    """Test suite for SFAST v2 binary snapshot mmap indexing in Mapper."""

    def test_create_binary_snapshot_in_state_dir(self) -> None:
        """Test the creation of a binary snapshot in .simplicio-loop/project.sfast."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            state_dir = root / ".simplicio-loop"
            state_dir.mkdir(parents=True, exist_ok=True)
            output = state_dir / "project.sfast"

            # Create sample python source files
            (root / "calculator.py").write_text(
                "class Calculator:\n"
                "    def add(self, a, b):\n"
                "        return a + b\n"
                "\n"
                "    def subtract(self, a, b):\n"
                "        return a - b\n",
                encoding="utf-8",
            )

            metrics = build_snapshot(root, output)
            self.assertTrue(output.is_file(), "Snapshot file must exist")
            self.assertGreater(output.stat().st_size, 0, "Snapshot file must not be empty")
            self.assertEqual(metrics.format_version, VERSION)
            self.assertEqual(metrics.parsed_files, 1)

            # Verify with Snapshot class
            with Snapshot(output) as snapshot:
                self.assertEqual(snapshot.format_version, VERSION)
                files = snapshot.files()
                self.assertEqual(len(files), 1)
                self.assertEqual(files[0][0], "calculator.py")
                symbols = snapshot.symbols()
                symbol_names = [s.name for s in symbols]
                self.assertIn("Calculator", symbol_names)
                self.assertIn("add", symbol_names)
                self.assertIn("subtract", symbol_names)

    def test_sfast_v2_header_validation(self) -> None:
        """Test validation of SFAST v2 header: MAGIC, VERSION 2, ENDIAN_MARKER."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output = root / ".simplicio-loop" / "project.sfast"
            (root / "module.py").write_text("def ping():\n    return 'pong'\n", encoding="utf-8")
            build_snapshot(root, output)

            raw_bytes = output.read_bytes()
            self.assertGreaterEqual(len(raw_bytes), HEADER.size)

            # Inspect header struct (<8sHHIQQQQ32s)
            (
                magic,
                version,
                endian,
                section_count,
                generation,
                directory_offset,
                directory_size,
                total_size,
                checksum,
            ) = HEADER.unpack_from(raw_bytes, 0)

            self.assertEqual(magic, MAGIC, f"MAGIC must be {MAGIC!r}")
            self.assertEqual(magic, b"SFAST001")
            self.assertEqual(version, 2, "VERSION must be 2")
            self.assertEqual(endian, ENDIAN_MARKER, f"ENDIAN_MARKER must be 0x{ENDIAN_MARKER:04x}")
            self.assertEqual(endian, 0x0102)
            self.assertGreaterEqual(section_count, len(REQUIRED_SECTIONS))
            self.assertEqual(total_size, len(raw_bytes))
            self.assertEqual(len(checksum), 32)

            # Test invalid magic rejection
            bad_magic_bytes = bytearray(raw_bytes)
            bad_magic_bytes[:8] = b"BADMAGIC"
            bad_magic_file = root / "bad_magic.sfast"
            bad_magic_file.write_bytes(bad_magic_bytes)
            with self.assertRaises(ValueError) as ctx:
                Snapshot(bad_magic_file)
            self.assertIn("unsupported", str(ctx.exception).lower())

            # Test invalid version rejection
            bad_version_bytes = bytearray(raw_bytes)
            bad_version_bytes[8:10] = struct.pack("<H", 99)
            bad_version_file = root / "bad_version.sfast"
            bad_version_file.write_bytes(bad_version_bytes)
            with self.assertRaises(ValueError) as ctx:
                Snapshot(bad_version_file)
            self.assertIn("version", str(ctx.exception).lower())

            # Test invalid endian marker rejection
            bad_endian_bytes = bytearray(raw_bytes)
            bad_endian_bytes[10:12] = struct.pack("<H", 0x9999)
            bad_endian_file = root / "bad_endian.sfast"
            bad_endian_file.write_bytes(bad_endian_bytes)
            with self.assertRaises(ValueError) as ctx:
                Snapshot(bad_endian_file)
            self.assertIn("header", str(ctx.exception).lower())

    def test_mmap_reading_sections(self) -> None:
        """Test reading files, symbols, relations, indexes, strings using mmap."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output = root / ".simplicio-loop" / "project.sfast"

            (root / "app.py").write_text(
                "import utils\n"
                "\n"
                "class App:\n"
                "    def run(self):\n"
                "        return utils.compute()\n",
                encoding="utf-8",
            )
            (root / "utils.py").write_text(
                "def compute():\n    return 42\n",
                encoding="utf-8",
            )

            build_snapshot(root, output)

            with Snapshot(output) as snapshot:
                # Ensure memory mapping is active
                self.assertTrue(hasattr(snapshot, "_map"))
                self.assertIsNotNone(snapshot._map)

                # 1. Section: files
                files = snapshot.files()
                file_names = [f[0] for f in files]
                self.assertIn("app.py", file_names)
                self.assertIn("utils.py", file_names)
                for f_path, f_hash in files:
                    self.assertEqual(len(f_hash), 32)

                # 2. Section: symbols
                symbols = snapshot.symbols()
                self.assertGreater(len(symbols), 0)
                app_sym = snapshot.find_exact("App")
                self.assertTrue(bool(app_sym))
                self.assertEqual(app_sym[0].kind, "class")
                self.assertEqual(app_sym[0].file, "app.py")

                run_sym = snapshot.find_exact("App.run")
                self.assertTrue(bool(run_sym))
                self.assertEqual(run_sym[0].name, "run")

                compute_sym = snapshot.find_exact("compute")
                self.assertTrue(bool(compute_sym))
                self.assertEqual(compute_sym[0].file, "utils.py")

                # 3. Section: relations
                relations = snapshot.relations()
                self.assertIsInstance(relations, list)
                import_rel = [r for r in relations if r.kind == "import"]
                self.assertTrue(any("utils" in r.destination for r in import_rel))

                # 4. Section: indexes
                indexes = snapshot.indexes()
                self.assertIn("exact", indexes)
                self.assertIn("names", indexes)
                self.assertIn("paths", indexes)
                self.assertIn("kinds", indexes)
                self.assertIn("provenance", indexes)
                self.assertIn("app.run", indexes["exact"])

                # 5. Section: strings
                # Validate strings are correctly resolved for symbols and files
                stats = snapshot.stats()
                for section in REQUIRED_SECTIONS:
                    self.assertIn(section, stats["sections"])

    def test_atomic_write_with_whole_file_sha256(self) -> None:
        """Test atomic write with whole-file SHA-256 checksum."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output = root / ".simplicio-loop" / "project.sfast"
            (root / "code.py").write_text("def answer(): return 42\n", encoding="utf-8")

            total_size, checksum = build_snapshot(root, output)
            self.assertEqual(total_size, output.stat().st_size)

            raw = output.read_bytes()
            # Whole-file checksum in header is verified
            (
                magic,
                version,
                endian,
                section_count,
                gen,
                dir_off,
                dir_sz,
                tot_sz,
                header_checksum,
            ) = HEADER.unpack_from(raw, 0)

            # Recompute expected whole-file checksum with checksum slot zeroed
            payload_copy = bytearray(raw)
            payload_copy[HEADER.size - 32 : HEADER.size] = b"\0" * 32
            expected_checksum = hashlib.sha256(payload_copy).digest()
            self.assertEqual(header_checksum, expected_checksum)
            self.assertEqual(checksum, expected_checksum.hex())

            # Test atomic publish: ensure no temporary files linger
            tmp_files = list((root / ".simplicio-loop").glob("*.tmp"))
            self.assertEqual(tmp_files, [], "No temporary files should be left after publication")

            # Verify with Snapshot property
            with Snapshot(output) as snapshot:
                self.assertEqual(snapshot.content_checksum, checksum)
                self.assertEqual(snapshot.sha256, hashlib.sha256(raw).hexdigest())

    def test_corrupt_snapshot_safe_degradation(self) -> None:
        """Test resilience: if the snapshot is corrupted, degrade safely without crash."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output = root / ".simplicio-loop" / "project.sfast"
            (root / "module.py").write_text("def work(): pass\n", encoding="utf-8")
            build_snapshot(root, output)
            original = output.read_bytes()

            # 1. Truncated snapshot
            output.write_bytes(original[: HEADER.size - 5])
            self.assertFalse(is_snapshot_valid(output))
            degraded_snapshot = load_snapshot_safe(output)
            self.assertIsNone(degraded_snapshot, "load_snapshot_safe must return None on truncated file")

            # 2. Bit flip in payload (checksum mismatch)
            corrupted = bytearray(original)
            corrupted[-1] ^= 0xFF
            output.write_bytes(corrupted)
            self.assertFalse(is_snapshot_valid(output))
            with self.assertRaises((ValueError, CorruptSnapshotError)):
                Snapshot(output)
            safe_snap = load_snapshot_safe(output)
            self.assertIsNone(safe_snap, "load_snapshot_safe must return None on checksum mismatch")

            # 3. Corrupted magic bytes
            corrupted_magic = bytearray(original)
            corrupted_magic[:8] = b"\x00" * 8
            output.write_bytes(corrupted_magic)
            self.assertFalse(is_snapshot_valid(output))
            self.assertIsNone(load_snapshot_safe(output))

            # 4. Non-existent file
            non_existent = root / "does_not_exist.sfast"
            self.assertFalse(is_snapshot_valid(non_existent))
            self.assertIsNone(load_snapshot_safe(non_existent))

    def test_snapshot_from_canonical_ast_artifacts(self) -> None:
        """Test generation of snapshot triggered from Mapper's canonical AST artifacts."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            src_file = root / "src" / "app.py"
            src_file.parent.mkdir(parents=True, exist_ok=True)
            src_content = (
                "class UserManager:\n"
                "    def authenticate(self, user, token):\n"
                "        return token == 'secret'\n"
            )
            src_file.write_text(src_content, encoding="utf-8")
            file_hash = hashlib.sha256(src_file.read_bytes()).hexdigest()

            # Canonical AST artifacts as produced by Mapper
            project_map = {
                "schema": "simplicio.project-map/v1",
                "version": "1.0.0",
                "generated_at": "2026-10-02T12:00:00Z",
                "files": [
                    {
                        "path": "src/app.py",
                        "language": "python",
                        "size_bytes": len(src_content),
                        "file_hash": file_hash,
                    }
                ],
            }
            symbol_index = {
                "schema": "simplicio.symbol-index/v1",
                "version": "1.0.0",
                "symbols": [
                    {
                        "name": "UserManager",
                        "qualified_name": "src/app.py::UserManager",
                        "kind": "class",
                        "defined_in": "src/app.py",
                        "line": 1,
                        "end_line": 3,
                    },
                    {
                        "name": "authenticate",
                        "qualified_name": "src/app.py::UserManager.authenticate",
                        "kind": "function",
                        "defined_in": "src/app.py",
                        "line": 2,
                        "end_line": 3,
                        "signature": "(self, user, token)",
                    },
                ],
            }
            call_graph = {
                "schema": "simplicio.call-graph/v1",
                "version": "1.0.0",
                "edges": [
                    {
                        "type": "calls",
                        "source_file": "src/app.py",
                        "source_symbol": "src/app.py::UserManager.authenticate",
                        "target_file": "src/app.py",
                        "target_symbol": "src/app.py::UserManager",
                        "confidence": 0.9,
                    }
                ],
            }

            artifacts = {
                "project_map": project_map,
                "symbol_index": symbol_index,
                "call_graph": call_graph,
            }

            sfast_dest = root / ".simplicio-loop" / "project.sfast"
            total_size, checksum = build_snapshot_from_artifacts(
                root,
                artifacts=artifacts,
                output=sfast_dest,
            )

            self.assertTrue(sfast_dest.is_file())
            self.assertGreater(total_size, 0)
            self.assertEqual(len(checksum), 64)

            with Snapshot(sfast_dest) as snapshot:
                self.assertEqual(snapshot.format_version, VERSION)
                # Verify provenance is marked as integrated with simplicio-mapper
                prov = snapshot.provenance
                self.assertEqual(prov["mode"], "integrated")
                self.assertEqual(prov["authority"], "simplicio-mapper")
                self.assertEqual(prov["mapper_schema"], MAPPER_HANDOFF_SCHEMA)

                # Verify symbols loaded via mmap
                symbols = snapshot.symbols()
                names = {s.name for s in symbols}
                self.assertIn("UserManager", names)
                self.assertIn("authenticate", names)

                # Verify search / find
                exact_res = snapshot.find_exact("src/app.py::UserManager")
                self.assertEqual(len(exact_res), 1)
                self.assertEqual(exact_res[0].kind, "class")
                self.assertEqual(exact_res[0].name, "UserManager")

                # Substring find matches both UserManager and UserManager.authenticate
                all_res = snapshot.find("UserManager")
                self.assertEqual(len(all_res), 2)

                # Verify relations
                rels = snapshot.relations()
                self.assertEqual(len(rels), 1)
                self.assertEqual(rels[0].kind, "call")
                self.assertEqual(rels[0].confidence, 0.9)

    def test_indexing_creates_fast_snapshot(self) -> None:
        """Test that running mapper index generates .simplicio-loop/project.sfast."""
        from simplicio_mapper.cli import main

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "app.py").write_text("def run():\n    return True\n", encoding="utf-8")
            exit_code = main(["index", str(root), "--json"])
            self.assertEqual(exit_code, 0)

            sfast_file = root / ".simplicio-loop" / "project.sfast"
            self.assertTrue(sfast_file.is_file(), "project.sfast must exist after index")
            self.assertTrue(is_snapshot_valid(sfast_file))

            with Snapshot(sfast_file) as snapshot:
                self.assertEqual(snapshot.format_version, VERSION)
                syms = snapshot.symbols()
                self.assertTrue(any(s.name == "run" for s in syms))

    def test_segments_publish_and_paging(self) -> None:
        """Test immutable segment slicing and semantic paging from SFAST."""
        from simplicio_mapper.store.segments import (
            MANIFEST_SCHEMA,
            SegmentStore,
            SemanticSegmentPager,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "app.py").write_text("def run():\n    return 42\n", encoding="utf-8")
            sfast_file = root / ".simplicio-loop" / "project.sfast"
            build_snapshot(root, sfast_file)

            seg_dir = root / ".simplicio-loop" / "segments"
            store = SegmentStore(seg_dir)
            manifest = store.publish(sfast_file)

            self.assertEqual(manifest["schema"], MANIFEST_SCHEMA)
            self.assertTrue((seg_dir / "manifest.json").is_file())
            self.assertEqual(manifest["segments_written"], len(REQUIRED_SECTIONS))

            validation = store.validate()
            self.assertEqual(validation["status"], "valid")

            pager = SemanticSegmentPager(
                store,
                repository="test-repo",
                generation=manifest["generation"],
            )
            data = pager.read("strings", 0, 4)
            self.assertEqual(len(data), 4)


if __name__ == "__main__":
    unittest.main()
