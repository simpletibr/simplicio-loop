from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper import retrieval_index as ri


def _sample_project_map() -> dict:
    return {
        "files": [
            {
                "path": "src/modeling/sort_lines.py",
                "roles": ["domain"],
                "importance": 0.4,
                "language": "python",
                "size_bytes": 200,
                "imports": ["os"],
                "exports": ["sort_power_plant_lines"],
            },
            {
                "path": "src/cache/token_cache.py",
                "roles": ["domain"],
                "importance": 0.6,
                "language": "python",
                "size_bytes": 400,
                "imports": ["functools"],
                "exports": ["TokenCache"],
            },
            {
                "path": "docs/release-notes.md",
                "roles": ["docs"],
                "importance": 0.9,
                "language": "markdown",
                "size_bytes": 50,
            },
            {
                "path": "node_modules/vendor/dep.js",
                "roles": [],
                "importance": 0.1,
                "language": "javascript",
                "size_bytes": 99999,
            },
        ],
        "recent_changes": [{"path": "docs/release-notes.md", "status": "modified"}],
    }


def _sample_symbols() -> dict:
    return {
        "symbols": [
            {"defined_in": "src/modeling/sort_lines.py", "name": "sort_power_plant_lines",
             "kind": "function", "line": 1, "qualified_name": "src/modeling/sort_lines.py::sort_power_plant_lines"},
            {"defined_in": "src/cache/token_cache.py", "name": "TokenCache",
             "kind": "class", "line": 3, "qualified_name": "src/cache/token_cache.py::TokenCache"},
        ]
    }


def _sample_call_graph() -> dict:
    return {
        "edges": [
            {"from": "src/cache/token_cache.py", "to": "src/modeling/sort_lines.py"},
        ]
    }


class RetrievalIndexBuildTest(unittest.TestCase):
    def test_index_schema_and_version(self) -> None:
        idx = ri.build_retrieval_index(_sample_project_map())
        self.assertEqual(idx["schema"], ri.RETRIEVAL_INDEX_SCHEMA)
        self.assertEqual(idx["version"], 1)
        self.assertEqual(idx["document_count"], 4)
        self.assertIn("document_frequency", idx)
        self.assertIn("documents", idx)
        self.assertIn("index_id", idx)

    def test_index_carries_symbol_and_path_terms_without_reading_files(self) -> None:
        idx = ri.build_retrieval_index(
            _sample_project_map(), symbol_index=_sample_symbols(), call_graph=_sample_call_graph()
        )
        by_path = {d["path"]: d for d in idx["documents"]}
        # Symbol names are indexed from the symbol index, not file bodies.
        self.assertIn("tokencache", by_path["src/cache/token_cache.py"]["tf"])
        # Path tokens are indexed.
        tf_cache = by_path["src/cache/token_cache.py"]["tf"]
        self.assertTrue(any("cache" in tok for tok in tf_cache))

    def test_generated_vendor_flagged(self) -> None:
        idx = ri.build_retrieval_index(_sample_project_map())
        by_path = {d["path"]: d for d in idx["documents"]}
        self.assertTrue(by_path["node_modules/vendor/dep.js"]["generated"])


class QueryPlanTest(unittest.TestCase):
    def test_explicit_target_and_symbol_weighting(self) -> None:
        plan = ri.build_query_plan(
            "Fix TokenCache cache eviction in src/cache/token_cache.py (RN01)",
            target="src/cache/token_cache.py",
        )
        self.assertEqual(plan.target_path, "src/cache/token_cache.py")
        self.assertIn("TokenCache", plan.symbol_terms)
        self.assertIn("rn01", [a.lower() for a in plan.ac_ids])

    def test_stop_words_excluded(self) -> None:
        plan = ri.build_query_plan("the quick brown fox jumps")
        self.assertNotIn("the", plan.domain_terms)
        # long tokens are kept (fox is a valid domain token here); ensure 'the' dropped only
        self.assertNotIn("the", plan.all_terms)


class RankingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.idx = ri.build_retrieval_index(
            _sample_project_map(), symbol_index=_sample_symbols(), call_graph=_sample_call_graph()
        )

    def test_exact_symbol_query_ranks_specific_file_over_generic_docs(self) -> None:
        plan = ri.build_query_plan("Fix TokenCache eviction bug", target="")
        ranked = ri.rank_candidates(self.idx, plan, limit=3)
        self.assertTrue(ranked)
        paths = [r["path"] for r in ranked]
        self.assertIn("src/cache/token_cache.py", paths)
        # Generic docs must NOT preempt the specific implementation when relevant.
        self.assertNotIn("docs/release-notes.md", paths[:2])

    def test_recency_never_creates_relevance(self) -> None:
        # A recent file with ZERO semantic match must never be surfaced, even
        # though it is in recent_paths. Recency only boosts an already-relevant
        # candidate; it never fabricates relevance.
        plan = ri.build_query_plan("quantum entanglement telemetry", target="")
        ranked = ri.rank_candidates(
            self.idx, plan, recent_paths={"docs/release-notes.md", "src/cache/token_cache.py"}, limit=3
        )
        paths = [r["path"] for r in ranked]
        self.assertNotIn("docs/release-notes.md", paths)
        self.assertNotIn("src/cache/token_cache.py", paths)
        self.assertEqual(ranked, [])

    def test_generated_file_penalized(self) -> None:
        plan = ri.build_query_plan("vendor dependency dep.js", target="")
        ranked = ri.rank_candidates(self.idx, plan, limit=5)
        gen = [r for r in ranked if r["path"] == "node_modules/vendor/dep.js"]
        if gen:
            self.assertIn("generated_or_vendor_penalty", gen[0]["reason_codes"])

    def test_no_match_abstains(self) -> None:
        plan = ri.build_query_plan("quantum orbital photon unrelated", target="")
        ranked = ri.rank_candidates(self.idx, plan, limit=3)
        self.assertEqual(ranked, [])

    def test_explainable_score_components(self) -> None:
        plan = ri.build_query_plan("Fix TokenCache eviction", target="")
        ranked = ri.rank_candidates(self.idx, plan, limit=1)
        self.assertTrue(ranked)
        row = ranked[0]
        self.assertIn("score_components", row)
        self.assertIn("reason_codes", row)
        self.assertGreater(row["relevance_score"], 0)
        # Reason codes are not a single opaque score.
        self.assertTrue(any(c.startswith("symbol_match") for c in row["reason_codes"]))


class SpanExpansionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src/cache").mkdir(parents=True)
        (self.root / "src/cache/token_cache.py").write_text(
            "import functools\n\n\nclass TokenCache:\n"
            "    def get(self, key):\n        return None\n\n"
            "    def evict(self):\n        pass\n",
            encoding="utf-8",
        )
        self.idx = ri.build_retrieval_index(
            _sample_project_map(), symbol_index=_sample_symbols(), call_graph=_sample_call_graph()
        )
        self.plan = ri.build_query_plan("Fix TokenCache eviction", target="")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_span_expands_symbol_range_with_stable_handle(self) -> None:
        ranked = ri.rank_candidates(self.idx, self.plan, limit=1)
        expanded = ri.expand_spans(str(self.root), ranked, self.idx, symbol_index=_sample_symbols())
        self.assertTrue(expanded)
        entry = expanded[0]
        self.assertEqual(entry["path"], "src/cache/token_cache.py")
        self.assertTrue(entry["spans"])
        span = entry["spans"][0]
        self.assertIn("range_hash", span)
        self.assertIn("start_line", span)
        # Stable expand handle present for omitted content.
        self.assertTrue(entry["expand_handle"].startswith("expand:"))
        self.assertIn("token_cache.py", entry["expand_handle"])


class TokenBudgetTest(unittest.TestCase):
    def test_budget_fit_under_limit(self) -> None:
        plan = ri.build_query_plan("Fix TokenCache", target="")
        fit = ri.fit_token_budget([], ".", token_budget=8000, plan=plan)
        self.assertFalse(fit["needs_broader_context"])

    def test_required_span_overflow_requests_broader_context(self) -> None:
        # Simulate a required path whose span cost exceeds the budget.
        entry = {
            "path": "big.py",
            "spans": [{"start_line": 1, "end_line": 100000, "symbol": "x", "kind": "function"}],
        }
        plan = ri.build_query_plan("Fix big", target="big.py")
        fit = ri.fit_token_budget([entry], ".", token_budget=10, plan=plan)
        self.assertTrue(fit["needs_broader_context"])
        self.assertTrue(any("big.py" in c for c in fit["broader_context"]))


class FidelityGateTest(unittest.TestCase):
    def test_sufficiency_requires_discriminative_coverage(self) -> None:
        idx = ri.build_retrieval_index(_sample_project_map(), symbol_index=_sample_symbols())
        plan = ri.build_query_plan("Fix TokenCache eviction")
        ranked = ri.rank_candidates(idx, plan, limit=3)
        fidelity = ri.fidelity_gate(ranked, ri.expand_spans(".", ranked, idx), plan)
        self.assertTrue(fidelity["sufficient"])
        # All discriminative terms matched (TokenCache, eviction -> symbol + domain).
        self.assertGreaterEqual(fidelity["coverage_ratio"], 0.5)

    def test_missing_required_identifier_fails_fidelity(self) -> None:
        # Query references an AC id that no file matches.
        idx = ri.build_retrieval_index(_sample_project_map())
        plan = ri.build_query_plan("Implement RN99 nonexistent requirement", target="")
        ranked = ri.rank_candidates(idx, plan, limit=3)
        fidelity = ri.fidelity_gate(ranked, [], plan, minimum_query_coverage=0.2)
        # Either abstained (no relevant target) or insufficient due to missing AC.
        self.assertFalse(fidelity["sufficient"])

    def test_high_generic_overlap_alone_cannot_pass(self) -> None:
        # A query whose terms all appear in generic docs only must not pass as
        # "sufficient" when no discriminative symbol/target matched.
        idx = ri.build_retrieval_index(_sample_project_map())
        plan = ri.build_query_plan("release notes documentation website", target="")
        ranked = ri.rank_candidates(idx, plan, limit=3)
        fidelity = ri.fidelity_gate(ranked, [], plan, minimum_query_coverage=0.2)
        # Generic docs-only selection should not be marked sufficient with symbol intent.
        self.assertFalse(fidelity["sufficient"])
        self.assertTrue(fidelity["reasons"])


class DeterminismTest(unittest.TestCase):
    def test_identical_inputs_produce_stable_ordering(self) -> None:
        pm = _sample_project_map()
        idx1 = ri.build_retrieval_index(pm, symbol_index=_sample_symbols())
        idx2 = ri.build_retrieval_index(pm, symbol_index=_sample_symbols())
        self.assertEqual(idx1["index_id"], idx2["index_id"])
        plan = ri.build_query_plan("Fix TokenCache eviction")
        r1 = [r["path"] for r in ri.rank_candidates(idx1, plan)]
        r2 = [r["path"] for r in ri.rank_candidates(idx2, plan)]
        self.assertEqual(r1, r2)


class EndToEndSelectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src/modeling").mkdir(parents=True)
        (self.root / "src/cache").mkdir(parents=True)
        (self.root / "docs").mkdir()
        (self.root / "src/modeling/sort_lines.py").write_text(
            "def sort_power_plant_lines(lines):\n    return sorted(lines)\n", encoding="utf-8")
        (self.root / "src/cache/token_cache.py").write_text(
            "class TokenCache:\n    def get(self, k):\n        return None\n", encoding="utf-8")
        (self.root / "docs/release-notes.md").write_text("release notes\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_selector_picks_specific_file_no_full_scan(self) -> None:
        selection = ri.select_context_targets(
            str(self.root), _sample_project_map(),
            goal="Fix TokenCache eviction in token cache implementation",
            symbol_index=_sample_symbols(), call_graph=_sample_call_graph(),
        )
        paths = [t["path"] for t in selection["targets"]]
        self.assertIn("src/cache/token_cache.py", paths)
        self.assertEqual(selection["schema"], ri.RETRIEVAL_SELECTION_SCHEMA)
        self.assertIn("query_plan", selection)
        self.assertIn("expanded_spans", selection)
        self.assertIn("token_budget_fit", selection)
        self.assertIn("fidelity", selection)
        # No false broader-context on a satisfied query.
        self.assertFalse(selection["fidelity"]["reasons"])

    def test_selector_abstains_on_no_vocabulary(self) -> None:
        selection = ri.select_context_targets(str(self.root), _sample_project_map(), goal="quantum orbital photon")
        self.assertTrue(selection["abstained"])
        self.assertEqual(selection["abstention_reason"], "no_relevant_targets")


if __name__ == "__main__":
    unittest.main()
