from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.contract import validate_instance
from simplicio_mapper.execution_context import (
    EXECUTION_CONTEXT_SCHEMA,
    ExecutionContextError,
    build_execution_context,
    resolve_execution_context_handle,
    validate_execution_context,
)
from simplicio_mapper.retrieval_index import (
    build_retrieval_index,
    resolve_expand_handle,
    select_context_targets,
)

ROOT = Path(__file__).resolve().parents[2]


class ExecutionContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src/service.py").write_text(
            "def calculate_total(value):\n    return value * 2\n",
            encoding="utf-8",
        )
        (self.root / "tests/test_service.py").write_text(
            "from src.service import calculate_total\n\n"
            "def test_calculate_total():\n    assert calculate_total(2) == 4\n",
            encoding="utf-8",
        )
        self.project_map = {
            "schema": "simplicio.project-map/v1",
            "product": {"name": "fixture"},
            "files": [
                {
                    "path": "src/service.py",
                    "roles": ["domain"],
                    "language": "python",
                    "size_bytes": 53,
                },
                {
                    "path": "tests/test_service.py",
                    "roles": ["test"],
                    "language": "python",
                    "size_bytes": 112,
                },
            ],
        }
        self.symbol_index = {
            "schema": "simplicio.symbol-index/v1",
            "symbols": [
                {
                    "name": "calculate_total",
                    "qualified_name": "src/service.py::calculate_total",
                    "kind": "function",
                    "defined_in": "src/service.py",
                    "line": 1,
                }
            ],
        }
        self.call_graph = {
            "schema": "simplicio.call-graph/v1",
            "edges": [
                {
                    "type": "imports",
                    "source_file": "tests/test_service.py",
                    "target_file": "src/service.py",
                    "line": 1,
                    "confidence": 0.65,
                }
            ],
        }
        self.precedent_index = {
            "schema": "simplicio.precedent-index/v1",
            "items": [
                {
                    "id": "precedent-1",
                    "path": "src/service.py",
                    "line": 1,
                    "summary": "calculate total feature precedent",
                    "tags": ["calculate_total", "feature"],
                    "snippet": "def calculate_total(value):",
                }
            ],
        }
        index = build_retrieval_index(
            self.project_map,
            symbol_index=self.symbol_index,
            call_graph=self.call_graph,
            root=str(self.root),
        )
        self.selection = select_context_targets(
            str(self.root),
            self.project_map,
            goal="Implement AC-1 calculate_total",
            target="src/service.py",
            symbol_index=self.symbol_index,
            call_graph=self.call_graph,
            token_budget=8000,
            retrieval_index=index,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self, **overrides):
        kwargs = {
            "root": str(self.root),
            "goal": "Implement AC-1 calculate_total",
            "task_fingerprint": "task-350",
            "acceptance_criteria": ["AC-1"],
            "project_map": self.project_map,
            "symbol_index": self.symbol_index,
            "call_graph": self.call_graph,
            "precedent_index": self.precedent_index,
            "selection": self.selection,
            "token_budget": 8000,
        }
        kwargs.update(overrides)
        return build_execution_context(**kwargs)

    def assert_invalid_shape(self, payload, path: str) -> None:
        self.assertIn(f"INVALID_SHAPE:{path}", validate_execution_context(payload))

    def test_builds_byte_stable_exact_evidence_envelope(self) -> None:
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)
        self.assertEqual(first["schema"], EXECUTION_CONTEXT_SCHEMA)
        self.assertEqual(first["envelope_hash"], second["envelope_hash"])
        source = first["sources"][0]
        self.assertEqual(source["path"], "src/service.py")
        self.assertEqual(source["source_hash"], hashlib.sha256((self.root / source["path"]).read_bytes()).hexdigest())
        self.assertTrue(source["spans"])
        self.assertEqual(source["spans"][0]["start_line"], 1)
        self.assertIn("calculate_total", source["spans"][0]["text"])
        self.assertTrue(source["spans"][0]["expansion_handle"].startswith("expand:"))
        self.assertEqual(first["graph_edges"][0]["provenance"], "call-graph")
        self.assertEqual(first["related_tests"][0]["path"], "tests/test_service.py")
        self.assertEqual(first["precedents"][0]["provenance"], "precedent-index:local-keyword-overlap")

    def test_different_tasks_have_independent_identity_and_ranking(self) -> None:
        other = self.build(goal="Verify test_calculate_total", task_fingerprint="task-other")
        first = self.build()
        self.assertNotEqual(first["task"]["fingerprint"], other["task"]["fingerprint"])
        self.assertNotEqual(first["envelope_hash"], other["envelope_hash"])

    def test_filters_secret_binary_and_path_escape_with_explicit_redactions(self) -> None:
        (self.root / ".env").write_text("API_TOKEN=top-secret\n", encoding="utf-8")
        (self.root / "blob.bin").write_bytes(b"\x00\x01secret")
        outside = self.root.parent / "outside-context.py"
        outside.write_text("SECRET='outside'\n", encoding="utf-8")
        unsafe_selection = json.loads(json.dumps(self.selection))
        unsafe_selection["targets"].extend(
            [{"path": ".env"}, {"path": "blob.bin"}, {"path": "../outside-context.py"}]
        )
        unsafe_selection["expanded_spans"].extend(
            [
                {"path": ".env", "spans": [], "expand_handle": "bad"},
                {"path": "blob.bin", "spans": [], "expand_handle": "bad"},
                {"path": "../outside-context.py", "spans": [], "expand_handle": "bad"},
            ]
        )
        unsafe_precedents = json.loads(json.dumps(self.precedent_index))
        unsafe_precedents["items"].append(
            {
                "id": "secret-precedent",
                "path": ".env",
                "summary": "calculate total secret precedent",
                "tags": ["calculate_total"],
                "snippet": "API_TOKEN=top-secret",
            }
        )
        unsafe_graph = json.loads(json.dumps(self.call_graph))
        unsafe_graph["edges"].append(
            {
                "type": "imports",
                "source_file": "src/service.py",
                "target_file": "../outside-context.py",
                "line": 1,
            }
        )
        result = self.build(
            selection=unsafe_selection,
            precedent_index=unsafe_precedents,
            call_graph=unsafe_graph,
        )
        source_paths = [item["path"] for item in result["sources"]]
        self.assertIn("src/service.py", source_paths)
        self.assertNotIn(".env", source_paths)
        self.assertNotIn("blob.bin", source_paths)
        self.assertNotIn("../outside-context.py", source_paths)
        self.assertEqual(
            {item["reason"] for item in result["redactions"]},
            {"secret_path", "binary_file", "outside_authorized_root"},
        )
        self.assertNotIn("top-secret", json.dumps(result))
        self.assertNotIn("outside-context.py", json.dumps(result["graph_edges"]))
        self.assertNotIn(".env", [item["path"] for item in result["precedents"]])
        outside.unlink()

    def test_redacts_common_credentials_in_every_free_text_field_and_resolved_handles(self) -> None:
        credentials = {
            "aws": "AKIA" + "ABCDEFGHIJKLMNOP",
            "bearer": "ghp_" + "abcdefghijklmnopqrstuvwxyz123456",
            "github_pat": "github_" + "pat_11AA22BB33_CC44DD55EE66FF77",
            "jwt": "eyJhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjMifQ.signature123",
            "url_password": "super-url-password",
        }
        (self.root / "src/service.py").write_text(
            "AWS_ACCESS_KEY_ID=" + credentials["aws"] + "\n"
            "Authorization: Bearer " + credentials["bearer"] + "\n"
            "GITHUB_TOKEN=" + credentials["github_pat"] + "\n"
            "session=" + credentials["jwt"] + "\n"
            "endpoint=https://user:" + credentials["url_password"] + "@example.test/db\n",
            encoding="utf-8",
        )
        unsafe_precedents = {
            "items": [
                {
                    "id": f"precedent-{credentials['github_pat']}",
                    "path": "src/service.py",
                    "line": 1,
                    "summary": f"calculate total {credentials['bearer']}",
                    "tags": ["calculate_total", credentials["jwt"]],
                    "snippet": f"AWS_SECRET_ACCESS_KEY={credentials['aws']}",
                }
            ]
        }
        current_selection = json.loads(json.dumps(self.selection))
        for expanded in current_selection["expanded_spans"]:
            if expanded["path"] == "src/service.py":
                expanded["expand_handle"] = ""
        result = self.build(
            goal=f"Implement calculate_total using {credentials['jwt']}",
            precedent_index=unsafe_precedents,
            selection=current_selection,
        )
        rendered = json.dumps(result)
        for value in credentials.values():
            self.assertNotIn(value, rendered)
        self.assertEqual(result["trust"]["sensitivity"], "redacted")
        self.assertIn("secret_value", {item["reason"] for item in result["redactions"]})

        resolved = resolve_execution_context_handle(
            str(self.root),
            result["sources"][0]["expansion_handle"],
        )
        for value in credentials.values():
            self.assertNotIn(value, json.dumps(resolved))
        self.assertIn("<redacted>", resolved["text"])

    def test_rejects_symlink_alias_to_secret_shaped_target(self) -> None:
        (self.root / ".env").write_text("AWS_ACCESS_KEY_ID=AKIA_SYMLINK_LEAK\n", encoding="utf-8")
        (self.root / "src/safe.py").symlink_to(self.root / ".env")
        unsafe_selection = json.loads(json.dumps(self.selection))
        unsafe_selection["targets"] = [{"path": "src/safe.py"}]
        unsafe_selection["expanded_spans"] = [{"path": "src/safe.py", "spans": []}]
        result = self.build(selection=unsafe_selection)
        self.assertEqual(result["sources"], [])
        self.assertIn({"path": "src/safe.py", "reason": "secret_path"}, result["redactions"])
        self.assertNotIn("AKIA_SYMLINK_LEAK", json.dumps(result))

    def test_pointer_only_selection_stays_pointer_only_and_within_budget(self) -> None:
        (self.root / "src/large.py").write_text(
            "".join(f"value_{index} = {index}\n" for index in range(5000)),
            encoding="utf-8",
        )
        pointer_selection = {
            "targets": [{"path": "src/large.py", "relevance_score": 1.0}],
            "expanded_spans": [{"path": "src/large.py", "spans": []}],
            "fidelity": {
                "sufficient": True,
                "dimensions": {},
                "coverage_ratio": 1.0,
                "reasons": [],
            },
            "abstained": False,
        }
        result = self.build(selection=pointer_selection, token_budget=8000)
        source = result["sources"][0]
        self.assertEqual(source["spans"], [])
        self.assertTrue(source["expansion_handle"].startswith("expand:"))
        self.assertTrue(result["token_budget"]["within_budget"])
        self.assertLessEqual(result["token_budget"]["serialized_tokens"], 8000)
        self.assertIn(
            {
                "kind": "source_content",
                "reason": "selection_pointer_only",
                "expansion_handle": source["expansion_handle"],
            },
            result["omissions"],
        )
        self.assertTrue(result["abstention"]["abstained"])
        self.assertFalse(result["fidelity"]["sufficient"])

    def test_impossible_budget_returns_explicit_overflow_and_abstention(self) -> None:
        result = self.build(token_budget=1)
        self.assertFalse(result["token_budget"]["within_budget"])
        self.assertTrue(result["abstention"]["abstained"])
        self.assertTrue(result["needs_broader_context"])
        self.assertIn("required_metadata_exceeds_budget", result["abstention"]["reasons"])
        self.assertTrue(result["next_queries"])

    def test_invalid_budget_and_no_match_fail_closed(self) -> None:
        with self.assertRaises(ExecutionContextError):
            self.build(token_budget=0)
        no_match = {
            "targets": [],
            "expanded_spans": [],
            "fidelity": {
                "sufficient": False,
                "dimensions": {},
                "coverage_ratio": 0.0,
                "reasons": ["no_relevant_targets"],
            },
            "abstained": True,
            "abstention_reason": "no_relevant_targets",
        }
        result = self.build(selection=no_match)
        self.assertTrue(result["abstention"]["abstained"])
        self.assertEqual(result["sources"], [])
        self.assertIn("no_relevant_targets", result["abstention"]["reasons"])

    def test_corrupt_or_stale_expansion_handle_is_rejected(self) -> None:
        handle = self.build()["sources"][0]["spans"][0]["expansion_handle"]
        resolved = resolve_execution_context_handle(str(self.root), handle)
        self.assertFalse(resolved["stale"])
        (self.root / "src/service.py").write_text("changed\n", encoding="utf-8")
        with self.assertRaises(ExecutionContextError):
            resolve_execution_context_handle(str(self.root), handle)
        with self.assertRaises(ExecutionContextError):
            resolve_execution_context_handle(str(self.root), "expand:corrupt")

    def test_expansion_handle_supports_colon_in_repository_path(self) -> None:
        colon_path = self.root / "src/namespace:service.py"
        colon_path.write_text("value = 1\n", encoding="utf-8")
        selection = {
            "targets": [{"path": "src/namespace:service.py"}],
            "expanded_spans": [{"path": "src/namespace:service.py", "spans": []}],
            "fidelity": {
                "sufficient": False,
                "dimensions": {},
                "coverage_ratio": 1.0,
                "reasons": ["exact_spans_omitted"],
            },
        }
        envelope = self.build(selection=selection)
        handle = envelope["sources"][0]["expansion_handle"]
        self.assertIn("%3A", handle)
        self.assertEqual(
            resolve_expand_handle(str(self.root), handle)["path"],
            "src/namespace:service.py",
        )

    def test_validator_detects_hash_and_budget_receipt_corruption(self) -> None:
        envelope = self.build()
        self.assertEqual(validate_execution_context(envelope), [])
        envelope["task"]["goal"] = "tampered"
        self.assertIn("ENVELOPE_HASH_MISMATCH", validate_execution_context(envelope))
        envelope = self.build()
        envelope["token_budget"]["serialized_tokens"] += 1
        self.assertIn("SERIALIZED_TOKEN_COUNT_MISMATCH", validate_execution_context(envelope))
        self.assertEqual(validate_execution_context({"schema": "future/v2"}), ["UNSUPPORTED_SCHEMA"])
        self.assertIn(
            "MISSING_REQUIRED:task",
            validate_execution_context({"schema": EXECUTION_CONTEXT_SCHEMA}),
        )
        for required in (
            "graph_edges",
            "related_tests",
            "precedents",
            "omissions",
            "needs_broader_context",
            "next_queries",
            "trust",
            "redactions",
        ):
            envelope = self.build()
            envelope.pop(required)
            self.assertIn(f"MISSING_REQUIRED:{required}", validate_execution_context(envelope))
        envelope = self.build()
        envelope["sources"][0]["line_count"] = "not-an-integer"
        self.assertIn("INVALID_SHAPE:sources[0].line_count", validate_execution_context(envelope))
        envelope = self.build()
        envelope["fidelity"]["sufficient"] = "yes"
        self.assertIn("INVALID_SHAPE:fidelity.sufficient", validate_execution_context(envelope))

    def test_validator_rejects_open_or_non_object_collection_items(self) -> None:
        for field in ("graph_edges", "related_tests", "precedents", "omissions", "redactions"):
            with self.subTest(field=field, shape="non-object"):
                envelope = self.build()
                envelope[field] = [42]
                self.assert_invalid_shape(envelope, f"{field}[0]")
            with self.subTest(field=field, shape="unknown-field"):
                envelope = self.build()
                envelope[field] = [{"unexpected": True}]
                self.assert_invalid_shape(envelope, f"{field}[0].unexpected")

    def test_validator_enforces_evidence_item_types_ranges_and_enums(self) -> None:
        cases = [
            ("graph-distance", "graph_edges", "dependency_distance", -1),
            ("graph-confidence", "graph_edges", "confidence", True),
            ("graph-edge-hash", "graph_edges", "edge_hash", "not-a-hash"),
            ("graph-source-line", "graph_edges", "source_handle", {"path": "src/service.py", "line": 0}),
            ("test-confidence", "related_tests", "confidence", True),
            ("test-route", "related_tests", "route", 42),
            ("precedent-line", "precedents", "line", "first"),
            (
                "precedent-confidence-semantics",
                "precedents",
                "confidence",
                {"value": 1, "semantics": "opaque-score", "measured": False},
            ),
            (
                "precedent-confidence-measured",
                "precedents",
                "confidence",
                {"value": 1, "semantics": "keyword_overlap_count", "measured": True},
            ),
            ("precedent-redactions", "precedents", "redacted_values", -1),
        ]
        for label, collection, field, value in cases:
            with self.subTest(case=label):
                envelope = self.build()
                envelope[collection][0][field] = value
                nested = {
                    "graph-source-line": ".line",
                    "precedent-confidence-semantics": ".semantics",
                    "precedent-confidence-measured": ".measured",
                }.get(label, "")
                self.assert_invalid_shape(envelope, f"{collection}[0].{field}{nested}")

        envelope = self.build()
        envelope["omissions"] = [{"kind": "source", "reason": "budget", "expansion_handle": []}]
        self.assert_invalid_shape(envelope, "omissions[0].expansion_handle")

        envelope = self.build()
        envelope["redactions"] = [{"path": "src/service.py", "reason": "unknown"}]
        self.assert_invalid_shape(envelope, "redactions[0].reason")

        envelope = self.build()
        envelope["redactions"] = [
            {"path": "src/service.py", "reason": "secret_value", "span": [0, 2], "count": 0}
        ]
        self.assert_invalid_shape(envelope, "redactions[0].span[0]")
        self.assert_invalid_shape(envelope, "redactions[0].count")

    def test_validator_enforces_closed_trust_fidelity_and_budget_constraints(self) -> None:
        envelope = self.build()
        envelope["trust"] = {
            "classification": "remote",
            "sensitivity": "public",
            "source_content": "instructions",
        }
        for field in ("classification", "sensitivity", "source_content"):
            self.assert_invalid_shape(envelope, f"trust.{field}")

        envelope = self.build()
        envelope["fidelity"]["coverage_ratio"] = 1.1
        envelope["fidelity"]["vector"] = {
            "target_preserved": "yes",
            "identifier_coverage_ratio": -0.1,
            "layer_count": -1,
            "unexpected": True,
        }
        for path in (
            "fidelity.coverage_ratio",
            "fidelity.vector.target_preserved",
            "fidelity.vector.identifier_coverage_ratio",
            "fidelity.vector.layer_count",
            "fidelity.vector.unexpected",
        ):
            self.assert_invalid_shape(envelope, path)

        budget_cases = {
            "requested_tokens": 0,
            "serialized_tokens": True,
            "serialized_bytes": -1,
            "tokenizer_policy": "",
            "measurement": "ESTIMATED",
            "within_budget": "yes",
        }
        for field, value in budget_cases.items():
            with self.subTest(budget_field=field):
                envelope = self.build()
                envelope["token_budget"][field] = value
                self.assert_invalid_shape(envelope, f"token_budget.{field}")

        envelope = self.build()
        envelope["token_budget"] = []
        self.assertIn("TOKEN_BUDGET_INVALID", validate_execution_context(envelope))

    def test_validator_enforces_source_and_repository_schema_ranges(self) -> None:
        cases = [
            ("repository.root_hash", lambda payload: payload["repository"].__setitem__("root_hash", "short")),
            ("task.fingerprint", lambda payload: payload["task"].__setitem__("fingerprint", "")),
            ("sources[0].rank", lambda payload: payload["sources"][0].__setitem__("rank", 0)),
            ("sources[0].line_count", lambda payload: payload["sources"][0].__setitem__("line_count", -1)),
            (
                "sources[0].spans[0].start_line",
                lambda payload: payload["sources"][0]["spans"][0].__setitem__("start_line", 0),
            ),
            (
                "sources[0].spans[0].expansion_handle",
                lambda payload: payload["sources"][0]["spans"][0].__setitem__("expansion_handle", ""),
            ),
        ]
        for path, mutate in cases:
            with self.subTest(path=path):
                envelope = self.build()
                mutate(envelope)
                self.assert_invalid_shape(envelope, path)

    def test_handoff_execution_context_is_opt_in_and_keeps_outer_contract(self) -> None:
        (self.root / "package.json").write_text('{"name":"execution-context-fixture"}', encoding="utf-8")
        index = subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.cli", "index", str(self.root), "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(index.returncode, 0, index.stderr)
        base_command = [
            sys.executable,
            "-m",
            "simplicio_mapper.cli",
            "handoff",
            str(self.root),
            "--goal",
            "Implement AC-1 calculate_total",
            "--target",
            "src/service.py",
            "--json",
        ]
        legacy = subprocess.run(base_command, check=False, capture_output=True, text=True)
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertNotIn("execution_context", json.loads(legacy.stdout))
        opted_in = subprocess.run(
            [*base_command[:-1], "--execution-context", "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(opted_in.returncode, 0, opted_in.stderr)
        payload = json.loads(opted_in.stdout)
        self.assertEqual(payload["schema"], "simplicio.map-handoff/v1")
        self.assertEqual(payload["execution_context"]["schema"], EXECUTION_CONTEXT_SCHEMA)

    def test_help_keeps_token_budget_default_with_token_budget_option(self) -> None:
        help_result = subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.cli", "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn(
            "--token-budget <n>    handoff: token budget passed to indexed selection "
            "diagnostics/fidelity\n                        (default 8000).\n"
            "  --execution-context",
            help_result.stdout,
        )

    def test_contract_schema_and_producer_fixture_are_packaged_assets(self) -> None:
        contract = ROOT / "contracts/execution-context/v1"
        schema = json.loads((contract / "schemas/execution-context.schema.json").read_text(encoding="utf-8"))
        fixture = json.loads((contract / "fixtures/valid/minimal/execution-context.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], EXECUTION_CONTEXT_SCHEMA)
        self.assertEqual(fixture["schema"], EXECUTION_CONTEXT_SCHEMA)
        self.assertEqual(set(schema["required"]) - set(fixture), set())
        self.assertFalse(schema["properties"]["repository"]["additionalProperties"])
        self.assertEqual(
            schema["properties"]["sources"]["items"]["properties"]["source_hash"]["pattern"],
            "^[0-9a-f]{64}$",
        )
        self.assertEqual(validate_instance(self.build(), schema), [])


if __name__ == "__main__":
    unittest.main()
