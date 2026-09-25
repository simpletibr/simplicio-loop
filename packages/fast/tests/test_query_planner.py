from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simplicio_fast.query_planner import QueryPlanCache, plan_query
from simplicio_fast.snapshot import Snapshot, build_snapshot


class QueryPlannerTest(unittest.TestCase):
    def snapshot(self) -> tuple[tempfile.TemporaryDirectory[str], Snapshot]:
        holder = tempfile.TemporaryDirectory()
        root = Path(holder.name)
        (root / "service.py").write_text(
            "def helper():\n    return True\n"
            "class Service:\n    def run(self):\n        return helper()\n",
            encoding="utf-8",
        )
        path = root / "project.sfast"
        build_snapshot(root, path)
        return holder, Snapshot(path)

    def test_exact_plan_uses_direct_index_and_budget(self) -> None:
        holder, snapshot = self.snapshot()
        try:
            plan = plan_query(
                snapshot,
                "Service.run",
                operation="context",
                max_results=2,
                max_bytes=100,
            )
            self.assertEqual("simplicio.fast.query-plan/v1", plan.schema)
            self.assertEqual("exact", plan.selected_index)
            self.assertEqual(1, plan.candidate_records)
            self.assertEqual(72, plan.estimated_bytes)
            self.assertEqual(("helper",), plan.prefetch)
            self.assertEqual(64, len(plan.request_digest))
            self.assertEqual("SFAST001:" + snapshot.sha256, plan.generation)
        finally:
            snapshot.close()
            holder.cleanup()

    def test_query_and_search_plans_expose_bounded_prefetch(self) -> None:
        holder, snapshot = self.snapshot()
        try:
            query = plan_query(
                snapshot, "Service.run", operation="query", max_results=1
            )
            search = plan_query(
                snapshot, "Service.run", operation="search", max_results=1
            )
            self.assertEqual(("helper",), query.prefetch)
            self.assertEqual(("helper",), search.prefetch)
        finally:
            snapshot.close()
            holder.cleanup()

    def test_filters_are_composed_without_source_materialization(self) -> None:
        holder, snapshot = self.snapshot()
        try:
            plan = plan_query(snapshot, "run", path="service.py", kind="function")
            self.assertEqual("name-substring+path+kind", plan.selected_index)
            self.assertEqual(1, plan.candidate_records)
            self.assertEqual("bounded_name_indexes", plan.reason)
            self.assertEqual(("helper",), plan.prefetch)
        finally:
            snapshot.close()
            holder.cleanup()

    def test_impact_plan_is_explicitly_relation_bounded(self) -> None:
        holder, snapshot = self.snapshot()
        try:
            plan = plan_query(snapshot, "Service", operation="impact")
            self.assertEqual("relation-scan", plan.selected_index)
            self.assertEqual(snapshot.relation_count, plan.candidate_records)
            self.assertEqual("impact_requires_typed_relation_filter", plan.reason)
        finally:
            snapshot.close()
            holder.cleanup()

    def test_cache_is_generation_and_request_scoped(self) -> None:
        holder, snapshot = self.snapshot()
        try:
            cache = QueryPlanCache(max_entries=2)
            first = plan_query(snapshot, "Service.run", cache=cache)
            second = plan_query(snapshot, "Service.run", cache=cache)
            different_request = plan_query(snapshot, "Service", cache=cache)
            self.assertIs(first, second)
            self.assertNotEqual(first.request_digest, different_request.request_digest)
            self.assertEqual(1, cache.stats()["hits"])
            self.assertEqual(2, cache.stats()["misses"])
            self.assertEqual(2, cache.invalidate_generation(snapshot.generation))
            self.assertIsNone(cache.get(snapshot.generation, first.request_digest))
        finally:
            snapshot.close()
            holder.cleanup()

    def test_cache_eviction_is_bounded_and_deterministic(self) -> None:
        holder, snapshot = self.snapshot()
        try:
            cache = QueryPlanCache(max_entries=1)
            first = plan_query(snapshot, "Service.run", cache=cache)
            plan_query(snapshot, "Service", cache=cache)
            self.assertEqual(1, cache.stats()["size"])
            self.assertIsNone(cache.get(snapshot.generation, first.request_digest))
        finally:
            snapshot.close()
            holder.cleanup()


if __name__ == "__main__":
    unittest.main()
