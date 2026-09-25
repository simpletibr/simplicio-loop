from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError

from simplicio_fast.fwht_turboquant import (
    SCHEMA,
    FwhtQuantizedVector,
    dequantize_fwht,
    quantize_fwht,
)
from simplicio_fast.turboquant import QuantizationError


class FwhtTurboQuantTest(unittest.TestCase):
    def test_contract_is_deterministic_and_packed(self) -> None:
        values = (1.0, -2.0, 0.5, 3.0, -4.0)
        first = quantize_fwht(values, seed=7)
        second = quantize_fwht(values, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(SCHEMA, first.schema)
        self.assertEqual(5, first.dimension)
        self.assertEqual(8, first.padded_dimension)
        self.assertEqual(4, len(first.packed))
        self.assertEqual(first.padded_dimension, len(first.codes))

    def test_round_trip_respects_padding_and_error_bound(self) -> None:
        values = (0.25, -1.0, 2.0, 3.5, -4.0)
        vector = quantize_fwht(values, seed=19)
        restored = dequantize_fwht(vector)
        error_norm = math.sqrt(
            sum(
                (left - right) ** 2
                for left, right in zip(values, restored, strict=True)
            )
        )
        self.assertLessEqual(
            error_norm,
            math.sqrt(vector.padded_dimension) * vector.scale / 2 + 1e-12,
        )
        self.assertEqual(len(values), len(restored))

    def test_input_is_unchanged_and_seed_is_normalized(self) -> None:
        values = [1.0, -2.0, 3.0]
        vector = quantize_fwht(values, seed=-1)
        self.assertEqual([1.0, -2.0, 3.0], values)
        self.assertEqual((1 << 64) - 1, vector.seed)
        with self.assertRaises(FrozenInstanceError):
            vector.scale = 2.0  # type: ignore[misc]

    def test_contract_rejects_invalid_input_and_packed_state(self) -> None:
        for values in ((), (True, 0.0), (float("nan"), 0.0), "12"):
            with self.subTest(values=values), self.assertRaises(QuantizationError):
                quantize_fwht(values)
        valid = quantize_fwht((1.0,), seed=1)
        invalid = (
            {"dimension": 0},
            {"padded_dimension": 2},
            {"scale": 0.0},
            {"packed": b""},
            {"packed": b"\xf0"},
        )
        for changes in invalid:
            fields = {
                "dimension": valid.dimension,
                "padded_dimension": valid.padded_dimension,
                "seed": valid.seed,
                "scale": valid.scale,
                "packed": valid.packed,
            }
            fields.update(changes)
            with self.subTest(changes=changes), self.assertRaises(QuantizationError):
                FwhtQuantizedVector(**fields)

    def test_contract_rejects_wrong_vector_type(self) -> None:
        with self.assertRaises(QuantizationError):
            dequantize_fwht(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
