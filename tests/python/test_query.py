"""Unit tests for simplicio_mapper.query (F10 `ask`).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.query import ASK_SCHEMA, run_query  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class QueryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "ask-app", "main": "src/main.py"}))
        _write(
            self.dir,
            "src/main.py",
            "from src.writer import persist\n"
            "def main():\n"
            "    persist()\n",
        )
        _write(
            self.dir,
            "src/writer.py",
            "def persist():\n"
            "    with open('out.json', 'w') as handle:\n"
            "        handle.write('{}')\n",
        )
        _write(self.dir, "tests/test_writer.py", "from src.writer import persist\n\ndef test_persist():\n    persist()\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_callers_finds_call_site(self) -> None:
        payload = run_query(str(self.dir), verb="callers", arg="persist")
        self.assertEqual(payload["schema"], ASK_SCHEMA)
        self.assertGreaterEqual(payload["total"], 1)
        self.assertEqual(payload["results"][0]["source_file"], "src/main.py")

    def test_callees_of_main_includes_persist(self) -> None:
        payload = run_query(str(self.dir), verb="callees", arg="main")
        targets = {r["target_symbol"] for r in payload["results"]}
        self.assertTrue(any(t and "persist" in t for t in targets))

    def test_reaches_from_entry_file(self) -> None:
        payload = run_query(str(self.dir), verb="reaches", arg="src/main.py", depth=2)
        paths = {item["path"] for item in payload["results"]}
        self.assertIn("src/writer.py", paths)

    def test_impact_reports_affected_flow(self) -> None:
        payload = run_query(str(self.dir), verb="impact", arg="src/writer.py")
        self.assertIn("affected_flows", payload["results"])
        self.assertGreaterEqual(len(payload["results"]["affected_flows"]), 1)

    def test_tests_for_finds_matching_test_file(self) -> None:
        payload = run_query(str(self.dir), verb="tests-for", arg="src/writer.py")
        self.assertIn("tests/test_writer.py", payload["results"])

    def test_rules_without_business_index_notes_missing(self) -> None:
        payload = run_query(str(self.dir), verb="rules")
        self.assertEqual(payload["results"], [])
        self.assertIsNotNone(payload["note"])

    def test_unknown_verb_raises(self) -> None:
        with self.assertRaises(ValueError):
            run_query(str(self.dir), verb="bogus")

    def test_ask_command_end_to_end(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["ask", str(self.dir), "callers", "persist", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], ASK_SCHEMA)


if __name__ == "__main__":
    unittest.main()
