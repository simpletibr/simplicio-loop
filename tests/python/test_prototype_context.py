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
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.prototype_context import (  # noqa: E402
    ALLOWED_TYPES,
    PROTOTYPE_CONTEXT_SCHEMA,
    PrototypeContextError,
    _is_forbidden_context_path,
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
            "def greet(name):\n    return f'hello {name}'\n\ndef main():\n    print(greet('world'))\n"
        )
    with open(os.path.join(root, "src", "util.py"), "w", encoding="utf-8") as handle:
        handle.write("def unrelated():\n    return 1\n")
    with open(os.path.join(root, "tests", "test_app.py"), "w", encoding="utf-8") as handle:
        handle.write(
            "from src.app import greet\n\ndef test_greet():\n    assert greet('world') == 'hello world'\n"
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
            "precedents_delegation",
            "precedents_note",
            "skeletons",
            "skeletons_note",
            "token_budget",
            "tokens_estimated",
            "truncated",
            "omitted_counts",
            "source_binding",
            "canonical_reuse",
            "excluded_context",
            "measurements",
            "budget_policy",
            "context_hash_algorithm",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["skeletons"][0]["type"], "failing_test")
        self.assertIn("context_hash", payload)
        self.assertEqual(payload["context_hash_algorithm"], "sha256:canonical-json-without-context_hash")

    def test_precedents_are_shaped_with_confidence_and_provenance(self) -> None:
        with mock.patch("simplicio_mapper.query.shutil.which", return_value=None):
            payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        for entry in payload["precedents"]:
            self.assertIn("precedent_id", entry)
            self.assertIn("path", entry)
            self.assertIn("confidence", entry)
            self.assertIsInstance(entry["confidence"], int)
            self.assertEqual(entry["provenance"], "local-keyword-overlap:precedent-index")

    def test_precedents_fall_back_to_local_when_native_runtime_absent(self) -> None:
        # No `simplicio` runtime binary is installed in this test environment
        # (and shutil.which is mocked out to guarantee that regardless of the
        # host), so the native-first `precedents` field (issue #286 step 6)
        # must fall back to the local keyword-overlap ranking, and label it
        # honestly via `provenance` and `precedents_delegation`.
        with mock.patch("simplicio_mapper.query.shutil.which", return_value=None):
            payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        for entry in payload["precedents"]:
            self.assertEqual(entry["provenance"], "local-keyword-overlap:precedent-index")
        self.assertFalse(payload["precedents_delegation"]["used"])
        self.assertEqual(payload["precedents_delegation"]["runtime"], "simplicio-runtime")

    def test_precedents_use_native_runtime_when_available(self) -> None:
        # Same native-first delegation path `ask precedent` uses
        # (`query._runtime_precedent_search`): when the runtime binary is
        # present and its response validates, the envelope must use it
        # instead of the local fallback, and label every candidate with a
        # genuine native provenance/confidence (never presented as a local
        # keyword-overlap count).
        native_payload = {
            "schema": "simplicio.precedent-search/v1",
            "candidates": [
                {
                    "precedent_id": "p1",
                    "path": "src/app.py",
                    "summary": "greet precedent",
                    "tags": ["greet"],
                    "score": 0.87,
                    "reuse_level": "high",
                    "suggested_next_action": "reuse as-is",
                }
            ],
        }
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(native_payload))
        with (
            mock.patch("simplicio_mapper.query.shutil.which", return_value="/usr/local/bin/simplicio"),
            mock.patch("simplicio_mapper.query._validated_runtime_binary", return_value=(True, "validated")),
            mock.patch("simplicio_mapper.query.subprocess.run", return_value=completed),
        ):
            payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        self.assertTrue(payload["precedents_delegation"]["used"])
        self.assertEqual(payload["precedents_delegation"]["runtime"], "simplicio-runtime")
        self.assertTrue(payload["precedents"])
        entry = payload["precedents"][0]
        self.assertEqual(entry["precedent_id"], "p1")
        self.assertEqual(entry["provenance"], "runtime-precedent-search")
        self.assertEqual(entry["confidence"], 0.87)
        self.assertEqual(entry["reuse_level"], "high")

    def test_precedents_fall_back_on_native_runtime_failure(self) -> None:
        # Non-zero exit from a present-but-broken binary must still fall
        # back honestly, never fake a native pass.
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with (
            mock.patch("simplicio_mapper.query.shutil.which", return_value="/usr/local/bin/simplicio"),
            mock.patch("simplicio_mapper.query._validated_runtime_binary", return_value=(True, "validated")),
            mock.patch("simplicio_mapper.query.subprocess.run", return_value=completed),
        ):
            payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        self.assertFalse(payload["precedents_delegation"]["used"])
        self.assertEqual(payload["precedents_delegation"]["reason"], "command_failed")
        for entry in payload["precedents"]:
            self.assertEqual(entry["provenance"], "local-keyword-overlap:precedent-index")

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

    def test_context_pack_is_bound_to_source_and_affected_shards(self) -> None:
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        binding = payload["source_binding"]
        self.assertRegex(binding["source_sha"], r"^[0-9a-f]{40,64}$")
        self.assertIn("src", binding["affected_shards"])
        self.assertIn("tests", binding["affected_shards"])
        self.assertEqual(binding["invalidation"], "invalidate-only-listed-shards-on-source-drift")

    def test_measurements_compare_full_remap_and_extraction(self) -> None:
        payload = build_prototype_context(self.root, type_="benchmark", arg="src/app.py")
        measurements = payload["measurements"]
        self.assertGreaterEqual(measurements["full_remap_seconds"], 0)
        self.assertGreaterEqual(measurements["prototype_extraction_seconds"], 0)
        self.assertEqual(
            measurements["comparison"],
            "full-remap-build-artifacts-vs-prototype-context-extraction",
        )

    def test_secret_and_binary_paths_are_excluded_from_context(self) -> None:
        payload = build_prototype_context(self.root, type_="bug", arg="src/app.py")
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn(".env", serialized)
        self.assertNotIn("secret-plan.md", serialized)
        self.assertNotIn("image.png", serialized)
        self.assertTrue(payload["excluded_context"]["paths"] or payload["excluded_context"]["policy"])

    def test_forbidden_target_is_rejected(self) -> None:
        with self.assertRaises(PrototypeContextError):
            build_prototype_context(self.root, type_="bug", arg=".env")

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


class ForbiddenContextPathTest(unittest.TestCase):
    """Unit: path-only exclusion policy for secret/binary context."""

    def test_rejects_common_secret_and_binary_paths(self) -> None:
        for path in (".env", ".env.local", "config/secrets.yml", "id_rsa", "assets/logo.png"):
            self.assertTrue(_is_forbidden_context_path(path), path)

    def test_allows_normal_source_and_docs_paths(self) -> None:
        for path in ("src/app.py", "tests/test_app.py", "docs/readme.md"):
            self.assertFalse(_is_forbidden_context_path(path), path)


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
    """Unit: `_precedent_candidates()` in isolation (issue #286 step 6,
    native-first delegation with local fallback -- crafted precedent-index
    items, no repo build needed). The native `simplicio` runtime binary is
    explicitly mocked absent in every case here so these tests exercise the
    local fallback deterministically, regardless of the host; the native
    branch itself is covered by `BuildPrototypeContextTest`'s
    `test_precedents_use_native_runtime_when_available` above."""

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
        self._which_patch = mock.patch("simplicio_mapper.query.shutil.which", return_value=None)
        self._which_patch.start()
        self.addCleanup(self._which_patch.stop)

    def test_ranks_by_keyword_overlap(self) -> None:
        candidates, delegation = _precedent_candidates(".", self.items, "checkout orders flow", limit=5)
        self.assertTrue(candidates)
        self.assertEqual(candidates[0]["precedent_id"], "p1")
        self.assertFalse(delegation["used"])

    def test_every_candidate_has_confidence_and_provenance(self) -> None:
        candidates, _delegation = _precedent_candidates(".", self.items, "checkout billing", limit=5)
        for entry in candidates:
            self.assertGreaterEqual(entry["confidence"], 1)
            self.assertEqual(entry["provenance"], "local-keyword-overlap:precedent-index")

    def test_no_overlap_returns_no_candidates(self) -> None:
        candidates, _delegation = _precedent_candidates(
            ".", self.items, "completely nonmatching query text", limit=5
        )
        self.assertEqual(candidates, [])

    def test_respects_limit(self) -> None:
        candidates, _delegation = _precedent_candidates(".", self.items, "python precedent", limit=1)
        self.assertLessEqual(len(candidates), 1)

    def test_empty_query_text_returns_no_candidates(self) -> None:
        candidates, delegation = _precedent_candidates(".", self.items, "", limit=5)
        self.assertEqual(candidates, [])
        self.assertEqual(delegation["reason"], "missing_argument")

    def test_carries_summary_and_tags_through(self) -> None:
        candidates, _delegation = _precedent_candidates(".", self.items, "checkout", limit=5)
        entry = next(c for c in candidates if c["precedent_id"] == "p1")
        self.assertEqual(entry["path"], "src/orders/checkout.py")
        self.assertEqual(entry["summary"], "checkout flow precedent")
        self.assertIn("checkout", entry["tags"])


class PrecedentCandidatesContradictoryTest(unittest.TestCase):
    """Unit: contradictory/stale precedents must not crash ranking and must
    produce a documented, deterministic tie-break (issue #286 mapper-scale
    follow-up). Two precedent entries recommend opposite things for the same
    overlap score -- ranking must still return a fully-ordered, stable
    result, not raise and not silently drop one arbitrarily each run."""

    def setUp(self) -> None:
        self._which_patch = mock.patch("simplicio_mapper.query.shutil.which", return_value=None)
        self._which_patch.start()
        self.addCleanup(self._which_patch.stop)
        # Both items have IDENTICAL tags/summary text -- and therefore an
        # identical keyword-overlap score against the same query -- but
        # contradictory recommendations, simulating two precedents from
        # different eras of the same feature that disagree on approach.
        self.items = [
            {
                "id": "stale-approach-a",
                "path": "src/checkout/v1.py",
                "summary": "checkout flow precedent: use synchronous payment capture",
                "tags": ["checkout", "payment", "sync"],
            },
            {
                "id": "stale-approach-b",
                "path": "src/checkout/v2.py",
                "summary": "checkout flow precedent: use async payment capture",
                "tags": ["checkout", "payment", "sync"],
            },
        ]

    def test_tied_contradictory_precedents_do_not_crash_ranking(self) -> None:
        candidates, delegation = _precedent_candidates(".", self.items, "checkout payment sync", limit=5)
        self.assertEqual(len(candidates), 2)
        self.assertFalse(delegation["used"])

    def test_tie_break_is_deterministic_across_repeated_calls(self) -> None:
        # Same input, called repeatedly: the tie-break (stable sort, original
        # index order preserved for equal overlap scores -- documented on
        # `query._local_precedent_fallback`) must return candidates in the
        # exact same order every time, never a random/unstable ordering.
        orders = []
        for _ in range(5):
            candidates, _delegation = _precedent_candidates(".", self.items, "checkout payment sync", limit=5)
            orders.append(tuple(c["precedent_id"] for c in candidates))
        self.assertEqual(len(set(orders)), 1)
        # The documented tie-break is stable-sort-preserves-input-order: the
        # first item in `self.items` must stay first in every ranked result.
        self.assertEqual(orders[0], ("stale-approach-a", "stale-approach-b"))

    def test_contradictory_summaries_both_carry_confidence_and_provenance(self) -> None:
        candidates, _delegation = _precedent_candidates(".", self.items, "checkout payment sync", limit=5)
        for entry in candidates:
            self.assertGreaterEqual(entry["confidence"], 1)
            self.assertEqual(entry["provenance"], "local-keyword-overlap:precedent-index")


class TruncateToBudgetTest(unittest.TestCase):
    """Unit: `_truncate_to_budget()` in isolation."""

    def test_under_budget_untouched(self) -> None:
        payload = {
            "affected_symbols": [1, 2, 3],
            "affected_tests": [],
            "needs_review": [],
            "negative_space": [],
        }
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
            code = main(
                ["prototype-context", self.root, "--type", "workflow", "--arg", "src/app.py", "--json"]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["schema"], PROTOTYPE_CONTEXT_SCHEMA)
        self.assertEqual(payload["type"], "workflow")


if __name__ == "__main__":
    unittest.main()
