"""The call graph and the overlay do not scale with calls x files (#1631).

Every check counts operations (passes over ``files``, capped candidates, service runs) so it is
deterministic; wall-clock only appears as a very wide ceiling (``WALL_CEILING_S``).
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_central_overlay import NAMES, OverlayCase, _git, semantic  # noqa: E402
from test_central_overlay_semantic_reuse import FAKE_SERVICE  # noqa: E402

from simplicio_mapper.mapper import graph as graph_module  # noqa: E402
from simplicio_mapper.mapper.central_overlay import compute_overlay  # noqa: E402
from simplicio_mapper.mapper.emit import build_artifacts  # noqa: E402
from simplicio_mapper.mapper.graph import (  # noqa: E402
    CALL_NAME_CANDIDATE_LIMIT,
    _build_call_graph,
    _build_symbol_index,
    _call_name_candidate_limit,
    _name_candidate_order,
    resolve_csharp_razor_semantics,
    semantic_input_key,
    semantic_not_required,
)
from simplicio_mapper.models import ProjectFile  # noqa: E402
from simplicio_mapper.relations import relation_coverage  # noqa: E402
from simplicio_mapper.semantic_resolution import COMMAND_ENV, RoslynSemanticAdapter  # noqa: E402

WALL_CEILING_S = 120.0
LIMIT_ENV = "SIMPLICIO_MAPPER_CALL_NAME_CANDIDATE_LIMIT"
TS = "2026-01-01T00:00:00Z"
# Passes over ``files`` that one ``_build_call_graph`` makes: a small constant, whatever the repo holds
# (measured: 5 at 50, 200 and 2000 files; the pre-#1631 loop made one pass per call site and language).
MAX_FILE_PASSES = 6


def _file(path: str, language: str, *, file_hash: str = "") -> ProjectFile:
    return ProjectFile(
        path=path,
        language=language,
        size_bytes=0,
        last_modified="",
        file_hash=file_hash,
        git_status="",
        roles=[],
        imports=[],
        exports=[],
    )


class CountingList(list):
    """A list that counts how many times it is iterated."""

    iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


class EnvCase(unittest.TestCase):
    """No semantic service and no candidate-limit override unless a test sets them."""

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(COMMAND_ENV, None)
        os.environ.pop(LIMIT_ENV, None)

    def graph(self, files: list[ProjectFile], contents: dict[str, str], **kwargs) -> dict:
        index = _build_symbol_index(".", files, TS, contents)
        return _build_call_graph(".", files, index, TS, contents, **kwargs)


CSHARP = "public class Svc{i} {{\n  public int Run{i}(int x) {{ return Helper{i}(x); }}\n  public int Helper{i}(int x) {{ return x; }}\n}}\n"
RAZOR = "@code {{\n  void Click{i}() {{ Svc{i}.Run{i}(1); }}\n}}\n"


def synthetic_repo(python_files: int, calls_per_file: int = 20) -> tuple[list[ProjectFile], dict[str, str]]:
    """``python_files`` Python files calling each other, plus 6 C# and 2 Razor files."""
    files: list[ProjectFile] = []
    contents: dict[str, str] = {}
    for i in range(python_files):
        body = "".join(f"    f_{(i + k) % python_files}()\n" for k in range(1, calls_per_file + 1))
        contents[f"py/m{i}.py"] = f"def f_{i}():\n{body}"
        files.append(_file(f"py/m{i}.py", "python"))
    for i in range(6):
        contents[f"cs/Svc{i}.cs"] = CSHARP.format(i=i)
        files.append(_file(f"cs/Svc{i}.cs", "csharp", file_hash=f"h{i}"))
    for i in range(2):
        contents[f"cs/View{i}.razor"] = RAZOR.format(i=i)
        files.append(_file(f"cs/View{i}.razor", "razor", file_hash=f"r{i}"))
    return files, contents


class FilePassesDoNotGrowWithCallsTests(EnvCase):
    def passes(self, python_files: int) -> tuple[int, int, dict]:
        files, contents = synthetic_repo(python_files)
        index = _build_symbol_index(".", files, TS, contents)
        counted = CountingList(files)
        started = time.perf_counter()
        graph = _build_call_graph(".", counted, index, TS, contents, edge_limit=10**7)
        self.assertLess(time.perf_counter() - started, WALL_CEILING_S)
        calls = sum(1 for edge in graph["edges"] if edge["type"] == "calls")
        return counted.iterations, calls, graph

    def test_passes_over_files_are_constant_for_2000_files_and_40000_call_sites(self) -> None:
        small_passes, small_calls, _ = self.passes(200)
        big_passes, big_calls, graph = self.passes(2000)
        self.assertGreaterEqual(small_calls, 200 * 20)
        self.assertGreaterEqual(big_calls, 2000 * 20)
        self.assertEqual(big_passes, small_passes, "passes over files must not depend on the repo size")
        self.assertGreaterEqual(big_passes, 1)
        self.assertLessEqual(big_passes, MAX_FILE_PASSES)
        self.assertEqual(graph["coverage"]["name_edges_discarded"], 0)
        self.assertEqual(graph["semantic_resolution"]["status"], "unavailable")


def _shared_repo(definitions: int, callers: int) -> tuple[list[ProjectFile], dict[str, str]]:
    """``shared`` defined in ``definitions`` files (listed in reverse order) and called once by each caller."""
    files: list[ProjectFile] = []
    contents: dict[str, str] = {}
    for k in reversed(range(definitions)):
        contents[f"defs/d{k:03d}.py"] = f"def shared():\n    return {k}\n"
        files.append(_file(f"defs/d{k:03d}.py", "python"))
    for k in range(callers):
        contents[f"callers/c{k:04d}.py"] = f"def run_{k}():\n    return shared()\n"
        files.append(_file(f"callers/c{k:04d}.py", "python"))
    return files, contents


def _shared_edges(graph: dict) -> dict[str, list[dict]]:
    by_site: dict[str, list[dict]] = {}
    for edge in graph["edges"]:
        if edge["type"] == "calls" and edge["provenance"]["queried_symbol"] == "shared":
            by_site.setdefault(edge["source_file"], []).append(edge)
    return by_site


class CandidateCapTests(EnvCase):
    def test_a_name_defined_ten_times_keeps_four_edges_per_site(self) -> None:
        files, contents = _shared_repo(definitions=10, callers=3)
        graph = self.graph(files, contents, name_candidate_limit=4)
        by_site = _shared_edges(graph)
        self.assertEqual(sorted(by_site), ["callers/c0000.py", "callers/c0001.py", "callers/c0002.py"])
        kept = [f"defs/d{k:03d}.py" for k in range(4)]
        for edges in by_site.values():
            self.assertEqual(len(edges), 4)
            self.assertEqual(sorted(edge["target_file"] for edge in edges), kept)
            for edge in edges:
                self.assertEqual(edge["provenance"]["candidate_count"], 10)
                self.assertEqual(edge["evidence_class"], "lexical_ambiguous")
                self.assertEqual(edge["resolution_status"], "ambiguous")
                self.assertEqual(edge["provenance"]["candidates"], [f"{path}::shared" for path in kept])
        coverage = graph["coverage"]
        self.assertEqual(coverage["name_candidate_limit"], 4)
        self.assertEqual(coverage["name_capped_call_sites"], 3)
        self.assertEqual(coverage["name_edges_discarded"], 3 * (10 - 4))
        self.assertEqual(coverage["status"], "degraded")

    def test_the_kept_candidates_do_not_depend_on_the_file_order(self) -> None:
        paths = ["z.py", "m.py", "a.py", "b.py"]
        contents = {path: "def shared():\n    return 1\n" for path in paths}
        contents["caller.py"] = "def go():\n    return shared()\n"
        for order in (list(contents), list(reversed(list(contents)))):
            files = [_file(path, "python") for path in order]
            graph = self.graph(files, contents, name_candidate_limit=2)
            targets = sorted(e["target_file"] for e in _shared_edges(graph)["caller.py"])
            self.assertEqual(targets, ["a.py", "b.py"], order)
            self.assertEqual(graph["coverage"]["name_edges_discarded"], 2)

    def test_the_candidate_order_is_file_then_line_then_name(self) -> None:
        def key(path: str, line: int, name: str) -> tuple:
            return _name_candidate_order({"defined_in": path, "line": line, "qualified_name": name})

        ordered = [key("a.py", 9, "z"), key("b.py", 1, "a"), key("b.py", 2, "a"), key("b.py", 2, "b")]
        self.assertEqual(ordered, sorted(reversed(ordered)))
        self.assertEqual(key("b.py", 10, "a") > key("b.py", 9, "a"), True)

    def test_a_limit_at_or_above_the_definitions_discards_nothing(self) -> None:
        files, contents = _shared_repo(definitions=10, callers=3)
        huge = self.graph(files, contents, name_candidate_limit=10**6)
        for limit in (10, 11, 32):
            graph = self.graph(files, contents, name_candidate_limit=limit)
            self.assertEqual(graph["coverage"]["name_edges_discarded"], 0)
            self.assertEqual(graph["coverage"]["name_capped_call_sites"], 0)
            self.assertEqual(graph["edges"], huge["edges"])
            self.assertEqual(len(_shared_edges(graph)["callers/c0000.py"]), 10)
        self.assertEqual(huge["coverage"]["name_edges_discarded"], 0)

    def test_a_limit_of_one_keeps_a_single_edge_and_counts_the_rest(self) -> None:
        files, contents = _shared_repo(definitions=3, callers=1)
        graph = self.graph(files, contents, name_candidate_limit=1)
        self.assertEqual(graph["coverage"]["name_edges_discarded"], 2)
        (edge,) = _shared_edges(graph)["callers/c0000.py"]
        # The class of the evidence follows the real number of candidates (3), not the capped list (1).
        self.assertEqual(
            (edge["evidence_class"], edge["resolution_status"], edge["provenance"]["candidate_count"]),
            ("lexical_ambiguous", "ambiguous", 3),
        )

    def test_csharp_name_lookup_is_classified_by_the_real_candidate_count(self) -> None:
        def helper(index: int) -> str:
            return f"public class H{index} {{\n  public int Helper(int x) {{ return x; }}\n}}\n"

        caller = "public class Caller {\n  public int Go() { return Helper(1); }\n}\n"
        for definitions, limit, status, discarded in ((3, 1, "ambiguous", 2), (1, 1, "inferred", 0)):
            contents = {f"cs/H{i}.cs": helper(i) for i in range(definitions)}
            contents["cs/Caller.cs"] = caller
            files = [_file(path, "csharp", file_hash="h") for path in contents]
            graph = self.graph(files, contents, name_candidate_limit=limit)
            edges = [e for e in graph["edges"] if e["type"] == "calls" and e["provenance"]["queried_symbol"] == "Helper"]
            self.assertEqual(len(edges), 1, (definitions, limit))
            self.assertEqual(edges[0]["resolution_status"], status)
            self.assertEqual(edges[0]["evidence_class"], "heuristic")
            self.assertEqual(edges[0]["provenance"]["candidate_count"], definitions)
            self.assertEqual(graph["coverage"]["name_edges_discarded"], discarded)

    def test_the_environment_variable_sets_the_limit(self) -> None:
        files, contents = _shared_repo(definitions=10, callers=3)
        os.environ[LIMIT_ENV] = "4"
        graph = self.graph(files, contents)
        self.assertEqual(graph["coverage"]["name_candidate_limit"], 4)
        self.assertEqual(graph["coverage"]["name_edges_discarded"], 18)
        # An explicit argument wins over the environment.
        graph = self.graph(files, contents, name_candidate_limit=7)
        self.assertEqual(graph["coverage"]["name_candidate_limit"], 7)
        self.assertEqual(graph["coverage"]["name_edges_discarded"], 3 * 3)

    def test_limit_resolution_rules(self) -> None:
        self.assertEqual(CALL_NAME_CANDIDATE_LIMIT, 32)
        self.assertEqual(_call_name_candidate_limit(), 32)
        for raw, expected in (("", 32), ("abc", 32), ("1.5", 32), ("0", 1), ("-7", 1), ("1", 1), ("500", 500)):
            os.environ[LIMIT_ENV] = raw
            self.assertEqual(_call_name_candidate_limit(), expected, raw)
        os.environ[LIMIT_ENV] = "9"
        self.assertEqual(_call_name_candidate_limit(3), 3)
        self.assertEqual(_call_name_candidate_limit(0), 1)
        self.assertEqual(_call_name_candidate_limit(-4), 1)

    def test_coverage_is_degraded_by_a_discard_alone(self) -> None:
        self.assertEqual(relation_coverage([])["status"], "complete")
        coverage = relation_coverage([], name_candidate_limit=5, name_capped_call_sites=1, name_edges_discarded=2)
        self.assertEqual(coverage["status"], "degraded")
        self.assertEqual(
            (coverage["name_candidate_limit"], coverage["name_capped_call_sites"], coverage["name_edges_discarded"]),
            (5, 1, 2),
        )


class CandidateCapScalesTests(EnvCase):
    def test_300_definitions_and_2000_call_sites_stay_bounded(self) -> None:
        files, contents = _shared_repo(definitions=300, callers=2000)
        index = _build_symbol_index(".", files, TS, contents)
        order_calls = []
        real_order = graph_module._name_candidate_order

        def counting_order(symbol: dict):
            order_calls.append(1)
            return real_order(symbol)

        started = time.perf_counter()
        with mock.patch.object(graph_module, "_name_candidate_order", counting_order):
            graph = _build_call_graph(".", files, index, TS, contents, edge_limit=10**7)
        self.assertLess(time.perf_counter() - started, WALL_CEILING_S)
        limit, sites = CALL_NAME_CANDIDATE_LIMIT, 2000
        name_edges = [e for e in graph["edges"] if e["type"] == "calls" and e["provenance"]["queried_symbol"] == "shared"]
        self.assertEqual(len(name_edges), limit * sites)
        coverage = graph["coverage"]
        self.assertEqual(coverage["name_candidate_limit"], limit)
        self.assertEqual(coverage["name_capped_call_sites"], sites)
        self.assertEqual(coverage["name_edges_discarded"], sites * (300 - limit))
        self.assertEqual(coverage["status"], "degraded")
        # The ordering key runs once per definition: the capped list is cached per name, not per call site.
        self.assertLessEqual(len(order_calls), 300)


class RecordingAdapter(RoslynSemanticAdapter):
    def __init__(self) -> None:
        super().__init__(command="recorded-service")
        self.requests: list[dict] = []

    def resolve(self, cwd, language, source_generation, symbols, call_sites):
        self.requests.append(
            {
                "language": language,
                "paths": sorted(item["path"] for item in source_generation),
                "symbol_files": sorted({item["defined_in"] for item in symbols}),
                "symbols": len(symbols),
                "call_files": sorted({item["source_file"] for item in call_sites}),
            }
        )
        return None, {"status": "unavailable", "languages": [language], "reason": "recorded"}


class SemanticPassScopeTests(EnvCase):
    def mixed(self) -> tuple[list[ProjectFile], dict[str, str]]:
        files, contents = synthetic_repo(5, calls_per_file=3)
        return files, contents

    def test_only_csharp_and_razor_reach_the_service(self) -> None:
        files, contents = self.mixed()
        index = _build_symbol_index(".", files, TS, contents)
        adapter = RecordingAdapter()
        resolution, by_site = resolve_csharp_razor_semantics(".", files, index["symbols"], contents, semantic_adapter=adapter)
        self.assertEqual(by_site, {})
        self.assertEqual([r["language"] for r in adapter.requests], ["csharp", "razor"])
        csharp, razor = adapter.requests
        self.assertEqual(csharp["paths"], [f"cs/Svc{i}.cs" for i in range(6)])
        self.assertEqual(razor["paths"], ["cs/View0.razor", "cs/View1.razor"])
        for request in adapter.requests:
            self.assertTrue(all(path.startswith("cs/") for path in request["symbol_files"]), request["symbol_files"])
            self.assertTrue(all(path.startswith("cs/") for path in request["call_files"]), request["call_files"])
        csharp_symbols = [s for s in index["symbols"] if s["defined_in"].startswith("cs/")]
        self.assertEqual(csharp["symbols"], len(csharp_symbols))
        self.assertEqual(resolution["status"], "unavailable")
        self.assertEqual(resolution["input_key"], semantic_input_key([f for f in files if f.path.startswith("cs/")], adapter))

    def test_a_tree_without_csharp_never_calls_the_service(self) -> None:
        files, contents = synthetic_repo(4, calls_per_file=2)
        files = [f for f in files if f.language == "python"]
        index = _build_symbol_index(".", files, TS, contents)
        adapter = RecordingAdapter()
        resolution, by_site = resolve_csharp_razor_semantics(".", files, index["symbols"], contents, semantic_adapter=adapter)
        self.assertEqual(adapter.requests, [])
        self.assertEqual((resolution, by_site), (semantic_not_required(), {}))
        self.assertNotIn("input_key", resolution)

    def test_input_key_depends_on_csharp_razor_and_the_service_only(self) -> None:
        files, _contents = synthetic_repo(3, calls_per_file=1)
        adapter = RecordingAdapter()
        key = semantic_input_key(files, adapter)
        self.assertIsNotNone(key)
        python_edited = [_file(f.path, f.language, file_hash="other") if f.language == "python" else f for f in files]
        self.assertEqual(semantic_input_key(python_edited, adapter), key)
        csharp_edited = [_file(f.path, f.language, file_hash="other") if f.path == "cs/Svc0.cs" else f for f in files]
        self.assertNotEqual(semantic_input_key(csharp_edited, adapter), key)
        other = RecordingAdapter()
        other.command = "another-service"
        self.assertNotEqual(semantic_input_key(files, other), key)
        unhashed = [_file(f.path, f.language) if f.path == "cs/Svc0.cs" else f for f in files]
        self.assertIsNone(semantic_input_key(unhashed, adapter))
        self.assertIsNone(semantic_input_key([f for f in files if f.language == "python"], adapter))


class LargeRepoOverlayTests(OverlayCase):
    BULK = 1990

    def setUp(self) -> None:
        super().setUp()
        bulk = self.main / "bulk"
        bulk.mkdir()
        for i in range(self.BULK):
            (bulk / f"b{i:04d}.py").write_text(f"def bulk_{i}(): return {i}\n", encoding="utf-8")
        src = self.main / "src"
        src.mkdir()
        for i in range(6):
            (src / f"Svc{i}.cs").write_text(CSHARP.format(i=i), encoding="utf-8")
        for i in range(2):
            (src / f"View{i}.razor").write_text(RAZOR.format(i=i), encoding="utf-8")
        _git(["add", "-A"], self.main)
        _git(["commit", "-q", "-m", "bulk"], self.main)
        self.log = self.base / "sem.log"
        script = self.base / "fake_sem.py"
        script.write_text(FAKE_SERVICE, encoding="utf-8")
        for key, value in {COMMAND_ENV: f"{sys.executable} {script}", "FAKE_SEM_LOG": str(self.log)}.items():
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)
        self.wt = self.worktree()
        self.assertIsNotNone(compute_overlay(str(self.wt)).artifacts)  # builds the central base

    def runs(self) -> int:
        return len(self.log.read_text(encoding="utf-8").split()) if self.log.exists() else 0

    def test_a_python_only_delta_in_a_2000_file_repo_does_not_rerun_the_service(self) -> None:
        tracked = [line for line in _git(["ls-files"], self.wt).splitlines() if line]
        self.assertGreaterEqual(len(tracked), 2000)
        self.assertGreaterEqual(sum(1 for path in tracked if path.endswith((".cs", ".razor"))), 8)
        (self.wt / self.rels[0]).write_text("def plain_edit():\n    return 1\n", encoding="utf-8")
        (self.wt / "bulk" / "b0007.py").write_text("def bulk_changed(): return 7\n", encoding="utf-8")
        (self.wt / "bulk" / "new_file.py").write_text("def brand_new(): return bulk_changed()\n", encoding="utf-8")
        before = self.runs()
        started = time.perf_counter()
        outcome = compute_overlay(str(self.wt))
        elapsed = time.perf_counter() - started
        self.assertIsNotNone(outcome.artifacts, outcome.receipt)
        self.assertEqual(self.runs() - before, 0, "the semantic service must not run for a Python-only delta")
        self.assertEqual(outcome.receipt["semantic"], "reused_from_base")
        self.assertLess(elapsed, WALL_CEILING_S)
        got, want = semantic(outcome.artifacts), semantic(build_artifacts(str(self.wt)))
        for name in NAMES:
            self.assertEqual(got[name], want[name], f"{name} differs from a fresh full mapping")


if __name__ == "__main__":
    unittest.main()
