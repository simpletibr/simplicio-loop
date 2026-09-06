"""Direct unit tests for simplicio_mapper.mapper.graph (issue #159 split).

Exercises call-graph/architecture/symbol construction in isolation --
imports straight from ``simplicio_mapper.mapper.graph``.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper import _native  # noqa: E402
from simplicio_mapper.mapper.graph import (  # noqa: E402
    _build_call_graph,
    _build_symbol_index,
    _candidate_import_targets,
    _is_macro_screen,
    _known_path_suffix_index,
    _macro_roles_for_path,
    _nearest_symbol,
    _symbol_definitions_for_file,
    build_macro_map,
)
from simplicio_mapper.mapper.parse import _build_file_inventory, _now_iso  # noqa: E402
from simplicio_mapper.models import ProjectFile  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class MacroHelpersTest(unittest.TestCase):
    def test_macro_roles_for_path_detects_entrypoint(self) -> None:
        roles = _macro_roles_for_path("src/index.js", "index.js", "index.js", [])
        self.assertIn("entrypoint", roles)

    def test_is_macro_screen_detects_nextjs_pages_route(self) -> None:
        self.assertTrue(_is_macro_screen("pages/index.tsx", "index.tsx", "typescript"))
        self.assertFalse(_is_macro_screen("src/utils/math.py", "math.py", "python"))


class BuildMacroMapTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "src/index.js", "module.exports = () => {};\n")
        _write(self.dir, "package.json", '{"name": "fixture", "main": "src/index.js"}')

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_macro_map_has_expected_schema_and_entrypoint(self) -> None:
        macro = build_macro_map(str(self.dir))
        self.assertEqual(macro["schema"], "simplicio.macro-map/v1")
        self.assertIn("src/index.js", macro["entry_points"])


class SymbolAndCallGraphTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "src/greet.py", "def greet(name):\n    return f'hi {name}'\n")
        _write(
            self.dir,
            "src/main.py",
            "from src.greet import greet\n\n\ndef run():\n    return greet('world')\n",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_symbol_index_and_call_graph_over_two_files(self) -> None:
        files = _build_file_inventory(str(self.dir), {}, {}, None)
        generated_at = _now_iso()
        symbol_index = _build_symbol_index(str(self.dir), files, generated_at)
        self.assertEqual(symbol_index["schema"], "simplicio.symbol-index/v1")
        names = {s["name"] for s in symbol_index["symbols"]}
        self.assertIn("greet", names)
        self.assertIn("run", names)

        call_graph = _build_call_graph(str(self.dir), files, symbol_index, generated_at)
        self.assertEqual(call_graph["schema"], "simplicio.call-graph/v1")
        self.assertIsInstance(call_graph["edges"], list)

    def test_native_symbol_index_canonicalizes_rich_records(self) -> None:
        original_available = _native.HAS_NATIVE
        original_builder = _native.build_symbol_index
        original_capabilities = _native.CAPABILITIES
        original_defaults = _native.NATIVE_DEFAULT_CAPABILITIES
        calls: list[list[tuple[str, str, int]]] = []

        def canonicalize(records: list[tuple[str, str, int]]) -> list[tuple[str, str, int]]:
            calls.append(records)
            return sorted(records, key=lambda item: (item[1], item[0], item[2]))

        _native.HAS_NATIVE = True
        _native.build_symbol_index = canonicalize
        _native.CAPABILITIES = {"features": ["symbol-index"]}
        _native.NATIVE_DEFAULT_CAPABILITIES = original_defaults | {"symbol-index"}
        try:
            files = _build_file_inventory(str(self.dir), {}, {}, None)
            result = _build_symbol_index(str(self.dir), files, _now_iso())
        finally:
            _native.HAS_NATIVE = original_available
            _native.build_symbol_index = original_builder
            _native.CAPABILITIES = original_capabilities
            _native.NATIVE_DEFAULT_CAPABILITIES = original_defaults

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            [(item["name"], item["defined_in"]) for item in result["symbols"]],
            [("greet", "src/greet.py"), ("run", "src/main.py")],
        )
        self.assertEqual(result["symbols"][0]["kind"], "function")


class SymbolLineNumberBlankLinesTest(unittest.TestCase):
    """Regression for a symbol-index line-number bug: every language pattern
    in ``_symbol_definitions_for_file`` anchors on ``^\\s*<keyword>`` with
    ``re.MULTILINE``. Because ``\\s`` matches newlines too, a definition
    preceded by one or more blank lines lets ``^`` anchor at an earlier
    blank line and lets ``\\s*`` swallow the intervening newlines -- so
    ``match.start()`` (and the reported line number) pointed at that earlier
    blank line instead of the real ``def``/``class`` line. This is the
    common case: any top-level Python function preceded by PEP8's one or
    two blank lines (or a module docstring followed by blank lines) got the
    wrong line number, which corrupted every consumer of that number
    (``ask callers/callees/tests-for``, call-graph self-call filtering,
    etc.)."""

    def test_def_after_module_docstring_reports_its_own_line(self) -> None:
        text = (
            '"""Sample module docstring."""\n'
            "\n"
            "\n"
            "def greet(name):\n"
            "    return f'hi {name}'\n"
            "\n"
            "\n"
            "def main():\n"
            "    print(greet('world'))\n"
        )
        file = ProjectFile(
            path="src/app.py",
            language="python",
            size_bytes=len(text),
            last_modified="",
            file_hash="",
            git_status="",
            roles=[],
            imports=[],
            exports=[],
        )
        symbols = {s["name"]: s["line"] for s in _symbol_definitions_for_file(file, text)}
        self.assertEqual(symbols["greet"], 4)
        self.assertEqual(symbols["main"], 8)

    def test_def_after_single_blank_line_reports_its_own_line(self) -> None:
        text = "x = 1\n\ndef foo():\n    return x\n"
        file = ProjectFile(
            path="a.py",
            language="python",
            size_bytes=len(text),
            last_modified="",
            file_hash="",
            git_status="",
            roles=[],
            imports=[],
            exports=[],
        )
        symbols = {s["name"]: s["line"] for s in _symbol_definitions_for_file(file, text)}
        self.assertEqual(symbols["foo"], 3)

    def test_call_graph_does_not_fabricate_self_call_on_def_line(self) -> None:
        """With the correct line number, the def line's own
        ``greet(name)`` occurrence in the call-expression scan matches
        ``greet``'s own definition line exactly, so the existing
        same-line self-skip in ``_build_call_graph`` correctly drops it --
        no more phantom ``greet`` calls ``greet`` edge."""
        text = (
            '"""Sample module docstring."""\n'
            "\n"
            "\n"
            "def greet(name):\n"
            "    return f'hi {name}'\n"
        )
        file = ProjectFile(
            path="src/app.py",
            language="python",
            size_bytes=len(text),
            last_modified="",
            file_hash="",
            git_status="",
            roles=[],
            imports=[],
            exports=[],
        )
        symbol_index = {"symbols": _symbol_definitions_for_file(file, text)}
        call_graph = _build_call_graph(".", [file], symbol_index, _now_iso(), contents={file.path: text})
        self_edges = [
            e
            for e in call_graph["edges"]
            if e["type"] == "calls" and e["source_symbol"] == e["target_symbol"] == "src/app.py::greet"
        ]
        self.assertEqual(self_edges, [])


class NearestSymbolIndexTest(unittest.TestCase):
    def test_indexed_lookup_preserves_nearest_definition(self) -> None:
        symbols = [
            {"name": "first", "qualified_name": "src/app.py::first", "defined_in": "src/app.py", "line": 4},
            {"name": "second", "qualified_name": "src/app.py::second", "defined_in": "src/app.py", "line": 10},
            {"name": "other", "qualified_name": "src/other.py::other", "defined_in": "src/other.py", "line": 2},
        ]
        by_file = {
            "src/app.py": [symbols[0], symbols[1]],
            "src/other.py": [symbols[2]],
        }
        lines_by_file = {path: [int(item["line"]) for item in definitions] for path, definitions in by_file.items()}

        expected = {1: None, 4: "src/app.py::first", 9: "src/app.py::first", 10: "src/app.py::second", 99: "src/app.py::second"}
        for line, qualified_name in expected.items():
            result = _nearest_symbol(
                symbols,
                "src/app.py",
                line,
                symbols_by_file=by_file,
                symbol_lines_by_file=lines_by_file,
            )
            self.assertEqual(result and result["qualified_name"], qualified_name)


class CandidateImportTargetsIndexParityTest(unittest.TestCase):
    """Issue #235 follow-up: ``_candidate_import_targets``'s suffix-match
    fallback was rewritten to use a precomputed index
    (``_known_path_suffix_index``) instead of re-scanning the full
    ``known_paths`` set for every import (the profiled ``O(n^2)`` hot spot,
    see ADR-009). These tests prove the indexed path returns exactly the
    same result as the original unindexed scan (``known_path_index=None``,
    which still builds the index on the fly) across the cases the original
    linear scan had to handle: a direct hit, a suffix-fallback hit, and no
    match at all.
    """

    def setUp(self) -> None:
        self.known_paths = {
            "src/pkg/utils.py",
            "src/pkg/main.py",
            "src/pkg/__init__.py",
            "other/unrelated/utils.py",
            "src/pkg/sub/deep/thing.py",
        }
        self.index = _known_path_suffix_index(self.known_paths)

    def _assert_parity(self, import_name: str, source_file: str) -> list[str]:
        with_index = _candidate_import_targets(import_name, source_file, self.known_paths, self.index)
        without_index = _candidate_import_targets(import_name, source_file, self.known_paths, None)
        self.assertEqual(with_index, without_index)
        return with_index

    def test_direct_hit_unaffected_by_index(self) -> None:
        result = self._assert_parity("./utils", "src/pkg/main.py")
        self.assertIn("src/pkg/utils.py", result)

    def test_suffix_fallback_hit_matches_original_scan(self) -> None:
        # Bare "utils" cannot resolve via any direct candidate path (no
        # "utils.py" at repo root), so this exercises the suffix-match
        # fallback -- there are two files ending in "/utils.py" in
        # known_paths, both should come back, sorted.
        result = self._assert_parity("utils", "src/pkg/main.py")
        self.assertEqual(result, sorted(["src/pkg/utils.py", "other/unrelated/utils.py"]))

    def test_no_match_returns_empty_both_ways(self) -> None:
        result = self._assert_parity("totally_unresolvable_name", "src/pkg/main.py")
        self.assertEqual(result, [])

    def test_deep_suffix_match(self) -> None:
        result = self._assert_parity("sub.deep.thing", "src/pkg/main.py")
        self.assertEqual(result, ["src/pkg/sub/deep/thing.py"])


class CallGraphSuffixFallbackEquivalenceTest(unittest.TestCase):
    """Full ``_build_call_graph`` pass over a fixture that forces the
    suffix-match fallback (a bare ``import utils`` that only resolves via
    ``known_base.endswith("/utils")``), proving the call-graph output is
    unchanged by the index-based rewrite -- this is the "pure performance
    fix, zero output change" guarantee for the enclosing pass, not just the
    helper in isolation.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "src/pkg/utils.py", "def helper():\n    return 1\n")
        _write(
            self.dir,
            "src/pkg/main.py",
            "import utils\n\n\ndef run():\n    return helper()\n",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_import_edge_resolved_via_suffix_fallback(self) -> None:
        files = _build_file_inventory(str(self.dir), {}, {}, None)
        generated_at = _now_iso()
        symbol_index = _build_symbol_index(str(self.dir), files, generated_at)
        call_graph = _build_call_graph(str(self.dir), files, symbol_index, generated_at)

        import_edges = [edge for edge in call_graph["edges"] if edge["type"] == "imports"]
        self.assertTrue(
            any(
                edge["source_file"] == "src/pkg/main.py" and edge["target_file"] == "src/pkg/utils.py"
                for edge in import_edges
            ),
            f"expected an imports edge from main.py to utils.py via suffix fallback, got: {import_edges}",
        )

        call_edges = [edge for edge in call_graph["edges"] if edge["type"] == "calls"]
        self.assertTrue(
            any(edge["target_symbol"] == "src/pkg/utils.py::helper" for edge in call_edges),
            f"expected a calls edge to helper(), got: {call_edges}",
        )


def _synthetic_files_forcing_fallback(count: int) -> tuple[list[ProjectFile], dict[str, str]]:
    """Build an in-memory (no disk I/O) file list where every file imports a
    name that never resolves directly, forcing every import into the
    suffix-match fallback path -- the exact shape that was quadratic before
    this fix (``_candidate_import_targets`` fallback scan, ADR-009).
    """
    files: list[ProjectFile] = []
    contents: dict[str, str] = {}
    for i in range(count):
        path = f"pkg_{i}/module_{i}.py"
        text = f"import unresolved_target_name\n\n\ndef fn_{i}():\n    return {i}\n"
        contents[path] = text
        files.append(
            ProjectFile(
                path=path,
                language="python",
                size_bytes=len(text),
                last_modified="",
                file_hash="",
                git_status="clean",
                roles=[],
                imports=["unresolved_target_name"],
                exports=[],
            )
        )
    return files, contents


class CandidateImportTargetsQuadraticRegressionTest(unittest.TestCase):
    """Heuristic timing proxy (NOT a hard perf assertion -- wall-clock
    numbers vary by machine/CI load) meant to catch a *future*
    reintroduction of the ``O(n^2)`` fallback scan this test file's sibling
    classes above prove is behaviorally unchanged. Doubling the number of
    files should scale roughly linearly (the indexed fallback); a
    regression back to a full ``known_paths`` scan per import would scale
    roughly quadratically instead, which this test's generous ratio
    threshold is sized to catch without being flaky on a slow CI box.
    """

    def test_doubling_files_does_not_scale_quadratically(self) -> None:
        small_files, small_contents = _synthetic_files_forcing_fallback(120)
        large_files, large_contents = _synthetic_files_forcing_fallback(480)  # 4x, not just 2x

        generated_at = _now_iso()
        small_symbol_index = _build_symbol_index(".", small_files, generated_at, small_contents)
        large_symbol_index = _build_symbol_index(".", large_files, generated_at, large_contents)

        # Warm-up call to avoid measuring first-call interpreter/import overhead.
        _build_call_graph(".", small_files, small_symbol_index, generated_at, small_contents)

        start = time.perf_counter()
        _build_call_graph(".", small_files, small_symbol_index, generated_at, small_contents)
        small_elapsed = time.perf_counter() - start

        start = time.perf_counter()
        _build_call_graph(".", large_files, large_symbol_index, generated_at, large_contents)
        large_elapsed = time.perf_counter() - start

        # 4x the files: linear scaling expects ~4x the time; quadratic
        # scaling (the bug this guards against) would expect ~16x. Allow a
        # generous 9x ceiling so ordinary noise/overhead never flakes this,
        # while still failing hard if the fallback goes quadratic again.
        ratio = large_elapsed / small_elapsed if small_elapsed > 0 else float("inf")
        self.assertLess(
            ratio,
            9.0,
            f"call-graph build time scaled {ratio:.2f}x for a 4x file-count "
            "increase -- looks quadratic again (expected roughly linear, "
            "~4x); see _candidate_import_targets / _known_path_suffix_index "
            "in simplicio_mapper/mapper/graph.py and ADR-009.",
        )


if __name__ == "__main__":
    unittest.main()
