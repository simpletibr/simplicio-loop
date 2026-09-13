from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from simplicio_mapper.context_contract import (
    MAX_SNAPSHOT_BYTES,
    REPORT_SCHEMA,
    canonical_json,
    canonical_sha256,
    validate_context_file,
    validate_context_graph,
    validate_context_payload,
    validate_context_snapshot,
)
from simplicio_mapper.context_snapshot import build_context_snapshot
from simplicio_mapper.contract import validate_payload


class ContextContractTest(unittest.TestCase):
    def snapshot(self):
        return build_context_snapshot(
            "/repo",
            project_map={"product": {"name": "demo"}, "files": [{"path": "src/main.py"}]},
            symbol_index={"symbols": []},
            call_graph={"edges": []},
            architecture_inventory={"layers": []},
            revision="abc",
        )

    def codes(self, report):
        return {reason["code"] for reason in report["reason_codes"]}

    def test_builder_snapshot_is_valid_and_canonical(self):
        snapshot = self.snapshot()
        report = validate_context_snapshot(snapshot)
        self.assertTrue(report["valid"])
        self.assertEqual(report["schema"], REPORT_SCHEMA)
        self.assertEqual(canonical_sha256(snapshot["graph"]), snapshot["freshness"]["graph_hash"])
        self.assertEqual(json.loads(canonical_json({"b": 1, "a": "é"})), {"a": "é", "b": 1})

    def test_builder_snapshot_with_mapper_relation_is_valid(self):
        snapshot = build_context_snapshot(
            "/repo",
            project_map={
                "product": {"name": "demo"},
                "files": [{"path": "src/caller.py"}, {"path": "src/target.py"}],
            },
            symbol_index={
                "symbols": [
                    {
                        "name": "invoke",
                        "kind": "function",
                        "qualified_name": "invoke",
                        "defined_in": "src/caller.py",
                        "line": 2,
                    },
                    {
                        "name": "target",
                        "kind": "function",
                        "qualified_name": "target",
                        "defined_in": "src/target.py",
                        "line": 1,
                    },
                ]
            },
            call_graph={
                "edges": [
                    {
                        "type": "calls",
                        "source_file": "src/caller.py",
                        "source_symbol": "invoke",
                        "target_file": "src/target.py",
                        "target_symbol": "target",
                        "line": 3,
                    }
                ]
            },
            architecture_inventory={"layers": []},
            revision="abc",
        )
        report = validate_context_snapshot(snapshot)
        self.assertTrue(report["valid"], report["reason_codes"])

    def test_canonical_json_rejects_non_json_numbers(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                canonical_json(value)

    def test_tamper_count_future_and_reason_codes(self):
        snapshot = self.snapshot()
        snapshot["graph"]["counts"]["nodes"] = 99
        self.assertIn("GRAPH_COUNT_MISMATCH", self.codes(validate_context_snapshot(snapshot)))
        snapshot = self.snapshot()
        snapshot["schema_version"] = "v2"
        self.assertIn("UNSUPPORTED_SCHEMA", self.codes(validate_context_snapshot(snapshot)))

    def test_freshness_fidelity_drilldown_and_build_config_codes(self):
        snapshot = self.snapshot()
        snapshot["freshness"]["root_hash"] = "0" * 64
        snapshot["freshness"]["artifact_hashes"]["call_graph"] = "bad"
        snapshot["fidelity"]["coverage"]["micro"] = 10
        snapshot["drilldown"]["reversible"] = False
        snapshot["build_config_hash"] = "BAD"
        codes = self.codes(validate_context_snapshot(snapshot))
        self.assertTrue({"FRESHNESS_ROOT_HASH_MISMATCH", "ARTIFACT_HASH_INVALID", "FIDELITY_COVERAGE_MISMATCH", "SNAPSHOT_DRILLDOWN_INVALID", "BUILD_CONFIG_HASH_INVALID"}.issubset(codes))

    def test_graph_alias_depth_traversal_and_external_edge(self):
        snapshot = self.snapshot()
        graph = snapshot["graph"]
        self.assertTrue(validate_context_graph(graph)["valid"])
        self.assertEqual(validate_context_payload(graph)["target_schema"], "simplicio.context-graph/v1")
        source = graph["nodes"][0]["id"]
        target = "symbol:not-indexed"
        graph["edges"].append({"id": canonical_sha256({"kind": "calls", "source": source, "target": target}), "kind": "calls", "source": source, "target": target, "content_hash": "0" * 64, "source_handle": {"file": "src/main.py", "line": 1}})
        graph["counts"]["edges"] += 1
        self.assertTrue(validate_context_graph(graph)["valid"])
        graph["nodes"][0]["source"]["file"] = "../secret.py"
        self.assertIn("SOURCE_HANDLE_TRAVERSAL", self.codes(validate_context_graph(graph)))
        deep = value = {}
        for _ in range(100):
            child = {}
            value["child"] = child
            value = child
        self.assertIn("PAYLOAD_TOO_DEEP", self.codes(validate_context_payload(deep)))

    def test_source_handles_are_closed_after_rehashing(self):
        for location in (("nodes", 0, "source"), ("edges", 0, "source_handle")):
            snapshot = self.snapshot()
            collection, index, handle_name = location
            if collection == "edges" and not snapshot["graph"]["edges"]:
                source = snapshot["graph"]["nodes"][0]["id"]
                snapshot["graph"]["edges"].append(
                    {
                        "id": canonical_sha256({"kind": "calls", "source": source, "target": "external"}),
                        "kind": "calls",
                        "source": source,
                        "target": "external",
                        "content_hash": "0" * 64,
                        "source_handle": {"file": "src/main.py", "line": 1},
                    }
                )
                snapshot["graph"]["counts"]["edges"] += 1
            snapshot["graph"][collection][index][handle_name]["unexpected"] = True
            snapshot["freshness"]["graph_hash"] = canonical_sha256(snapshot["graph"])
            snapshot["snapshot_id"] = canonical_sha256(
                {key: value for key, value in snapshot.items() if key not in {"snapshot_id", "generated_at"}}
            )
            self.assertIn("SOURCE_HANDLE_UNKNOWN_PROPERTY", self.codes(validate_context_snapshot(snapshot)))

    def test_source_root_and_generic_contract_parity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
            graph = self.snapshot()["graph"]
            self.assertTrue(validate_context_graph(graph, source_root=directory)["valid"])
            graph["nodes"][0]["source"]["file"] = "missing.py"
            self.assertIn("SOURCE_HANDLE_UNRESOLVABLE", self.codes(validate_context_graph(graph, source_root=directory)))
        snapshot = self.snapshot()
        snapshot["graph"]["unknown"] = True
        snapshot["build_config_hash"] = "bad"
        direct = validate_context_payload(snapshot)
        schema, errors = validate_payload(snapshot, ".")
        self.assertEqual(schema, "simplicio.context-snapshot/v1")
        self.assertFalse(direct["valid"])
        self.assertTrue(any("BUILD_CONFIG_HASH_INVALID" in error for error in errors))

    def test_file_limits_malformed_and_hostile_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.json"
            path.write_bytes(b"x" * 20)
            self.assertIn("PAYLOAD_TOO_LARGE", self.codes(validate_context_file(str(path), max_bytes=8)))
            path.write_bytes(b"{")
            self.assertIn("INVALID_JSON", self.codes(validate_context_file(str(path))))
            path.write_text(json.dumps({"x": {"x": {"x": 1}}}), encoding="utf-8")
            self.assertIn("PAYLOAD_TOO_DEEP", self.codes(validate_context_file(str(path), max_depth=1)))
        self.assertIn("PAYLOAD_NOT_JSON", self.codes(validate_context_payload({"schema": "simplicio.context-snapshot/v1", "x": math.nan})))
        self.assertIn("PAYLOAD_NOT_JSON", self.codes(validate_context_payload({"schema": "simplicio.context-snapshot/v1", "x": "\ud800"})))
        graph = self.snapshot()["graph"]
        graph["nodes"][0]["source"]["file"] = "C:/secret.py"
        self.assertIn("SOURCE_HANDLE_INVALID", self.codes(validate_context_graph(graph)))
        self.assertLess(len(canonical_json(self.snapshot())), MAX_SNAPSHOT_BYTES)

    def test_wide_container_is_bounded_without_materializing_child_stack(self):
        report = validate_context_payload([0] * 100_000, max_bytes=64)
        self.assertIn("PAYLOAD_TOO_LARGE", self.codes(report))

    def test_shared_alias_is_not_a_cycle(self):
        shared = ["value"]
        report = validate_context_payload({"left": shared, "right": shared})
        self.assertNotIn("PAYLOAD_CYCLIC", self.codes(report))

    def test_stdlib_only_import(self):
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[2]))
        result = subprocess.run([sys.executable, "-S", "-c", "from simplicio_mapper.context_contract import validate_context_payload"], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @given(st.dictionaries(st.text(min_size=1, max_size=8), st.integers()))
    def test_mapping_order_does_not_change_hash(self, payload):
        self.assertEqual(canonical_sha256(payload), canonical_sha256(dict(reversed(list(payload.items())))))

    @given(st.text(min_size=1, max_size=32), st.text(min_size=1, max_size=32))
    def test_mutation_and_roundtrip(self, first, second):
        self.assertEqual(json.loads(canonical_json({"value": first})), {"value": first})
        if first != second:
            self.assertNotEqual(canonical_sha256({"value": first}), canonical_sha256({"value": second}))

    @given(st.recursive(st.none() | st.booleans() | st.integers() | st.text(max_size=32), lambda child: st.lists(child, max_size=4) | st.dictionaries(st.text(max_size=8), child, max_size=4), max_leaves=30))
    def test_arbitrary_json_never_crashes(self, payload):
        self.assertEqual(validate_context_payload(payload, max_bytes=4096, max_depth=16)["schema"], REPORT_SCHEMA)


if __name__ == "__main__":
    unittest.main()
