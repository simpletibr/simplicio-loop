from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main
from simplicio_mapper.fast_backend import diagnose_fast, resolve_backend

REPO_ROOT = Path(__file__).resolve().parents[2]


class FastBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "package.json").write_text('{"name":"fast-backend-test"}\n', encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
        self.manifest = self.root / "fast-context.json"
        self.local = {
            "project_map": {"product": {"name": "fast-backend-test"}, "files": [{"path": "local.py"}]},
            "symbol_index": {"symbols": []},
            "call_graph": {"edges": []},
            "architecture_inventory": {"modules": [], "layers": []},
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_manifest(self) -> dict:
        payload = {
            "schema": "simplicio.fast-context/v1",
            "generation": "generation-0001",
            "capabilities": {
                "snapshot_schemas": ["simplicio.context-snapshot/v1"],
                "languages": ["python"],
                "edge_kinds": ["calls", "imports"],
            },
            "projections": {
                "files": [{"path": "src/main.py", "language": "python", "roles": ["domain"]}],
                "symbols": [
                    {
                        "name": "main",
                        "qualified_name": "src/main.py::main",
                        "kind": "function",
                        "defined_in": "src/main.py",
                        "line": 1,
                    }
                ],
                "edges": [],
            },
        }
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def test_fast_projection_is_translated_without_exposing_mmap_offsets(self) -> None:
        self._write_manifest()
        resolution = resolve_backend(
            root=str(self.root),
            local_artifacts=self.local,
            mode="fast",
            manifest_path=str(self.manifest),
        )
        self.assertEqual(resolution.receipt["selected_backend"], "fast")
        self.assertEqual(resolution.receipt["generation"], "generation-0001")
        self.assertEqual(resolution.artifacts["project_map"]["files"][0]["path"], "src/main.py")
        self.assertNotIn("offset", json.dumps(resolution.artifacts))

    def test_incompatible_manifest_falls_back_with_reason_not_empty_graph(self) -> None:
        self.manifest.write_text('{"schema":"simplicio.fast-context/v999"}', encoding="utf-8")
        resolution = resolve_backend(
            root=str(self.root),
            local_artifacts=self.local,
            mode="fast",
            manifest_path=str(self.manifest),
        )
        self.assertEqual(resolution.receipt["selected_backend"], "mapper")
        self.assertEqual(resolution.receipt["status"], "degraded")
        self.assertEqual(resolution.receipt["reason"], "fast_schema_incompatible")
        self.assertEqual(resolution.artifacts["project_map"]["files"], [{"path": "local.py"}])

    def test_same_manifest_produces_deterministic_projection_hash(self) -> None:
        self._write_manifest()
        first = resolve_backend(
            root=str(self.root), local_artifacts=self.local, mode="fast", manifest_path=str(self.manifest)
        )
        second = resolve_backend(
            root=str(self.root), local_artifacts=self.local, mode="fast", manifest_path=str(self.manifest)
        )
        self.assertEqual(first.receipt["projection_hash"], second.receipt["projection_hash"])

    def test_versioned_cross_language_fixture_preserves_all_languages(self) -> None:
        fixture = REPO_ROOT / "contracts" / "fast-context" / "v1" / "fixtures" / "cross-language.json"
        resolution = resolve_backend(
            root=str(self.root),
            local_artifacts=self.local,
            mode="fast",
            manifest_path=str(fixture),
        )
        languages = {item["language"] for item in resolution.artifacts["project_map"]["files"]}
        self.assertEqual(languages, {"python", "typescript", "rust", "csharp"})
        self.assertEqual(len(resolution.artifacts["symbol_index"]["symbols"]), 4)

    def test_snapshot_cli_keeps_mapper_as_public_producer_and_writes_receipt(self) -> None:
        self._write_manifest()
        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "snapshot",
                    "build",
                    "--root",
                    str(self.root),
                    "--backend",
                    "fast",
                    "--fast-manifest",
                    str(self.manifest),
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        snapshot = json.loads(output.getvalue())
        self.assertEqual(snapshot["producer"]["name"], "simplicio-mapper")
        self.assertEqual(snapshot["graph"]["counts"]["micro"], 1)
        receipt = json.loads(
            (self.root / ".simplicio" / "fast-backend-receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["selected_backend"], "fast")

    def test_doctor_reports_absent_and_compatible_fast(self) -> None:
        self.assertEqual(diagnose_fast()["reason"], "fast_manifest_absent")
        self._write_manifest()
        output = StringIO()
        with redirect_stdout(output):
            code = main(["doctor", "--fast", str(self.manifest), "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["compatible"])


if __name__ == "__main__":
    unittest.main()
