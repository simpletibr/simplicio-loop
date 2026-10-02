from __future__ import annotations

import math
import unittest

from simplicio_mapper.store.neural.fwht import fwht
from simplicio_mapper.store.neural.fwht_turboquant import (
    SCHEMA as FWHT_SCHEMA,
)
from simplicio_mapper.store.neural.fwht_turboquant import (
    dequantize_fwht,
    quantize_fwht,
)
from simplicio_mapper.store.neural.turboquant import (
    QuantizationError,
    QuantizedVector,
    _splitmix64,
    _validate_dimension,
    _validate_seed,
    approximate_candidates,
    dequantize,
    exact_rerank,
    pack_nibbles,
    quantize,
    rotate,
    unpack_nibbles,
)
from simplicio_mapper.store.neural.vector_contracts import (
    VECTOR_INDEX_SCHEMA,
    VECTOR_QUERY_RECEIPT_SCHEMA,
    VectorContractError,
    validate_vector_index_manifest,
    validate_vector_query_receipt,
)


class TurboQuantTest(unittest.TestCase):
    def test_dimension_validation(self) -> None:
        _validate_dimension(1)
        _validate_dimension(128)
        for invalid in (0, -1, True, False, "128", 3.14, None):
            with self.subTest(invalid=invalid), self.assertRaises(QuantizationError):
                _validate_dimension(invalid)  # type: ignore[arg-type]

    def test_seed_validation_and_normalization(self) -> None:
        self.assertEqual(0, _validate_seed(0))
        self.assertEqual(42, _validate_seed(42))
        self.assertEqual((1 << 64) - 1, _validate_seed(-1))
        for invalid in (True, False, "seed", 3.14, None):
            with self.subTest(invalid=invalid), self.assertRaises(QuantizationError):
                _validate_seed(invalid)  # type: ignore[arg-type]

    def test_splitmix64_properties(self) -> None:
        # Deterministic generation
        s0 = _splitmix64(0)
        s1 = _splitmix64(0)
        self.assertEqual(s0, s1)
        self.assertNotEqual(0, s0)
        # Sequence changes
        s2 = _splitmix64(s0)
        self.assertNotEqual(s0, s2)

    def test_rotation_is_orthogonal_and_seed_deterministic(self) -> None:
        values = (1.0, -2.0, 3.5, 4.0, -0.25)
        rotated = rotate(values, seed=19)
        self.assertEqual(rotated, rotate(values, seed=19))
        self.assertEqual(values, rotate(rotated, seed=19, inverse=True))
        # Norm is preserved
        norm_orig = sum(x * x for x in values)
        norm_rot = sum(x * x for x in rotated)
        self.assertAlmostEqual(norm_orig, norm_rot, places=9)

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

    def test_zero_vector_uses_stable_unit_scale(self) -> None:
        vector = quantize((0.0, 0.0), seed=1)
        self.assertEqual(1.0, vector.scale)
        self.assertEqual((0, 0), vector.codes)
        self.assertEqual((0.0, 0.0), dequantize(vector))

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
        self.assertEqual(
            "near",
            exact_rerank((1.0, 0.0), candidates, metric="dot")[0].canonical_id,
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


class FwhtTest(unittest.TestCase):
    def test_unscaled_golden_vector(self) -> None:
        self.assertEqual(
            (10.0, -2.0, -4.0, 0.0), fwht((1, 2, 3, 4), normalization="none")
        )

    def test_orthonormal_transform_is_self_inverse(self) -> None:
        values = (0.25, -1.0, 2.0, 3.5, -4.0, 0.0, 1.25, 8.0)
        round_trip = fwht(fwht(values))
        for actual, expected in zip(round_trip, values):
            self.assertAlmostEqual(expected, actual, places=9)

    def test_fwht_validates_power_of_two(self) -> None:
        for invalid in ((), (1, 2, 3), (1, 2, 3, 4, 5)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                fwht(invalid)

    def test_fwht_turboquant_roundtrip_and_error_bound(self) -> None:
        values = (0.25, -1.0, 2.0, 3.5, -4.0)
        vector = quantize_fwht(values, seed=19)
        self.assertEqual(FWHT_SCHEMA, vector.schema)
        self.assertEqual(5, vector.dimension)
        self.assertEqual(8, vector.padded_dimension)
        restored = dequantize_fwht(vector)
        self.assertEqual(len(values), len(restored))
        error_norm = math.sqrt(
            sum((val_left - r) ** 2 for val_left, r in zip(values, restored, strict=True))
        )
        self.assertLessEqual(
            error_norm,
            math.sqrt(vector.padded_dimension) * vector.scale / 2 + 1e-12,
        )


class VectorContractsTest(unittest.TestCase):
    def test_valid_vector_index_manifest(self) -> None:
        manifest = {
            "schema": VECTOR_INDEX_SCHEMA,
            "repository": "simplicio-mapper",
            "commit": "a" * 40,
            "generation": "gen-1",
            "created_at": "2026-10-02T12:00:00Z",
            "embedding": {
                "model": "model-1",
                "revision": "rev-1",
                "dimension": 128,
            },
            "metric": "cosine",
            "normalization": "l2",
            "quantizer": {
                "algorithm": "turboquant-4bit",
                "format_version": "v1",
                "rotation_seed_hash": "b" * 64,
                "codebook_hash": "c" * 64,
            },
            "vector_count": 100,
            "canonical_id_mapping": {
                "owner": "mapper",
                "format": "csv",
            },
            "segments": [
                {
                    "name": "segment-0",
                    "offset": 0,
                    "bytes": 64,
                    "alignment": 64,
                    "endianness": "little",
                    "sha256": "d" * 64,
                }
            ],
            "integral_store": {
                "format": "fp32",
                "location": "/data/store.bin",
                "sha256": "e" * 64,
            },
            "build_source_hashes": {
                "file1": "f" * 64,
            },
            "compatibility_flags": ["compat_v1"],
        }
        validated = validate_vector_index_manifest(manifest)
        self.assertEqual(VECTOR_INDEX_SCHEMA, validated["schema"])

    def test_manifest_rejects_non_mapper_owner(self) -> None:
        manifest = {
            "schema": VECTOR_INDEX_SCHEMA,
            "repository": "repo",
            "commit": "a" * 40,
            "generation": "gen-1",
            "created_at": "2026-10-02T12:00:00Z",
            "embedding": {"model": "m", "revision": "r", "dimension": 4},
            "metric": "dot",
            "normalization": "none",
            "quantizer": {
                "algorithm": "turboquant-4bit",
                "format_version": "v1",
                "rotation_seed_hash": "b" * 64,
                "codebook_hash": "c" * 64,
            },
            "vector_count": 1,
            "canonical_id_mapping": {"owner": "external", "format": "raw"},
            "segments": [{"name": "s0", "offset": 0, "bytes": 8, "alignment": 8, "endianness": "little", "sha256": "d" * 64}],
            "integral_store": {"format": "fp16", "location": "loc", "sha256": "e" * 64},
            "build_source_hashes": {"f": "f" * 64},
            "compatibility_flags": ["c"],
        }
        with self.assertRaises(VectorContractError) as ctx:
            validate_vector_index_manifest(manifest)
        self.assertEqual("canonical_id_owner_invalid", ctx.exception.reason_code)

    def test_query_receipt_validation(self) -> None:
        receipt = {
            "schema": VECTOR_QUERY_RECEIPT_SCHEMA,
            "query_hash": "1" * 64,
            "policy_version": "simplicio.hybrid-retrieval/v1",
            "requested_k": 5,
            "candidate_k": 20,
            "oversampling": 4.0,
            "engine": {"requested": "python", "selected": "python"},
            "timings": {"quantized_ms": 1.2, "integral_ms": 0.8},
            "io": {"pages_read": 1, "bytes_read": 4096},
            "cache": {"hit": True, "miss": False},
            "fallback": {"used": False, "reason_code": "NONE"},
            "results": [
                {
                    "canonical_id": "doc-1",
                    "quantized_score": 0.85,
                    "integral_score": 0.88,
                }
            ],
            "resources": {"cpu_ms": 2.0, "rss_bytes": 1024, "io_bytes": 4096},
            "status": "success",
            "generation": "gen-1",
        }
        validated = validate_vector_query_receipt(receipt)
        self.assertEqual(VECTOR_QUERY_RECEIPT_SCHEMA, validated["schema"])


if __name__ == "__main__":
    unittest.main()
