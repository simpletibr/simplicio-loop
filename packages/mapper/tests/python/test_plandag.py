"""Tests for PlanDAG, understand, and plan commands (Issue #654).

Covers:
- understand(task): extracts terms, ranks symbols via snapshot mmap and
  SemanticScorer, generates ContextSpans with source_sha256 and budget limits.
- plan(task): generates the PlanDAG (schema simplicio.fast.plandag/v2),
  structured in nodes orient -> modify -> validate -> refresh, bound to
  ContextHandles and detecting project test commands (pytest, npm test, etc.).
- CLI: simplicio-mapper understand <task> and simplicio-mapper plan <task>.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main
from simplicio_mapper.processor import (
    ProjectProcessor,
    Understanding,
    plan,
    understand,
)
from simplicio_mapper.store.snapshot import ContextSpan


def _write_file(root: Path, rel_path: str, content: str) -> Path:
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class PlanDAGTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name).resolve()
        self.snapshot_path = self.root / ".simplicio" / "fast" / "project.sfast"

        # Create a sample project structure
        _write_file(
            self.root,
            "payment_service.py",
            "class PaymentService:\n"
            "    def process_payment(self, amount: float) -> bool:\n"
            "        if amount <= 0:\n"
            "            return False\n"
            "        return True\n"
            "\n"
            "    def refund_payment(self, transaction_id: str) -> bool:\n"
            "        return True\n",
        )
        _write_file(
            self.root,
            "models.py",
            "class PaymentRecord:\n"
            "    def __init__(self, record_id: str, amount: float) -> None:\n"
            "        self.record_id = record_id\n"
            "        self.amount = amount\n",
        )
        _write_file(
            self.root,
            "audit_logger.py",
            "def log_audit_event(event_name: str, payload: dict) -> None:\n"
            "    print(f'AUDIT: {event_name}')\n",
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_understand_extracts_terms_and_ranks_symbols(self) -> None:
        processor = ProjectProcessor(self.root, self.snapshot_path)
        task = "process payment and refund through payment service"

        res = processor.understand(task)
        self.assertIsInstance(res, Understanding)
        self.assertEqual("simplicio.fast.understanding/v2", res.schema)
        self.assertEqual(task, res.task)

        # Check terms extracted (no stop words like 'and', 'through')
        self.assertIn("payment", res.terms)
        self.assertIn("service", res.terms)
        self.assertNotIn("and", res.terms)
        self.assertNotIn("through", res.terms)

        # Check files and symbols found
        self.assertIn("payment_service.py", res.files)
        self.assertTrue(any("PaymentService" in sym or "process_payment" in sym for sym in res.symbols))

        # Check ContextSpans have source_sha256
        self.assertTrue(res.context)
        for span in res.context:
            self.assertIsInstance(span, ContextSpan)
            source_file = self.root / span.file
            expected_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
            self.assertEqual(expected_hash, span.source_sha256)

        # Check selection receipt
        self.assertIn("selection_mode", res.selection)
        self.assertEqual("simplicio.fast.semantic-ranking-receipt/v1", res.selection["schema"])

    def test_understand_respects_budget_limits(self) -> None:
        processor = ProjectProcessor(self.root, self.snapshot_path)
        task = "payment service"

        # Very restrictive budget
        res = processor.understand(task, max_results=1, max_bytes=200)
        self.assertLessEqual(len(res.context), 1)
        total_bytes = sum(len(span.content.encode("utf-8")) for span in res.context)
        self.assertLessEqual(total_bytes, 200)

    def test_standalone_understand_function(self) -> None:
        res = understand("payment service", root=self.root, snapshot_path=self.snapshot_path)
        self.assertIsInstance(res, Understanding)
        self.assertEqual("simplicio.fast.understanding/v2", res.schema)
        self.assertIn("payment_service.py", res.files)

    def test_plan_dag_structure_and_nodes(self) -> None:
        processor = ProjectProcessor(self.root, self.snapshot_path)
        task = "update payment service logic"

        plan_dag = processor.plan(task)
        self.assertEqual("simplicio.fast.plandag/v2", plan_dag["schema"])
        self.assertEqual(task, plan_dag["task"])
        self.assertEqual(str(self.root), plan_dag["root"])

        # Check 4 structured nodes: orient -> modify -> validate -> refresh
        node_ids = [node["id"] for node in plan_dag["nodes"]]
        self.assertEqual(["orient", "modify", "validate", "refresh"], node_ids)

        nodes_by_id = {node["id"]: node for node in plan_dag["nodes"]}

        # Orient node
        orient = nodes_by_id["orient"]
        self.assertEqual("context", orient["kind"])
        self.assertEqual([], orient["depends_on"])
        self.assertIn("context_handles", orient["inputs"])
        self.assertIn("source_hashes", orient["inputs"])

        # Modify node
        modify = nodes_by_id["modify"]
        self.assertEqual("structured_patch", modify["kind"])
        self.assertEqual(["orient"], modify["depends_on"])
        self.assertEqual("simplicio.fast.changeset/v2", modify["inputs"]["format"])
        self.assertIn("allowed_files", modify["inputs"])
        self.assertIn("context_handles", modify["inputs"])

        # Validate node
        validate = nodes_by_id["validate"]
        self.assertEqual("command_gate", validate["kind"])
        self.assertEqual(["modify"], validate["depends_on"])
        self.assertIn("commands", validate["inputs"])

        # Refresh node
        refresh = nodes_by_id["refresh"]
        self.assertEqual("snapshot_refresh", refresh["kind"])
        self.assertEqual(["validate"], refresh["depends_on"])
        self.assertIn("snapshot", refresh["inputs"])

        # Context handles bound to planDAG and understanding
        handles = plan_dag["context_handles"]
        self.assertTrue(handles)
        self.assertEqual(handles, plan_dag["understanding"]["context_handles"])
        for h in handles:
            self.assertIn("handle", h)
            self.assertIn("generation", h)
            self.assertIn("base_generation", h)
            self.assertIn("source_sha256", h)
            self.assertEqual(64, len(h["source_sha256"]))

    def test_plan_detects_project_test_commands(self) -> None:
        # Case A: Pytest configured via pyproject.toml
        _write_file(
            self.root,
            "pyproject.toml",
            "[tool.pytest.ini_options]\naddopts = '-q'\n",
        )
        proc_pytest = ProjectProcessor(self.root, self.snapshot_path)
        plan_pytest = proc_pytest.plan("payment")
        val_node = next(n for n in plan_pytest["nodes"] if n["id"] == "validate")
        self.assertIn(["pytest"], val_node["inputs"]["commands"])

        # Case B: npm test configured via package.json
        _write_file(
            self.root,
            "package.json",
            json.dumps({"name": "app", "scripts": {"test": "jest"}}),
        )
        plan_npm = proc_pytest.plan("payment")
        val_node_npm = next(n for n in plan_npm["nodes"] if n["id"] == "validate")
        self.assertIn(["npm", "test"], val_node_npm["inputs"]["commands"])

        # Case C: cargo test configured via Cargo.toml
        _write_file(self.root, "Cargo.toml", "[package]\nname = 'rust_app'\n")
        plan_cargo = proc_pytest.plan("payment")
        val_node_cargo = next(n for n in plan_cargo["nodes"] if n["id"] == "validate")
        self.assertIn(["cargo", "test"], val_node_cargo["inputs"]["commands"])

    def test_plan_fallback_validation_commands(self) -> None:
        # Empty project with no configs
        empty_tmp = tempfile.TemporaryDirectory()
        try:
            empty_root = Path(empty_tmp.name).resolve()
            _write_file(empty_root, "dummy.py", "x = 1\n")
            proc = ProjectProcessor(empty_root, empty_root / "snap.sfast")
            commands = proc._validation_commands()
            self.assertEqual([["python", "-m", "compileall", "-q", "."]], commands)

            # With tests/ directory
            _write_file(empty_root, "tests/test_dummy.py", "pass\n")
            commands_with_tests = proc._validation_commands()
            self.assertEqual(
                [["python", "-m", "unittest", "discover", "-s", "tests", "-v"]],
                commands_with_tests,
            )
        finally:
            empty_tmp.cleanup()

    def test_standalone_plan_function(self) -> None:
        plan_res = plan("payment service", root=self.root, snapshot_path=self.snapshot_path)
        self.assertEqual("simplicio.fast.plandag/v2", plan_res["schema"])
        self.assertTrue(plan_res["nodes"])

    def test_cli_understand_and_plan(self) -> None:
        # Test CLI: simplicio-mapper understand <task>
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["understand", "payment service", "--root", str(self.root)])
        self.assertEqual(0, exit_code, stderr.getvalue())
        data = json.loads(stdout.getvalue())
        self.assertEqual("simplicio.fast.understanding/v2", data["schema"])
        self.assertIn("payment_service.py", data["files"])

        # Test CLI: simplicio-mapper plan <task>
        stdout_plan = StringIO()
        stderr_plan = StringIO()
        with redirect_stdout(stdout_plan), redirect_stderr(stderr_plan):
            exit_code_plan = main(["plan", "payment service", "--root", str(self.root)])
        self.assertEqual(0, exit_code_plan, stderr_plan.getvalue())
        plan_data = json.loads(stdout_plan.getvalue())
        self.assertEqual("simplicio.fast.plandag/v2", plan_data["schema"])
        self.assertEqual(["orient", "modify", "validate", "refresh"], [n["id"] for n in plan_data["nodes"]])


if __name__ == "__main__":
    unittest.main()
