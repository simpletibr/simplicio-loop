from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.language_capabilities import (
    CAPABILITIES,
    LANGUAGES,
    build_capability_coverage,
    native_route,
    validate_promotion,
)
from simplicio_mapper.mapper.graph import _build_call_graph, _build_symbol_index
from simplicio_mapper.mapper.parse import _build_file_inventory, _now_iso
from simplicio_mapper.models import ProjectFile
from simplicio_mapper.semantic_resolution import (
    RoslynSemanticAdapter,
    resolution_key,
    resolve_semantic_calls,
)


def _write(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class LanguageCapabilityCatalogTest(unittest.TestCase):
    def test_native_route_falls_back_without_dropping_known_language(self) -> None:
        route = native_route("csharp", "imports")
        self.assertEqual(route["backend"], "python-reference")
        self.assertEqual(route["reason"], "native_extension_unavailable")

    def test_catalog_rejects_unknown_route_keys_and_always_uses_python_reference(self) -> None:
        self.assertEqual(native_route("not-a-language", "imports")["reason"], "language_not_in_capability_catalog")
        self.assertEqual(native_route("python", "not-a-capability")["reason"], "capability_not_in_catalog")
        route = native_route("python", "imports")
        self.assertEqual((route["backend"], route["status"]), ("python-reference", "fallback"))

    def test_matrix_and_promotion_validation_fail_closed(self) -> None:
        from simplicio_mapper.language_capabilities import build_matrix_rows

        rows = build_matrix_rows({("python", "imports"): {"status": "bogus", "native_default": True}})
        python_imports = next(row for row in rows if row["language"] == "python" and row["capability"] == "imports")
        self.assertEqual(python_imports["status"], "MISMATCH")
        self.assertIn("row_key_invalid:unknown@imports", validate_promotion([{"language": "unknown", "capability": "imports"}]))
        self.assertIn("matrix_incomplete:csharp", validate_promotion([]))

    def test_promotion_is_blocked_by_missing_or_mismatched_capability(self) -> None:
        rows = [
            {"language": language, "capability": capability, "status": "NATIVE_PARITY"}
            for language in LANGUAGES
            for capability in CAPABILITIES
        ]
        rows[0]["status"] = "MISSING"
        errors = validate_promotion(rows)
        self.assertEqual(errors, [])
        rows[0]["native_default"] = True
        self.assertIn("native_default_without_parity:csharp@language-detection", validate_promotion(rows))

    def test_receipt_exposes_observed_language_degradation(self) -> None:
        file = ProjectFile(
            path="Service.cs",
            language="csharp",
            size_bytes=1,
            last_modified="",
            file_hash="",
            git_status="clean",
            roles=[],
            imports=[],
            exports=[],
        )
        receipt = build_capability_coverage(
            [file],
            semantic_resolution={
                "schema": "simplicio.mapper-semantic-resolution/v1",
                "status": "unavailable",
                "languages": ["csharp"],
                "reason": "semantic_service_not_configured",
            },
        )
        self.assertIn("csharp", receipt["languages"])
        self.assertIn("calls:csharp:semantic_service_not_configured", receipt["languages"]["csharp"]["degraded"])
        self.assertFalse(receipt["native_promotion"]["csharp"]["native_default"])

    def test_receipt_marks_semantic_backend_when_available(self) -> None:
        file = ProjectFile(
            path="Service.cs",
            language="csharp",
            size_bytes=1,
            last_modified="",
            file_hash="",
            git_status="clean",
            roles=[],
            imports=[],
            exports=[],
        )
        receipt = build_capability_coverage(
            [file],
            semantic_resolution={"status": "available", "languages": ["csharp"]},
        )
        capabilities = receipt["languages"]["csharp"]["capabilities"]
        self.assertIn("calls", capabilities["backend"]["semantic-service"])
        self.assertIn("calls", capabilities["route_status"]["semantic"])


class CSharpSemanticResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        _write(
            self.root,
            "Service.cs",
            "public class Service\n"
            "{\n"
            "    public int Compute(int value) => value;\n"
            "    public string Compute(string value) => value;\n"
            "}\n",
        )
        _write(
            self.root,
            "App.cs",
            "public class App\n"
            "{\n"
            "    public void Run(Service service)\n"
            "    {\n"
            "        service.Compute(1);\n"
            "        service.Compute(\"x\");\n"
            "    }\n"
            "}\n",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _files_and_symbols(self):
        files = _build_file_inventory(str(self.root), {}, {}, None)
        symbols = _build_symbol_index(str(self.root), files, _now_iso(), contents={
            file.path: (self.root / file.path).read_text(encoding="utf-8") for file in files
        })
        return files, symbols

    def test_duplicate_overloads_use_compiler_identity_when_service_available(self) -> None:
        files, symbols = self._files_and_symbols()
        by_signature = {
            item.get("signature"): item["qualified_name"]
            for item in symbols["symbols"]
            if item.get("signature")
        }

        def runner(command, **kwargs):
            request = json.loads(kwargs["input"])
            resolutions = [
                {"source_file": "App.cs", "name": "Compute", "line": 5, "target_symbol": by_signature["Compute(int)"]},
                {"source_file": "App.cs", "name": "Compute", "line": 6, "target_symbol": by_signature["Compute(string)"]},
            ]
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({
                    "schema": "simplicio.mapper-semantic-result/v1",
                    "protocol": "v1",
                    "provider": "roslyn-test",
                    "provider_version": "4.12",
                    "resolutions": resolutions,
                    "symbols": [],
                    "request_language": request["language"],
                }),
                "",
            )

        adapter = RoslynSemanticAdapter(command=["semantic-test"], runner=runner)
        graph = _build_call_graph(
            str(self.root),
            files,
            symbols,
            _now_iso(),
            contents={file.path: (self.root / file.path).read_text(encoding="utf-8") for file in files},
            semantic_adapter=adapter,
        )
        calls = [edge for edge in graph["edges"] if edge["type"] == "calls" and edge["line"] in {5, 6}]
        self.assertEqual({edge["target_symbol"] for edge in calls}, {by_signature["Compute(int)"], by_signature["Compute(string)"]})
        self.assertTrue(all(edge["evidence_class"] == "semantic_resolved" for edge in calls))
        self.assertTrue(all(edge["resolution_status"] == "resolved" for edge in calls))
        self.assertEqual(graph["semantic_resolution"]["status"], "available")

    def test_without_service_overloads_remain_heuristic_not_resolved(self) -> None:
        files, symbols = self._files_and_symbols()
        graph = _build_call_graph(
            str(self.root),
            files,
            symbols,
            _now_iso(),
            contents={file.path: (self.root / file.path).read_text(encoding="utf-8") for file in files},
        )
        calls = [edge for edge in graph["edges"] if edge["type"] == "calls" and edge["line"] in {5, 6}]
        self.assertTrue(calls)
        self.assertTrue(all(edge["evidence_class"] == "heuristic" for edge in calls))
        self.assertTrue(all(edge["resolution_status"] != "resolved" for edge in calls))
        self.assertEqual(graph["semantic_resolution"]["status"], "unavailable")


class SqlCoverageTest(unittest.TestCase):
    def test_sql_objects_are_explicit_and_call_graph_is_empty(self) -> None:
        text = (
            "CREATE TABLE users (id INTEGER);\n"
            "CREATE VIEW active_users AS SELECT id FROM users;\n"
            "CREATE FUNCTION user_count() RETURNS INTEGER;\n"
            "CREATE PROCEDURE refresh_users();\n"
        )
        file = ProjectFile(
            path="schema.sql",
            language="sql",
            size_bytes=len(text),
            last_modified="",
            file_hash="",
            git_status="clean",
            roles=[],
            imports=[],
            exports=[],
        )
        symbols = _build_symbol_index(".", [file], _now_iso(), contents={"schema.sql": text})
        self.assertEqual(
            {item["kind"] for item in symbols["symbols"]},
            {"table", "view", "function", "procedure"},
        )
        graph = _build_call_graph(".", [file], symbols, _now_iso(), contents={"schema.sql": text})
        self.assertEqual([edge for edge in graph["edges"] if edge["type"] == "calls"], [])


class SemanticProtocolTest(unittest.TestCase):
    def test_protocol_rejects_bad_service_output_and_supports_fallbacks(self) -> None:
        unsupported = RoslynSemanticAdapter(command=["unused"], runner=lambda *_args, **_kwargs: None)
        result, receipt = unsupported.resolve(".", "python", [], [], [{"source_file": "x.py", "name": "f", "line": 1}])
        self.assertIsNone(result)
        self.assertEqual(receipt["status"], "not_required")

        invalid = RoslynSemanticAdapter(
            command=["semantic-test"],
            runner=lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "{}", ""),
        )
        result, receipt = invalid.resolve(".", "csharp", [], [], [{"source_file": "x.cs", "name": "f", "line": 1}])
        self.assertIsNone(result)
        self.assertIn("semantic_service_schema_mismatch", receipt["reason"])

        result, receipt = resolve_semantic_calls(".", "csharp", [], [], [])
        self.assertIsNone(result)
        self.assertEqual(receipt["reason"], "no_call_sites")
        self.assertEqual(resolution_key({"source_file": "./x.cs", "source_line": 3, "call_name": "f"}), ("x.cs", 3, "f"))
        self.assertIsNone(resolution_key({"source_file": "x.cs", "line": "bad", "name": "f"}))


if __name__ == "__main__":
    unittest.main()
