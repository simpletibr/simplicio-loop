from __future__ import annotations

import unittest

from simplicio_fast.vector_contracts import (
    VECTOR_QUERY_RECEIPT_SCHEMA,
    validate_vector_query_receipt,
)
from simplicio_fast.vector_index import SCHEMA, TurboQuantIndex, VectorIndexError


class TurboQuantIndexTest(unittest.TestCase):
    def test_build_query_and_contract_validated_integral_rerank(self) -> None:
        index = TurboQuantIndex.build(
            [
                ("near", (1.0, 0.0)),
                ("near-two", (0.9, 0.0)),
                ("orthogonal", (0.0, 1.0)),
            ],
            seed=7,
            generation="g1",
        )
        receipt = index.query((1.0, 0.0), requested_k=2, candidate_k=3)
        self.assertEqual(SCHEMA, index.schema)
        self.assertEqual(VECTOR_QUERY_RECEIPT_SCHEMA, receipt["schema"])
        validate_vector_query_receipt(receipt)
        self.assertEqual(
            ["near", "near-two"], [row["canonical_id"] for row in receipt["results"]]
        )
        self.assertEqual(2, len(receipt["results"]))

    def test_query_is_stable_and_reports_quantized_then_integral_stages(self) -> None:
        index = TurboQuantIndex.build([("a", (1.0, 0.0)), ("b", (0.0, 1.0))], seed=3)
        first = index.query((1.0, 0.0), requested_k=1, candidate_k=2)
        second = index.query((1.0, 0.0), requested_k=1, candidate_k=2)
        self.assertEqual(first["query_hash"], second["query_hash"])
        self.assertGreaterEqual(first["timings"]["quantized_ms"], 0.0)
        self.assertGreaterEqual(first["timings"]["integral_ms"], 0.0)
        self.assertEqual(first["results"][0]["canonical_id"], "a")

    def test_build_rejects_empty_duplicate_mixed_dimension_and_invalid_limits(
        self,
    ) -> None:
        with self.assertRaisesRegex(VectorIndexError, "at least one vector"):
            TurboQuantIndex.build([])
        with self.assertRaisesRegex(VectorIndexError, "unique"):
            TurboQuantIndex.build([("a", (1.0,)), ("a", (1.0,))])
        with self.assertRaisesRegex(VectorIndexError, "one dimension"):
            TurboQuantIndex.build([("a", (1.0,)), ("b", (1.0, 2.0))])
        index = TurboQuantIndex.build([("a", (1.0,))])
        with self.assertRaisesRegex(VectorIndexError, "candidate_k must cover"):
            index.query((1.0,), requested_k=2, candidate_k=1)

    def test_query_rejects_dimension_and_non_finite_values(self) -> None:
        index = TurboQuantIndex.build([("a", (1.0, 0.0))])
        with self.assertRaisesRegex(VectorIndexError, "query dimension"):
            index.query((1.0,), requested_k=1)
        with self.assertRaisesRegex(VectorIndexError, "finite"):
            index.query((float("nan"), 0.0), requested_k=1)


if __name__ == "__main__":
    unittest.main()
