from __future__ import annotations

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
            {
                "defined_in": "src/modeling/sort_lines.py",
                "name": "sort_power_plant_lines",
                "kind": "function",
                "line": 1,
                "qualified_name": "src/modeling/sort_lines.py::sort_power_plant_lines",
            },
            {
                "defined_in": "src/cache/token_cache.py",
                "name": "TokenCache",
                "kind": "class",
                "line": 3,
                "qualified_name": "src/cache/token_cache.py::TokenCache",
            },
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
        self.assertTrue(by_path["src/cache/token_cache.py"]["document_id"].startswith("doc:"))
        self.assertTrue(by_path["src/cache/token_cache.py"]["chunks"])
        self.assertTrue(by_path["src/cache/token_cache.py"]["chunks"][0]["chunk_id"].startswith("chunk:"))

    def test_generated_vendor_flagged(self) -> None:
        idx = ri.build_retrieval_index(_sample_project_map())
        by_path = {d["path"]: d for d in idx["documents"]}
        self.assertTrue(by_path["node_modules/vendor/dep.js"]["generated"])

    def test_incremental_update_reuses_unchanged_document_and_chunk_ids(self) -> None:
        base_idx = ri.build_retrieval_index(
            _sample_project_map(), symbol_index=_sample_symbols(), call_graph=_sample_call_graph()
        )
        updated_map = _sample_project_map()
        updated_map["files"] = list(updated_map["files"])
        updated_map["files"][0] = {
            **updated_map["files"][0],
            "exports": ["sort_power_plant_lines", "sort_power_plant_lines_v2"],
        }
        updated = ri.update_retrieval_index(
            base_idx,
            updated_map,
            symbol_index=_sample_symbols(),
            call_graph=_sample_call_graph(),
            changed_paths=["src/modeling/sort_lines.py"],
        )
        base_docs = {d["path"]: d for d in base_idx["documents"]}
        updated_docs = {d["path"]: d for d in updated["documents"]}
        self.assertEqual(
            base_docs["src/cache/token_cache.py"]["document_id"],
            updated_docs["src/cache/token_cache.py"]["document_id"],
        )
        self.assertEqual(
            base_docs["src/cache/token_cache.py"]["chunks"],
            updated_docs["src/cache/token_cache.py"]["chunks"],
        )
        self.assertIn("src/modeling/sort_lines.py", updated["incremental"]["invalidated_paths"])
        self.assertIn("src/cache/token_cache.py", updated["incremental"]["reused_paths"])


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

    def test_archive_and_large_generic_files_penalized_unless_targeted(self) -> None:
        project_map = {
            "files": [
                {"path": "archive/old-dependency.py", "size_bytes": 100},
                {"path": "src/large-generic.py", "size_bytes": ri.LARGE_GENERIC_FILE_THRESHOLD_BYTES + 1},
                {"path": "src/current.py", "size_bytes": 20},
            ]
        }
        index = ri.build_retrieval_index(project_map)
        docs = {doc["path"]: doc for doc in index["documents"]}
        self.assertIn("archive", docs["archive/old-dependency.py"]["generic_flags"])
        self.assertTrue(docs["src/large-generic.py"]["large"])

        ranked = ri.rank_candidates(index, ri.build_query_plan("old dependency large generic"), limit=5)
        archive = next(row for row in ranked if row["path"] == "archive/old-dependency.py")
        large = next(row for row in ranked if row["path"] == "src/large-generic.py")
        self.assertIn("archive_penalty", archive["reason_codes"])
        self.assertIn("large_generic_penalty", large["reason_codes"])

        targeted = ri.rank_candidates(
            index,
            ri.build_query_plan("inspect archived dependency", target="archive/old-dependency.py"),
            limit=3,
        )
        target = next(row for row in targeted if row["path"] == "archive/old-dependency.py")
        self.assertNotIn("archive_penalty", target["reason_codes"])

    def test_serialized_token_count_measures_canonical_utf8_bytes(self) -> None:
        payload = {"text": "áé", "values": [1, 2]}
        encoded = ri.serialized_json_bytes(payload)
        self.assertEqual(encoded, b'{"text":"\xc3\xa1\xc3\xa9","values":[1,2]}')
        self.assertEqual(ri.serialized_token_count(payload), ri.estimate_tokens(encoded.decode("utf-8")))

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
        self.assertIn("idf_terms", row)
        self.assertIn("reason_codes", row)
        self.assertGreater(row["relevance_score"], 0)
        # Reason codes are not a single opaque score.
        self.assertTrue(any(c.startswith("symbol_match") for c in row["reason_codes"]))
        self.assertTrue(any(c.startswith("idf_terms=") for c in row["reason_codes"]))


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
        self.assertTrue(span["chunk_id"].startswith("chunk:"))
        # Stable expand handle present for omitted content.
        self.assertTrue(entry["expand_handle"].startswith("expand:"))
        self.assertIn("token_cache.py", entry["expand_handle"])
        self.assertTrue(entry["omitted_ranges"])

    def test_expand_handle_round_trip_reads_omitted_content(self) -> None:
        ranked = ri.rank_candidates(self.idx, self.plan, limit=1)
        expanded = ri.expand_spans(str(self.root), ranked, self.idx, symbol_index=_sample_symbols())
        omitted = expanded[0]["omitted_ranges"][0]["expand_handle"]
        resolved = ri.resolve_expand_handle(str(self.root), omitted)
        self.assertEqual(resolved["path"], "src/cache/token_cache.py")
        self.assertFalse(resolved["stale"])
        self.assertIn("import functools", resolved["text"])

    def test_expand_handle_round_trips_colon_in_path(self) -> None:
        path = "src/namespace:service.py"
        (self.root / path).write_text("value = 1\n", encoding="utf-8")
        handle = ri._expand_handle(str(self.root), path, None)
        self.assertIn("%3A", handle)
        self.assertEqual(ri.resolve_expand_handle(str(self.root), handle)["path"], path)


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

    def test_explicit_target_allows_unmatched_contract_ids(self) -> None:
        idx = ri.build_retrieval_index(_sample_project_map(), symbol_index=_sample_symbols())
        plan = ri.build_query_plan("Fix TokenCache eviction for RN99", target="src/cache/token_cache.py")
        ranked = ri.rank_candidates(idx, plan, limit=3)
        fidelity = ri.fidelity_gate(ranked, ri.expand_spans(".", ranked, idx), plan)
        self.assertTrue(fidelity["sufficient"], fidelity)


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
            "def sort_power_plant_lines(lines):\n    return sorted(lines)\n", encoding="utf-8"
        )
        (self.root / "src/cache/token_cache.py").write_text(
            "class TokenCache:\n    def get(self, k):\n        return None\n", encoding="utf-8"
        )
        (self.root / "docs/release-notes.md").write_text("release notes\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_selector_picks_specific_file_no_full_scan(self) -> None:
        selection = ri.select_context_targets(
            str(self.root),
            _sample_project_map(),
            goal="Fix TokenCache eviction in token cache implementation",
            symbol_index=_sample_symbols(),
            call_graph=_sample_call_graph(),
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
        selection = ri.select_context_targets(
            str(self.root), _sample_project_map(), goal="quantum orbital photon"
        )
        self.assertTrue(selection["abstained"])
        self.assertEqual(selection["abstention_reason"], "no_relevant_targets")

    def test_selector_keeps_explicit_target_outside_ranked_limit(self) -> None:
        (self.root / "src/noise.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
        terms = "alpha beta gamma delta epsilon zeta eta theta iota kappa".split()
        project_map = {
            "files": [
                {
                    "path": "src/cache/token_cache.py",
                    "roles": ["domain"],
                    "importance": 0.1,
                    "language": "python",
                    "size_bytes": 100,
                },
                {
                    "path": "src/noise.py",
                    "roles": ["domain"],
                    "importance": 0.9,
                    "language": "python",
                    "size_bytes": 100,
                },
            ]
        }
        symbol_index = {
            "symbols": [
                {
                    "defined_in": "src/noise.py",
                    "name": term,
                    "kind": "function",
                    "line": 1,
                    "qualified_name": f"src/noise.py::{term}",
                }
                for term in terms
            ]
        }
        selection = ri.select_context_targets(
            str(self.root),
            project_map,
            goal=" ".join(terms),
            target="src/cache/token_cache.py",
            limit=1,
            symbol_index=symbol_index,
        )
        paths = [target["path"] for target in selection["targets"]]
        self.assertEqual(paths[0], "src/noise.py")
        self.assertIn("src/cache/token_cache.py", paths)
        self.assertEqual(selection["target_resolution"]["status"], "included")


class FullContentFallbackTest(unittest.TestCase):
    """Regression coverage for issue #308: handoff must deliver real source
    content, not just an `expand_handle` pointer, for the most relevant
    target when it fits inside the token budget."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src/pricing").mkdir(parents=True)
        (self.root / "src/pricing/discount_calculator.py").write_text(
            "def apply_discount(price, pct):\n    return price - (price * pct / 100)\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _project_map(self) -> dict:
        return {
            "files": [
                {
                    "path": "src/pricing/discount_calculator.py",
                    "roles": ["domain"],
                    "importance": 0.6,
                    "language": "python",
                    "size_bytes": 100,
                },
            ]
        }

    def test_explicit_high_relevance_target_gets_real_content_when_it_fits_budget(self) -> None:
        # No symbol_index/call_graph passed -> no symbol-name lexical match,
        # so before the fix `spans` stayed empty (pointer-only) here.
        selection = ri.select_context_targets(
            str(self.root),
            self._project_map(),
            goal="apply_discount pricing calculator",
            target="src/pricing/discount_calculator.py",
            token_budget=8000,
        )
        self.assertEqual(
            selection["target_resolution"]["status"],
            "included",
            selection["target_resolution"],
        )
        expanded_by_path = {entry["path"]: entry for entry in selection["expanded_spans"]}
        entry = expanded_by_path["src/pricing/discount_calculator.py"]
        self.assertTrue(entry["spans"], "expected real content spans for the explicit high-relevance target")
        span = entry["spans"][0]
        self.assertEqual(span["kind"], "full_content")
        self.assertIn("apply_discount", span["text"])
        # The pointer-only mechanism must still be present alongside the content.
        self.assertTrue(entry["expand_handle"].startswith("expand:"))
        self.assertTrue(entry["omitted_ranges"])

    def test_content_omitted_when_it_does_not_fit_remaining_budget(self) -> None:
        # A near-zero token budget leaves no room for any real content: the
        # exception (pointer-only) must remain the behavior, not the rule.
        selection = ri.select_context_targets(
            str(self.root),
            self._project_map(),
            goal="apply_discount pricing calculator",
            target="src/pricing/discount_calculator.py",
            token_budget=1,
        )
        expanded_by_path = {entry["path"]: entry for entry in selection["expanded_spans"]}
        entry = expanded_by_path["src/pricing/discount_calculator.py"]
        self.assertEqual(entry["spans"], [])
        self.assertTrue(entry["expand_handle"].startswith("expand:"))


if __name__ == "__main__":
    unittest.main()
