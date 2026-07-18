"""Tests for simplicio_mapper/prototype_context.py + the
`simplicio-mapper prototype-context` CLI subcommand (issue #286, Phase-0
bounded context pack for Prototype-First; see
`simplicio_mapper/prototype_context.py` module docstring for the explicit
scope boundary against the full epic).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.prototype_context import (  # noqa: E402
    ALLOWED_TYPES,
    PROTOTYPE_CONTEXT_SCHEMA,
    PrototypeContextError,
    _negative_space,
    _precedent_candidates,
    _truncate_to_budget,
    build_prototype_context,
    run_prototype_context_cli,
)


def _write_fixture(root: str) -> None:
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    os.makedirs(os.path.join(root, "tests"), exist_ok=True)
    with open(os.path.join(root, "src", "app.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "def greet(name):\n"
            "    return f'hello {name}'\n"
            "\n"
            "def main():\n"
            "    print(greet('world'))\n"
        )
    with open(os.path.join(root, "src", "util.py"), "w", encoding="utf-8") as handle:
        handle.write("def unrelated():\n    return 1\n")
    with open(os.path.join(root, "tests", "test_app.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "from src.app import greet\n"
            "\n"
            "def test_greet():\n"
            "    assert greet('world') == 'hello world'\n"
        )
    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as handle:
        handle.write("# fixture\n")


class BuildPrototypeContextTest(unittest.TestCase):
    """Unit + integration: `build_prototype_context()` over a real fixture repo."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _write_fixture(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_unknown_type_raises(self) -> None:
        with self.assertRaises(PrototypeContextError):
            build_prototype_context(self.root, type_="not-a-type", arg="src/app.py")

    def test_empty_arg_raises(self) -> None:
        with self.assertRaises(PrototypeContextError):
            build_prototype_context(self.root, type_="bug", arg="")

    def test_every_allowed_type_is_accepted(self) -> None:
        for type_ in ALLOWED_TYPES:
            payload = build_prototype_context(self.root, type_=type_, arg="src/app.py")
            self.assertEqual(payload["type"], type_)

    def test_schema_and_shape(self) -> None:
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        self.assertEqual(payload["schema"], PROTOTYPE_CONTEXT_SCHEMA)
        for key in (
            "type",
            "query",
            "target_files",
            "affected_symbols",
            "affected_flows",
            "affected_tests",
            "needs_review",
            "negative_space",
            "precedents",
            "precedents_note",
            "skeletons",
            "skeletons_note",
            "token_budget",
            "tokens_estimated",
            "truncated",
            "omitted_counts",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["skeletons"][0]["type"], "failing_test")
        self.assertIn("context_hash", payload)

    def test_precedents_are_shaped_with_confidence_and_provenance(self) -> None:
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        for entry in payload["precedents"]:
            self.assertIn("precedent_id", entry)
            self.assertIn("path", entry)
            self.assertIn("confidence", entry)
            self.assertIsInstance(entry["confidence"], int)
            self.assertEqual(entry["provenance"], "local-keyword-overlap:precedent-index")

    def test_precedents_never_calls_native_runtime(self) -> None:
        # The `precedents` field is documented (module docstring + ADR-012
        # addendum) as local-only -- unlike `ask precedent`, it must never
        # shell out to the native `simplicio` runtime binary.
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        for entry in payload["precedents"]:
            self.assertNotEqual(entry["provenance"], "runtime-ask-precedent")

    def test_resolves_existing_path_directly(self) -> None:
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        self.assertEqual(payload["target_files"], ["src/app.py"])
        self.assertEqual(payload["query"]["resolution"], "resolved-as-path")

    def test_resolves_symbol_name_to_defining_file(self) -> None:
        payload = build_prototype_context(self.root, type_="ui", arg="greet")
        self.assertEqual(payload["target_files"], ["src/app.py"])
        self.assertEqual(payload["query"]["resolution"], "resolved-as-symbol")

    def test_unresolved_argument_falls_back_to_literal(self) -> None:
        payload = build_prototype_context(self.root, type_="api", arg="does/not/exist.py")
        self.assertEqual(payload["target_files"], ["does/not/exist.py"])
        self.assertEqual(payload["query"]["resolution"], "unresolved-literal")

    def test_finds_related_test_file(self) -> None:
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        self.assertIn("tests/test_app.py", payload["affected_tests"])

    def test_negative_space_excludes_touched_dirs(self) -> None:
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        # src/ (target) and tests/ (a found test) must never appear in
        # negative_space; an untouched top-level file (README.md) may.
        for path in payload["negative_space"]:
            self.assertFalse(path.startswith("src/"))
            self.assertFalse(path.startswith("tests/"))

    def test_limit_bounds_result_lists(self) -> None:
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py", limit=1)
        self.assertLessEqual(len(payload["affected_symbols"]), 1)
        self.assertLessEqual(len(payload["affected_tests"]), 1)
        self.assertLessEqual(len(payload["negative_space"]), 1)
        self.assertLessEqual(len(payload["precedents"]), 1)

    def test_generous_budget_is_not_truncated(self) -> None:
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py", token_budget=1_000_000)
        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["omitted_counts"], {})

    def test_tiny_budget_truncates_and_reports_omissions(self) -> None:
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py", token_budget=1)
        self.assertTrue(payload["truncated"])
        self.assertTrue(any(count > 0 for count in payload["omitted_counts"].values()))
        # never silently drops the schema/type identity fields
        self.assertEqual(payload["schema"], PROTOTYPE_CONTEXT_SCHEMA)
        self.assertEqual(payload["type"], "bug")


class NegativeSpaceHelperTest(unittest.TestCase):
    """Unit: `_negative_space()` in isolation (no repo build needed)."""

    def test_excludes_top_level_dirs_of_touched_paths(self) -> None:
        project_map = {
            "files": [
                {"path": "src/app.py"},
                {"path": "src/util.py"},
                {"path": "docs/readme.md"},
                {"path": "tests/test_app.py"},
            ]
        }
        result = _negative_space(project_map, ["src/app.py"], {"src/app.py"}, limit=10)
        self.assertIn("docs/readme.md", result)
        self.assertIn("tests/test_app.py", result)
        self.assertNotIn("src/app.py", result)
        self.assertNotIn("src/util.py", result)

    def test_respects_limit(self) -> None:
        project_map = {"files": [{"path": f"docs/{i}.md"} for i in range(5)]}
        result = _negative_space(project_map, [], set(), limit=2)
        self.assertEqual(len(result), 2)

    def test_skips_entries_without_a_path(self) -> None:
        project_map = {"files": [{"path": "docs/a.md"}, {"no_path_field": True}, {"path": ""}]}
        result = _negative_space(project_map, [], set(), limit=10)
        self.assertEqual(result, ["docs/a.md"])


class PrecedentCandidatesHelperTest(unittest.TestCase):
    """Unit: `_precedent_candidates()` in isolation (issue #286 step 6
    follow-up -- crafted precedent-index items, no repo build needed)."""

    def setUp(self) -> None:
        self.items = [
            {
                "id": "p1",
                "path": "src/orders/checkout.py",
                "summary": "checkout flow precedent",
                "tags": ["checkout", "orders", "python"],
            },
            {
                "id": "p2",
                "path": "src/billing/invoice.py",
                "summary": "invoice generation precedent",
                "tags": ["billing", "invoice", "python"],
            },
            {
                "id": "p3",
                "path": "src/unrelated/misc.py",
                "summary": "unrelated helper",
                "tags": ["misc"],
            },
        ]

    def test_ranks_by_keyword_overlap(self) -> None:
        candidates = _precedent_candidates(self.items, "checkout orders flow", limit=5)
        self.assertTrue(candidates)
        self.assertEqual(candidates[0]["precedent_id"], "p1")

    def test_every_candidate_has_confidence_and_provenance(self) -> None:
        candidates = _precedent_candidates(self.items, "checkout billing", limit=5)
        for entry in candidates:
            self.assertGreaterEqual(entry["confidence"], 1)
            self.assertEqual(entry["provenance"], "local-keyword-overlap:precedent-index")

    def test_no_overlap_returns_no_candidates(self) -> None:
        candidates = _precedent_candidates(self.items, "completely nonmatching query text", limit=5)
        self.assertEqual(candidates, [])

    def test_respects_limit(self) -> None:
        candidates = _precedent_candidates(self.items, "python precedent", limit=1)
        self.assertLessEqual(len(candidates), 1)

    def test_empty_query_text_returns_no_candidates(self) -> None:
        candidates = _precedent_candidates(self.items, "", limit=5)
        self.assertEqual(candidates, [])

    def test_carries_summary_and_tags_through(self) -> None:
        candidates = _precedent_candidates(self.items, "checkout", limit=5)
        entry = next(c for c in candidates if c["precedent_id"] == "p1")
        self.assertEqual(entry["path"], "src/orders/checkout.py")
        self.assertEqual(entry["summary"], "checkout flow precedent")
        self.assertIn("checkout", entry["tags"])


class TruncateToBudgetTest(unittest.TestCase):
    """Unit: `_truncate_to_budget()` in isolation."""

    def test_under_budget_untouched(self) -> None:
        payload = {"affected_symbols": [1, 2, 3], "affected_tests": [], "needs_review": [], "negative_space": []}
        result = _truncate_to_budget(dict(payload), token_budget=10_000)
        self.assertEqual(result["affected_symbols"], [1, 2, 3])
        self.assertFalse(result["truncated"])

    def test_over_budget_trims_largest_field_first(self) -> None:
        payload = {
            "affected_symbols": list(range(100)),
            "affected_tests": ["a"],
            "needs_review": [],
            "negative_space": [],
        }
        result = _truncate_to_budget(dict(payload), token_budget=5)
        self.assertLess(len(result["affected_symbols"]), 100)
        self.assertEqual(result["affected_tests"], ["a"])
        self.assertTrue(result["truncated"])
        self.assertIn("affected_symbols", result["omitted_counts"])

    def test_never_raises_when_budget_unreachable(self) -> None:
        payload = {"affected_symbols": [1], "affected_tests": [], "needs_review": [], "negative_space": []}
        result = _truncate_to_budget(dict(payload), token_budget=0)
        self.assertTrue(result["truncated"] or result["tokens_estimated"] >= 0)


class RunPrototypeContextCliTest(unittest.TestCase):
    """Integration: `run_prototype_context_cli()` argv parsing + exit codes."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _write_fixture(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_json_output_round_trips(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = run_prototype_context_cli([self.root, "--type", "bug", "--arg", "src/app.py", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["schema"], PROTOTYPE_CONTEXT_SCHEMA)

    def test_human_output_is_non_json(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = run_prototype_context_cli([self.root, "--type", "bug", "--arg", "src/app.py"])
        self.assertEqual(code, 0)
        self.assertIn("type:", buf.getvalue())

    def test_positional_arg_after_root(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = run_prototype_context_cli([self.root, "greet", "--type", "ui", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["target_files"], ["src/app.py"])

    def test_unknown_type_exits_nonzero(self) -> None:
        code = run_prototype_context_cli([self.root, "--type", "nope", "--arg", "src/app.py"])
        self.assertEqual(code, 1)

    def test_missing_arg_exits_nonzero(self) -> None:
        code = run_prototype_context_cli([self.root, "--type", "bug"])
        self.assertEqual(code, 1)

    def test_bad_limit_exits_two(self) -> None:
        code = run_prototype_context_cli([self.root, "--type", "bug", "--arg", "src/app.py", "--limit", "x"])
        self.assertEqual(code, 2)

    def test_bad_token_budget_exits_two(self) -> None:
        code = run_prototype_context_cli(
            [self.root, "--type", "bug", "--arg", "src/app.py", "--token-budget", "x"]
        )
        self.assertEqual(code, 2)

    def test_valid_limit_and_token_budget_flags_are_applied(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = run_prototype_context_cli(
                [
                    self.root,
                    "--type",
                    "bug",
                    "--arg",
                    "src/app.py",
                    "--limit",
                    "1",
                    "--token-budget",
                    "50000",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["token_budget"], 50000)
        self.assertLessEqual(len(payload["affected_symbols"]), 1)


class CliDispatchTest(unittest.TestCase):
    """System: dispatch through `simplicio_mapper.cli.main()`, the real entry point."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _write_fixture(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_main_dispatches_prototype_context(self) -> None:
        buf = StringIO()
        with redirect_stdout(buf):
            code = main(["prototype-context", self.root, "--type", "workflow", "--arg", "src/app.py", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["schema"], PROTOTYPE_CONTEXT_SCHEMA)
        self.assertEqual(payload["type"], "workflow")


if __name__ == "__main__":
    unittest.main()
