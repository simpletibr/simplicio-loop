from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from simplicio_mapper.cli import main
from simplicio_mapper.contract import validate_instance
from simplicio_mapper.orient import build_orientation
from simplicio_mapper.retrieval_index import build_retrieval_index, write_retrieval_index
from simplicio_mapper.toon import decode_toon


class OrientContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".simplicio").mkdir()
        (self.root / "src").mkdir()
        (self.root / "src/order_lines.py").write_text(
            "def order_lines(lines):\n"
            "    # structural first, then temporal/modeling by start date\n"
            "    return sorted(lines)\n",
            encoding="utf-8",
        )
        (self.root / "docs.md").write_text("unrelated release notes\n", encoding="utf-8")
        project_map = {
            "schema": "simplicio.project-map/v1",
            "files": [
                {"path": "src/order_lines.py", "importance": 0.4},
                {"path": "docs.md", "importance": 0.9},
            ],
        }
        (self.root / ".simplicio/project-map.json").write_text(
            json.dumps(project_map),
            encoding="utf-8",
        )
        # `build_orientation` -> `select_context_targets` only does
        # content-aware (not just path/metadata) matching against a
        # *persisted* retrieval index (the warm path populated by the real
        # `scan`/`index` CLI flow) -- a cold, unindexed call is deliberately
        # metadata-only so an ad hoc query never has to reopen every
        # candidate file body (see retrieval_index.py::select_context_targets
        # and test_task_context_selection.py's
        # test_selector_does_not_open_irrelevant_candidate_files). Persist
        # a real retrieval index here so this test exercises the supported
        # warm path instead of asserting content-match behavior that the
        # cold path intentionally does not provide.
        write_retrieval_index(
            str(self.root), ".simplicio", build_retrieval_index(project_map, root=str(self.root))
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_orientation_is_stable_and_has_existing_line_evidence(self) -> None:
        task = {"system": "PLANES", "functionality": "temporal"}
        first = build_orientation(str(self.root), task)
        second = build_orientation(str(self.root), task)
        self.assertEqual(first, second)
        self.assertFalse(first["needs_broader_context"])
        self.assertEqual(first["candidates"][0]["path"], "src/order_lines.py")
        candidate = first["candidates"][0]
        self.assertGreaterEqual(candidate["line"], 1)
        self.assertTrue((self.root / candidate["evidence"]["path"]).is_file())
        self.assertEqual(validate_instance(first, {
            "$id": "simplicio.task-context/v1",
            "type": "object",
            "required": ["schema", "task", "map", "result_fingerprint", "candidates", "needs_broader_context", "gaps"],
            "properties": {"schema": {"enum": ["simplicio.task-context/v1"]}},
        }), [])

    def test_unmatched_task_abstains_with_explicit_gap(self) -> None:
        payload = build_orientation(str(self.root), "quantum orbital photon")
        self.assertTrue(payload["needs_broader_context"])
        self.assertEqual(payload["candidates"], [])
        self.assertTrue(payload["gaps"])

    def test_stdin_json_and_toon_have_semantic_parity(self) -> None:
        task = json.dumps({"system": "PLANES", "functionality": "Order lines"})
        stdin_output = StringIO()
        with patch("sys.stdin", StringIO(task)), redirect_stdout(stdin_output):
            self.assertEqual(main(["orient", str(self.root), "--stdin", "--json"]), 0)
        task_file = self.root / "task.json"
        task_file.write_text(task, encoding="utf-8")
        file_output = StringIO()
        with redirect_stdout(file_output):
            self.assertEqual(main(["orient", str(self.root), "--task-json", str(task_file), "--json"]), 0)
        default_output = StringIO()
        with redirect_stdout(default_output):
            self.assertEqual(main(["orient", str(self.root), "--task-json", str(task_file)]), 0)
        toon_output = StringIO()
        with redirect_stdout(toon_output):
            self.assertEqual(
                main(["orient", str(self.root), "--task-json", str(task_file), "--for-llm", "toon"]), 0
            )
        expected = json.loads(file_output.getvalue())
        default_text = default_output.getvalue()
        default_payload = (
            decode_toon(default_text)
            if not default_text.lstrip().startswith("{")
            else json.loads(default_text)
        )
        self.assertEqual(expected, default_payload)
        self.assertEqual(expected, decode_toon(toon_output.getvalue()))
        self.assertEqual(expected, json.loads(stdin_output.getvalue()))
        self.assertEqual(expected, json.loads(file_output.getvalue()))
        self.assertEqual(json.loads(stdin_output.getvalue()), json.loads(file_output.getvalue()))


if __name__ == "__main__":
    unittest.main()
