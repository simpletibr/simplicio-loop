from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.contract import validate_instance
from simplicio_mapper.retrieval_index import build_retrieval_index, write_retrieval_index
from simplicio_mapper.task_batch import TASK_BATCH_SCHEMA, build_task_batch
from simplicio_mapper.task_intent import parse_task_intent
from simplicio_mapper.task_traceability import apply_receipts, build_task_traceability


class TaskBatchAndTraceabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src/model.py").write_text("# structural temporal modeling ordering\n", encoding="utf-8")
        (self.root / "tests/test_model.py").write_text("def test_order(): pass\n", encoding="utf-8")
        self.project_map = {"files": [
            {"path": "src/model.py", "roles": ["frontend", "backend"]},
            {"path": "tests/test_model.py", "roles": ["test"]},
        ]}
        write_retrieval_index(str(self.root), ".simplicio", build_retrieval_index(self.project_map, root=str(self.root)))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_zero_target_batch_is_plan_only_and_topologically_stable(self) -> None:
        raw = {"tasks": [
            {"id": "b", "depends_on": ["a"], "task": "Funcionalidade: temporal modeling ordering"},
            {"id": "a", "task": "Funcionalidade: structural modeling ordering"},
        ]}
        batch = build_task_batch(str(self.root), raw, self.project_map)
        self.assertEqual(batch["schema"], TASK_BATCH_SCHEMA)
        self.assertEqual(batch["order"], ["a", "b"])
        self.assertFalse(batch["execution"]["executed"])
        self.assertTrue(all(task["selection"]["status"] != "abstained" for task in batch["tasks"]))

    def test_shared_candidate_is_conflict_not_parallel_permission(self) -> None:
        raw = ["Funcionalidade: modeling ordering", "Funcionalidade: modeling ordering"]
        batch = build_task_batch(str(self.root), raw, self.project_map)
        self.assertTrue(batch["shared_surfaces"])
        self.assertTrue(batch["conflicts"])

    def test_traceability_preserves_many_to_many_rules_and_never_fakes_verified(self) -> None:
        intent = parse_task_intent({
            "functionality": "modeling ordering",
            "acceptance_criteria": [
                {"id": "AC01", "title": "first", "given": [], "when": [], "then": [], "rule_ids": ["RN01", "RN02"]},
                {"id": "AC02", "title": "date", "given": [], "when": [], "then": [], "rule_ids": ["RN02"]},
            ],
            "business_rules": [{"id": "RN01", "description": "structural first"}, {"id": "RN02", "description": "date order"}],
        })
        trace = build_task_traceability(str(self.root), intent, context_pack={"files": [{"path": "src/model.py", "symbols": [], "tests": ["tests/test_model.py"]}]})
        self.assertEqual([entry["rule_ids"] for entry in trace["criteria"]], [["RN01", "RN02"], ["RN02"]])
        self.assertEqual(trace["criteria"][0]["execution_status"], "pending")
        self.assertIn("no prototype declared", trace["gaps"])
        self.assertFalse(trace["complete"])

    def test_stale_receipt_is_blocked(self) -> None:
        intent = parse_task_intent({"acceptance_criteria": [{"id": "AC01", "title": "x"}], "business_rules": []})
        trace = build_task_traceability(str(self.root), intent, context_pack={"files": [{"path": "src/model.py"}]})
        receipt = {"criterion_id": "AC01", "receipt_id": "r1", "status": "verified", "command": "pytest", "evidence": [{"path": "src/model.py", "hash": "stale"}]}
        apply_receipts(trace, [receipt], root=str(self.root))
        self.assertEqual(trace["criteria"][0]["execution_status"], "blocked")
        self.assertFalse(trace["complete"])

    def test_versioned_schemas_validate_golden_shapes(self) -> None:
        root = Path(__file__).resolve().parents[2] / "contracts/task-orientation/v1"
        for name in ("task-batch", "task-traceability"):
            schema = json.loads((root / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
            if name == "task-batch":
                payload = build_task_batch(str(self.root), ["Funcionalidade: modeling ordering"], self.project_map)
            else:
                payload = build_task_traceability(str(self.root), parse_task_intent("Funcionalidade: modeling ordering"), context_pack={"files": []})
            self.assertEqual(validate_instance(payload, schema), [])


if __name__ == "__main__":
    unittest.main()
