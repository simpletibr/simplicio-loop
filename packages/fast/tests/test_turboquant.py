from __future__ import annotations

import unittest

from simplicio_fast.turboquant import (
    QuantizationError,
    approximate_candidates,
    exact_rerank,
    QuantizedVector,
    dequantize,
    pack_nibbles,
    quantize,
    rotate,
    unpack_nibbles,
)


class TurboQuantTest(unittest.TestCase):
    def test_rotation_is_orthogonal_and_seed_deterministic(self) -> None:
        values = (1.0, -2.0, 3.5, 4.0, -0.25)
        rotated = rotate(values, seed=19)
        self.assertEqual(rotated, rotate(values, seed=19))
        self.assertEqual(values, rotate(rotated, seed=19, inverse=True))

    def test_pack_uses_two_signed_nibbles_per_byte(self) -> None:
        codes = (-8, 7, 0, 3, -1)
        self.assertEqual(bytes((0x78, 0x30, 0x0F)), pack_nibbles(codes))
        self.assertEqual(codes, unpack_nibbles(pack_nibbles(codes), len(codes)))

    def test_odd_dimension_round_trip_has_zero_padding(self) -> None:
        vector = quantize((0.0, 1.0, -2.0, 3.0, 4.0), seed=7)
        self.assertEqual(5, vector.dimension)
        self.assertEqual(3, len(vector.packed))
        self.assertEqual(0, vector.packed[-1] & 0xF0)
        self.assertEqual(5, len(vector.codes))

    def test_quantization_is_deterministic_and_reconstruction_is_bounded(self) -> None:
        values = (-3.25, -1.0, 0.5, 2.0, 6.5, 0.0)
        first = quantize(values, seed=123)
        second = quantize(values, seed=123)
        self.assertEqual(first, second)
        self.assertEqual("simplicio.fast.turboquant-4bit/v1", first.schema)
        reconstructed = dequantize(first)
        self.assertTrue(
            all(
                abs(left - right) <= first.scale / 2 + 1e-12
                for left, right in zip(values, reconstructed)
            )
        )

    def test_exact_rerank_is_deterministic_and_tie_breaks_by_id(self) -> None:
        query = (1.0, 0.0)
        candidates = (("b", (1.0, 0.0)), ("a", (1.0, 0.0)), ("c", (0.0, 1.0)))
        self.assertEqual(
            ("a", "b", "c"),
            tuple(
                item.canonical_id for item in exact_rerank(query, candidates, top_k=3)
            ),
        )
        self.assertEqual(
            exact_rerank(query, candidates, top_k=2),
            exact_rerank(query, iter(candidates), top_k=2),
        )

    def test_exact_rerank_supports_l2_and_cosine_metrics(self) -> None:
        candidates = (("near", (2.0, 0.0)), ("far", (0.0, 3.0)))
        self.assertEqual(
            "near", exact_rerank((1.0, 0.0), candidates, metric="l2")[0].canonical_id
        )
        self.assertEqual(
            "near",
            exact_rerank((1.0, 0.0), candidates, metric="cosine")[0].canonical_id,
        )

    def test_exact_rerank_rejects_invalid_candidates(self) -> None:
        with self.assertRaises(QuantizationError):
            exact_rerank((1.0,), (("a", (1.0,)), ("a", (1.0,))))
        with self.assertRaises(QuantizationError):
            exact_rerank((1.0,), (("a", (1.0, 2.0)),))
        with self.assertRaises(QuantizationError):
            exact_rerank((1.0,), (("a", (1.0,)),), top_k=0)
        with self.assertRaises(QuantizationError):
            exact_rerank((1.0,), (("a", (1.0,)),), metric="manhattan")  # type: ignore[arg-type]

    def test_approximate_candidates_scores_packed_codes(self) -> None:
        query = (1.0, 0.0, 0.0, 0.0)
        candidates = (
            ("orthogonal", quantize((0.0, 1.0, 0.0, 0.0), seed=7)),
            ("near", quantize((1.0, 0.0, 0.0, 0.0), seed=7)),
        )
        self.assertEqual(
            "near",
            approximate_candidates(query, candidates, seed=7, candidate_k=1)[
                0
            ].canonical_id,
        )
        self.assertEqual(
            "near",
            approximate_candidates(query, candidates, seed=7, metric="cosine")[
                0
            ].canonical_id,
        )
        self.assertEqual(
            "near",
            approximate_candidates(query, candidates, seed=7, metric="l2")[
                0
            ].canonical_id,
        )

    def test_approximate_candidates_rejects_incompatible_packed_vectors(self) -> None:
        with self.assertRaises(QuantizationError):
            approximate_candidates(
                (1.0, 0.0), (("a", quantize((1.0, 0.0), seed=8)),), seed=7
            )
        with self.assertRaises(QuantizationError):
            approximate_candidates(
                (1.0, 0.0), (("a", quantize((1.0, 0.0, 0.0), seed=7)),), seed=7
            )
        with self.assertRaises(QuantizationError):
            approximate_candidates(
                (1.0, 0.0), (("a", quantize((1.0, 0.0), seed=7)),), candidate_k=0
            )

    def test_zero_vector_uses_stable_unit_scale(self) -> None:
        vector = quantize((0.0, 0.0), seed=1)
        self.assertEqual(1.0, vector.scale)
        self.assertEqual((0, 0), vector.codes)
        self.assertEqual((0.0, 0.0), dequantize(vector))

    def test_invalid_inputs_fail_closed(self) -> None:
        with self.assertRaises(QuantizationError):
            quantize((), seed=1)
        with self.assertRaises(QuantizationError):
            quantize((float("nan"),))
        with self.assertRaises(QuantizationError):
            pack_nibbles((8,))
        with self.assertRaises(QuantizationError):
            unpack_nibbles(b"\x00", 3)
        with self.assertRaises(QuantizationError):
            unpack_nibbles(b"\xf0", 1)
        with self.assertRaises(QuantizationError):
            dequantize(QuantizedVector(1, 0, 0.0, b"\x00"))


if __name__ == "__main__":
    unittest.main()
