from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main
from simplicio_mapper.context_graph_contract import canonical_digest
from simplicio_mapper.fast_handoff import (
    HANDOFF_SCHEMA,
    build_fast_handoff,
    verify_fast_handoff,
)


class FastHandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        out = self.root / ".simplicio"
        out.mkdir()
        snapshot = {
            "schema": "simplicio.context-snapshot/v1",
            "snapshot_id": "stable-generation",
            "repository_id": "repo-1",
            "revision": "abc123",
            "producer": {
                "name": "simplicio-mapper",
                "version": "0.26.31",
                "artifact_version": 1,
            },
            "fidelity": {
                "gate": "ready",
                "status": "complete",
                "omissions": [],
            },
            "graph": {
                "nodes": [
                    {"id": "py-main", "language": "python", "source": {"file": "src/main.py"}},
                    {"id": "ts-main", "language": "typescript", "source": {"file": "src/main.ts"}},
                ],
                "edges": [
                    {"id": "call-1", "kind": "calls", "source": "py-main", "target": "ts-main"}
                ],
            },
        }
        self.snapshot = snapshot
        self.capability_coverage = {
            "schema": "simplicio.mapper-capability-coverage/v1",
            "version": 1,
            "languages": {"python": {"file_count": 1}},
        }
        artifacts = {
            "context-snapshot.json": snapshot,
            "project-map.json": {
                "files": [{"path": "src/main.py"}, {"path": "src/main.ts"}],
                "capability_coverage": self.capability_coverage,
            },
            "symbol-index.json": {"symbols": []},
            "call-graph.json": {"edges": []},
            "architecture-inventory.json": {"modules": []},
        }
        for name, payload in artifacts.items():
            (out / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_machine_first_cli_emits_paths_generation_and_receipt(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(
                [
                    "fast-handoff",
                    str(self.root),
                    "--changed-path",
                    "src/main.py",
                    "--base-commit",
                    "base-1",
                ]
            )
        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["handoff"]["schema"], HANDOFF_SCHEMA)
        self.assertEqual(
            payload["handoff"]["producer"],
            self.snapshot["producer"],
        )
        self.assertEqual(
            payload["handoff"]["fidelity"],
            self.snapshot["fidelity"],
        )
        self.assertEqual(payload["handoff"]["generation"], "stable-generation")
        self.assertEqual(payload["handoff"]["fidelity"]["gate"], "ready")
        canonical_map = payload["handoff"]["canonical_map"]
        self.assertEqual(canonical_map["schema"], "simplicio.context-graph-contract/v1")
        self.assertEqual(canonical_map["version"], 1)
        self.assertEqual(canonical_map["digest"], canonical_digest({key: value for key, value in canonical_map.items() if key != "digest"}))
        self.assertEqual(payload["handoff"]["delta"]["node_ids"], ["py-main"])
        self.assertEqual(payload["handoff"]["delta"]["base_commit"], "base-1")
        self.assertEqual(
            payload["handoff"]["capabilities"]["language_capability_coverage"],
            self.capability_coverage,
        )
        self.assertEqual(payload["receipt"]["counters"]["parsed"], 1)
        self.assertNotIn("offset", stdout.getvalue())

    def test_restart_reuses_same_generation_ids_and_canonical_map(self) -> None:
        first, first_receipt = build_fast_handoff(str(self.root))
        second, second_receipt = build_fast_handoff(str(self.root))
        self.assertEqual(first["generation"], second["generation"])
        self.assertEqual(first["delta"]["node_ids"], second["delta"]["node_ids"])
        self.assertEqual(first["canonical_map"]["id"], second["canonical_map"]["id"])
        self.assertEqual(first_receipt["status"], "parsed")
        self.assertEqual(second_receipt["status"], "reused")

    def test_one_file_delta_only_selects_affected_subgraph(self) -> None:
        handoff, _ = build_fast_handoff(str(self.root), changed_paths=["src/main.py"])
        self.assertEqual(handoff["delta"]["node_ids"], ["py-main"])
        self.assertEqual(handoff["delta"]["edge_ids"], ["call-1"])
        self.assertEqual(handoff["delta"]["affected"], {"nodes": 1, "edges": 1})

    def test_incompatible_schema_has_actionable_fallback(self) -> None:
        handoff, receipt = build_fast_handoff(str(self.root), expected_schema="v999")
        self.assertFalse(handoff)
        self.assertEqual(receipt["status"], "fallback")
        self.assertIn(HANDOFF_SCHEMA, receipt["reason"])
        self.assertEqual(receipt["counters"]["fallback"], 1)

    def test_missing_corrupt_and_stale_artifacts_degrade_safely(self) -> None:
        snapshot_path = self.root / ".simplicio" / "context-snapshot.json"
        original = snapshot_path.read_text(encoding="utf-8")
        snapshot_path.write_text("{", encoding="utf-8")
        handoff, receipt = build_fast_handoff(str(self.root))
        self.assertFalse(handoff)
        self.assertEqual(receipt["status"], "degraded")
        self.assertIn("snapshot build", receipt["reason"])

        snapshot_path.write_text(original, encoding="utf-8")
        build_fast_handoff(str(self.root))
        (self.root / ".simplicio" / "project-map.json").write_text("{}\n", encoding="utf-8")
        valid, reason = verify_fast_handoff(str(self.root))
        self.assertFalse(valid)
        self.assertTrue(reason.startswith("checksum_mismatch:"))

    def test_twenty_slots_reuse_one_canonical_base(self) -> None:
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: build_fast_handoff(str(self.root))[0], range(20)))
        self.assertEqual({item["generation"] for item in results}, {"stable-generation"})
        self.assertEqual(len({item["canonical_map"]["id"] for item in results}), 1)
        self.assertTrue(verify_fast_handoff(str(self.root))[0])


if __name__ == "__main__":
    unittest.main()
