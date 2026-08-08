from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import simplicio_mapper.context_pack as context_pack_module
from simplicio_mapper.cli import main
from simplicio_mapper.cli._status_engine import _run_handoff
from simplicio_mapper.context_pack import build_context_pack
from simplicio_mapper.retrieval_index import (
    estimate_tokens,
    serialized_json_bytes,
    serialized_token_count,
)


def select_context_targets(*args, **kwargs):
    return context_pack_module.select_context_targets(*args, **kwargs)


def _materialize(root: Path, value: dict) -> dict:
    if value.get("schema") != "simplicio.context-reference/v1":
        return value
    return json.loads((root / value["expansion_handle"]["path"]).read_text(encoding="utf-8"))


def _summary(value: dict) -> dict:
    return value["summary"] if value.get("schema") == "simplicio.context-reference/v1" else value


class TaskAwareHandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src/modeling").mkdir(parents=True)
        (self.root / "docs").mkdir()
        (self.root / "src/modeling/sort_lines.py").write_text(
            "def sort_power_plant_lines(lines):\n"
            "    # structural first; temporal and modeling by start date\n"
            "    return sorted(lines)\n",
            encoding="utf-8",
        )
        (self.root / "docs/release-notes.md").write_text(
            "Dependency release packaging notes only.\n", encoding="utf-8"
        )
        self.project_map = {
            "files": [
                {"path": "src/modeling/sort_lines.py", "roles": ["domain"], "importance": 0.4},
                {"path": "docs/release-notes.md", "roles": [], "importance": 0.9},
            ],
            "recent_changes": [{"path": "docs/release-notes.md", "status": "modified"}],
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_recent_irrelevant_change_does_not_preempt_task_match(self) -> None:
        selection = select_context_targets(
            str(self.root),
            self.project_map,
            goal="Order modeling lines: structural first, then temporal and modeling by start date",
            limit=1,
        )

        self.assertEqual([row["path"] for row in selection["targets"]], ["src/modeling/sort_lines.py"])
        self.assertGreater(selection["targets"][0]["relevance_score"], 0)
        self.assertIn("matched_terms", selection["targets"][0]["relevance_reason"])
        self.assertFalse(selection["targets"][0]["recent_change_boost"])
        self.assertFalse(selection["abstained"])
        self.assertIn("fidelity", selection)
        self.assertIn("token_budget_fit", selection)
        self.assertIn("score_components", selection["targets"][0])
        self.assertIn("reason_codes", selection["targets"][0])

    def test_no_task_vocabulary_abstains_explicitly(self) -> None:
        selection = select_context_targets(
            str(self.root), self.project_map, goal="quantum orbital photon", limit=2
        )

        self.assertEqual(selection["targets"], [])
        self.assertTrue(selection["abstained"])
        self.assertEqual(selection["coverage"]["ratio"], 0.0)
        self.assertEqual(selection["abstention_reason"], "no_relevant_targets")

    def test_explicit_target_is_included_or_explained(self) -> None:
        included = select_context_targets(
            str(self.root), self.project_map, goal="unrelated vocabulary", target="src/modeling/sort_lines.py"
        )
        missing = select_context_targets(
            str(self.root), self.project_map, goal="unrelated vocabulary", target="src/missing.py"
        )

        self.assertIn("src/modeling/sort_lines.py", [row["path"] for row in included["targets"]])
        self.assertEqual(included["target_resolution"]["status"], "included")
        self.assertEqual(missing["target_resolution"]["status"], "missing")
        self.assertIn("does not exist", missing["target_resolution"]["reason"])

    def test_docs_query_can_select_docs_conditionally(self) -> None:
        selection = select_context_targets(
            str(self.root),
            self.project_map,
            goal="Update release notes documentation for dependency packaging",
            limit=1,
        )

        self.assertEqual(selection["targets"][0]["path"], "docs/release-notes.md")
        self.assertFalse(selection["abstained"])

    def test_query_changes_pack_hash_and_emits_relevance_metadata(self) -> None:
        selection = select_context_targets(
            str(self.root),
            self.project_map,
            goal="structural temporal modeling start date",
            task_fingerprint="task-planes",
        )
        first = build_context_pack(
            str(self.root),
            selection["targets"],
            project_map=self.project_map,
            symbol_index={"symbols": []},
            call_graph={"edges": []},
            goal="structural temporal modeling start date",
            task_fingerprint="task-planes",
            query_terms=selection["query_terms"],
            minimum_query_coverage=0.2,
        )
        second = build_context_pack(
            str(self.root),
            selection["targets"],
            project_map=self.project_map,
            symbol_index={"symbols": []},
            call_graph={"edges": []},
            goal="unrelated changed task",
            task_fingerprint="task-other",
            query_terms=["unrelated", "changed", "task"],
            minimum_query_coverage=0.2,
        )

        self.assertNotEqual(first["query_fingerprint"], second["query_fingerprint"])
        self.assertNotEqual(first["pack_hash"], second["pack_hash"])
        self.assertIn("relevance_score", first["files"][0])
        self.assertIn("relevance_reason", first["files"][0])
        self.assertIn("reason_codes", first["files"][0])
        self.assertIn("serialization_budget", first)
        self.assertIn("fidelity", first)
        self.assertFalse(first["needs_broader_context"])
        self.assertEqual(first["recent_changes"], [])

    def test_map_changes_pack_hash_even_when_selected_file_is_unchanged(self) -> None:
        selection = select_context_targets(
            str(self.root), self.project_map, goal="structural temporal modeling start date"
        )
        first = build_context_pack(
            str(self.root),
            selection["targets"],
            project_map=self.project_map,
            symbol_index={"symbols": []},
            call_graph={"edges": []},
            goal="structural temporal modeling start date",
            query_terms=selection["query_terms"],
        )
        changed_map = {**self.project_map, "dependencies": {"new": "dependency"}}
        second = build_context_pack(
            str(self.root),
            selection["targets"],
            project_map=changed_map,
            symbol_index={"symbols": []},
            call_graph={"edges": []},
            goal="structural temporal modeling start date",
            query_terms=selection["query_terms"],
        )
        self.assertNotEqual(first["map_fingerprint"], second["map_fingerprint"])
        self.assertNotEqual(first["pack_hash"], second["pack_hash"])

    def test_low_query_coverage_requires_broader_context(self) -> None:
        pack = build_context_pack(
            str(self.root),
            [
                {
                    "path": "src/modeling/sort_lines.py",
                    "relevance_score": 0.2,
                    "relevance_reason": "matched_terms=structural",
                    "matched_terms": ["structural"],
                    "recent_change_boost": False,
                }
            ],
            project_map=self.project_map,
            symbol_index={"symbols": []},
            call_graph={"edges": []},
            goal="structural temporal modeling plant start date alphabetic screen",
            query_terms=[
                "structural",
                "temporal",
                "modeling",
                "plant",
                "start",
                "date",
                "alphabetic",
                "screen",
            ],
            minimum_query_coverage=0.5,
        )

        self.assertTrue(pack["needs_broader_context"])
        self.assertIn("query coverage", pack["needs_broader_context_reason"])
        self.assertLess(pack["query_coverage"]["ratio"], 0.5)

    def test_declared_serialized_output_budget_fails_closed_without_requesting_broader_context(self) -> None:
        pack = build_context_pack(
            str(self.root),
            [
                {
                    "path": "src/modeling/sort_lines.py",
                    "relevance_score": 1.0,
                    "relevance_reason": "explicit_target; matched_terms=structural",
                    "matched_terms": ["structural"],
                    "recent_change_boost": False,
                    "score_components": {"explicit_target": 5.0},
                    "reason_codes": ["explicit_target", "matched_terms=structural"],
                }
            ],
            project_map=self.project_map,
            symbol_index={"symbols": []},
            call_graph={"edges": []},
            goal="Keep the serialized output budget 10 tokens",
            task_intent={"additional_information": ["serialized output budget 10"]},
            query_terms=["structural"],
        )

        receipt = pack["serialization_budget"]
        self.assertFalse(pack["needs_broader_context"])
        self.assertFalse(receipt["within_budget"])
        self.assertTrue(receipt["budget_exceeded"])
        self.assertEqual(receipt["status"], "required_context_exceeds_budget")
        self.assertGreater(receipt["required_minimum_token_budget"], 10)
        self.assertEqual(receipt["scope"], "context_pack")
        encoded = serialized_json_bytes(pack)
        self.assertEqual(receipt["serialized_bytes"], len(encoded))
        self.assertEqual(receipt["serialized_tokens"], serialized_token_count(pack))
        self.assertEqual(receipt["measurement"], "MEASURED")


class TaskAwareHandoffEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src/modeling").mkdir(parents=True)
        (self.root / "docs").mkdir()
        (self.root / "package.json").write_text('{"name": "planes-fixture"}', encoding="utf-8")
        (self.root / "src/modeling/sort_lines.py").write_text(
            "def sort_lines(lines):\n"
            "    # structural, temporal and modeling ordered by start date\n"
            "    # ordenacao de linhas: estrutural, temporal e modelagem por data de inicio\n"
            "    return sorted(lines)\n",
            encoding="utf-8",
        )
        (self.root / "docs/release-notes.md").write_text("old release notes\n", encoding="utf-8")
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["map", "--root", str(self.root), "--silent"]), 0)
        (self.root / "docs/release-notes.md").write_text("new packaging release only\n", encoding="utf-8")
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["scan", str(self.root), "--sync", "--json"]), 0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _handoff(self, goal: str, target: str = "") -> dict:
        output = StringIO()
        with redirect_stdout(output):
            code = _run_handoff(
                {
                    "root": str(self.root),
                    "out": ".simplicio",
                    "await": False,
                    "timeout": 0,
                    "json": True,
                    "for_llm": "",
                    "goal": goal,
                    "task_intent": None,
                    "task_fingerprint": "task-planes",
                    "target": target,
                    "minimum_query_coverage": 0.2,
                    "token_budget": 8000,
                    "limit": 8,
                }
            )
        self.assertEqual(code, 0)
        return json.loads(output.getvalue())

    def test_engine_emits_task_selection_metrics_and_query_keyed_pack(self) -> None:
        payload = self._handoff(
            "Order modeling lines: structural first, temporal and modeling by start date",
            "src/modeling/sort_lines.py",
        )

        self.assertTrue(payload["ready"])
        context_pack = _materialize(self.root, payload["context_pack"])
        selection = _materialize(self.root, payload["selection"])
        self.assertFalse(context_pack["needs_broader_context"])
        self.assertTrue(context_pack["serialization_budget"]["within_budget"])
        self.assertEqual(payload["targets"][0], "src/modeling/sort_lines.py")
        self.assertNotIn("docs/release-notes.md", payload["targets"])
        self.assertEqual(selection["target_resolution"]["status"], "included")
        self.assertEqual(payload["evidence"]["query_fingerprint"], context_pack["query_fingerprint"])
        self.assertGreaterEqual(payload["metrics"]["selection_latency_ms"], 0)
        self.assertGreater(payload["metrics"]["estimated_tokens"], 0)
        self.assertGreater(payload["metrics"]["precision_at_k"], 0)
        self.assertIn("token_budget_fit", selection)
        self.assertIn("fidelity", selection)
        self.assertEqual(
            payload["metrics"]["estimated_tokens"], selection["token_budget_fit"]["estimated_tokens"]
        )
        self.assertEqual(
            payload["metrics"]["tokens_estimation_method"], selection["token_budget_fit"]["tokenizer_policy"]
        )
        self.assertIn("stats", payload["status"]["cache"])
        self.assertIn("pack_diagnostics", payload["cache"])

    def test_final_json_envelope_is_measured_bounded_and_expandable(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            code = _run_handoff(
                {
                    "root": str(self.root),
                    "out": ".simplicio",
                    "await": False,
                    "timeout": 0,
                    "json": True,
                    "for_llm": "",
                    "goal": "Order modeling lines: structural first, temporal and modeling by start date",
                    "task_intent": None,
                    "task_fingerprint": "task-planes",
                    "target": "src/modeling/sort_lines.py",
                    "minimum_query_coverage": 0.2,
                    "token_budget": 8000,
                    "limit": 8,
                    "execution_context": True,
                }
            )
        self.assertEqual(code, 0)
        raw = output.getvalue()
        payload = json.loads(raw)
        receipt = payload["serialization_budget"]
        self.assertTrue(payload["ready"])
        self.assertTrue(receipt["within_budget"])
        self.assertLessEqual(receipt["serialized_tokens"], 8000)
        self.assertEqual(receipt["serialized_bytes"], len(raw.encode("utf-8")))
        self.assertEqual(receipt["serialized_tokens"], estimate_tokens(raw))
        self.assertEqual(receipt["scope"], "handoff_envelope")
        self.assertEqual(payload["gate_precedence"]["outcome"], "ready")
        self.assertFalse(payload["gate_precedence"]["gates"]["context_snapshot"]["mandatory"])
        for field in receipt["referenced_fields"]:
            reference = payload[field]
            artifact = self.root / reference["expansion_handle"]["path"]
            content = artifact.read_bytes()
            decoded = json.loads(content)
            canonical = serialized_json_bytes(decoded)
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), reference["canonical_sha256"])
            self.assertEqual(decoded["schema"], reference["referent_schema"])

    def test_engine_accepts_token_budget_and_limit_and_reports_budget_fit(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            code = _run_handoff(
                {
                    "root": str(self.root),
                    "out": ".simplicio",
                    "await": False,
                    "timeout": 0,
                    "json": True,
                    "for_llm": "",
                    "goal": "Order modeling lines: structural first, temporal and modeling by start date",
                    "task_intent": None,
                    "task_fingerprint": "task-planes",
                    "target": "src/modeling/sort_lines.py",
                    "minimum_query_coverage": 0.2,
                    "token_budget": 64,
                    "limit": 1,
                }
            )
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        selection = _summary(payload["selection"])
        self.assertEqual(selection["token_budget_fit"]["token_budget"], 64)
        self.assertTrue(selection["token_budget_fit"]["budget_exceeded"])
        self.assertFalse(selection["needs_broader_context"])
        self.assertFalse(payload["ready"])
        self.assertIn("budget_exceeded", payload["reason"])
        self.assertNotIn("needs_broader_context", payload["reason"])
        receipt = payload["serialization_budget"]
        self.assertEqual(receipt["scope"], "handoff_envelope")
        self.assertFalse(receipt["within_budget"])
        self.assertEqual(receipt["required_minimum_token_budget"], receipt["serialized_tokens"])
        self.assertEqual(selection["metrics"]["selected_count"], 1)

    def test_engine_abstains_when_repo_has_no_task_vocabulary(self) -> None:
        payload = self._handoff("quantum orbital photon")

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["targets"], [])
        selection = _materialize(self.root, payload["selection"])
        context_pack = _materialize(self.root, payload["context_pack"])
        self.assertTrue(selection["abstained"])
        self.assertIn("task_context_insufficient", payload["reason"])
        self.assertTrue(context_pack["needs_broader_context"])

    def test_cli_accepts_goal_task_file_fingerprint_and_target(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".task.md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(
                "Sistema: PLANES\nFuncionalidade: Ordenacao de linhas\n"
                "COMO analista QUERO estrutural primeiro e temporal/modelagem por data de inicio.\n"
                "RN01 - estrutural primeiro.\nRN02 - temporal e modelagem por data de inicio.\n"
            )
            task_file = Path(handle.name)
        self.addCleanup(task_file.unlink, missing_ok=True)
        output = StringIO()
        with redirect_stdout(output):
            try:
                code = main(
                    [
                        "handoff",
                        str(self.root),
                        "--task-file",
                        str(task_file),
                        "--task-fingerprint",
                        "task-planes-cli",
                        "--target",
                        "src/modeling/sort_lines.py",
                        "--token-budget",
                        "64",
                        "--json",
                    ]
                )
            except SystemExit as error:
                self.fail(f"task-aware handoff flags rejected with exit {error.code}")
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        context_pack = _summary(payload["context_pack"])
        selection = _summary(payload["selection"])
        self.assertFalse(payload["ready"])
        self.assertFalse(context_pack["needs_broader_context"])
        self.assertFalse(context_pack["serialization_budget"]["within_budget"])
        self.assertTrue(context_pack["serialization_budget"]["budget_exceeded"])
        self.assertFalse(selection["needs_broader_context"])
        self.assertEqual(selection["target_resolution"]["status"], "included")
        self.assertEqual(selection["token_budget_fit"]["token_budget"], 64)
        self.assertIn("required_context_exceeds_budget", payload["reason"])


if __name__ == "__main__":
    unittest.main()
