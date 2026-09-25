from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simplicio_fast.snapshot import (
    Snapshot,
    SnapshotProvenanceError,
    Symbol,
    _build_v2,
    build_snapshot,
)


class MapperProjection516Test(unittest.TestCase):
    @staticmethod
    def _provenance() -> dict[str, object]:
        return {
            "schema": "simplicio.fast.snapshot-provenance/v1",
            "mode": "integrated",
            "authority": "simplicio-mapper",
            "mapper_schema": "simplicio.mapper-fast-handoff/v1",
            "mapper_version": "0.26.20",
            "repository_id": "repo",
            "mapper_generation": "mapper-g1",
            "artifact_digest": "a" * 64,
            "fast_format_version": 2,
            "capability_coverage": {
                "context_graph": True,
                "files": True,
                "symbols": True,
                "relations": True,
                "source_hashes": True,
                "stable_handles": True,
            },
        }

    def test_snapshot_persists_and_checks_mapper_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project.sfast"
            symbol = Symbol(
                "run",
                "run",
                "function",
                "service.py",
                1,
                1,
                "0" * 64,
            )
            _build_v2(
                [("service.py", b"x" * 32, 1, [symbol])],
                (),
                output,
                provenance=self._provenance(),
            )
            with Snapshot(output) as snapshot:
                self.assertEqual(self._provenance(), snapshot.provenance)
                self.assertTrue(snapshot.matches_mapper({
                    "mapper_schema": "simplicio.mapper-fast-handoff/v1",
                    "mapper_version": "0.26.20",
                    "repository_id": "repo",
                    "generation": "mapper-g1",
                    "artifact_digest": "a" * 64,
                }))
                with self.assertRaisesRegex(RuntimeError, "provenance"):
                    snapshot.require_mapper({
                        "mapper_schema": "simplicio.mapper-fast-handoff/v1",
                        "mapper_version": "0.26.20",
                        "repository_id": "repo",
                        "generation": "mapper-g2",
                        "artifact_digest": "a" * 64,
                    })

    def test_source_parser_cannot_overwrite_integrated_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text("def run():\n    return True\n", encoding="utf-8")
            output = root / "project.sfast"
            symbol = Symbol("run", "run", "function", "service.py", 1, 1, "0" * 64)
            _build_v2(
                [("service.py", b"x" * 32, source.stat().st_size, [symbol])],
                (),
                output,
                provenance=self._provenance(),
            )
            with self.assertRaises(SnapshotProvenanceError):
                build_snapshot(root, output)


if __name__ == "__main__":
    unittest.main()
