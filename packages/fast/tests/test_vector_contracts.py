from __future__ import annotations

import copy
import math
import unittest
from pathlib import Path

from simplicio_fast.vector_contracts import (
    VECTOR_INDEX_SCHEMA,
    VECTOR_QUERY_RECEIPT_SCHEMA,
    VectorContractError,
    validate_vector_index_manifest,
    validate_vector_query_receipt,
)


DIGEST = "a" * 64


def manifest() -> dict[str, object]:
    return {
        "schema": VECTOR_INDEX_SCHEMA,
        "repository": "example/repo",
        "commit": "abc123",
        "generation": "g1",
        "embedding": {"model": "code-embed", "revision": "r1", "dimension": 768},
        "metric": "cosine",
        "normalization": "l2",
        "quantizer": {
            "algorithm": "turboquant-4bit",
            "format_version": "1",
            "rotation_seed_hash": DIGEST,
            "codebook_hash": DIGEST,
        },
        "vector_count": 2,
        "canonical_id_mapping": {"owner": "mapper", "format": "canonical-id/v1"},
        "segments": [
            {
                "name": "hot",
                "offset": 4096,
                "bytes": 128,
                "alignment": 4096,
                "endianness": "little",
                "sha256": DIGEST,
            },
            {
                "name": "metadata",
                "offset": 8192,
                "bytes": 64,
                "alignment": 4096,
                "endianness": "little",
                "sha256": DIGEST,
            },
        ],
        "integral_store": {
            "format": "fp16",
            "location": "cold-vectors.bin",
            "sha256": DIGEST,
        },
        "build_source_hashes": {"corpus": DIGEST},
        "created_at": "2026-07-27T00:00:00Z",
        "compatibility_flags": ["little-endian", "immutable-segments"],
    }


def receipt() -> dict[str, object]:
    return {
        "schema": VECTOR_QUERY_RECEIPT_SCHEMA,
        "query_hash": DIGEST,
        "policy_version": "quality-v1",
        "requested_k": 1,
        "candidate_k": 4,
        "oversampling": 4.0,
        "engine": {"requested": "auto", "selected": "python"},
        "timings": {"quantized_ms": 0.2, "integral_ms": 0.4},
        "io": {"pages_read": 2, "bytes_read": 8192},
        "cache": {"hit": False, "miss": True},
        "fallback": {"used": False, "reason_code": "none"},
        "results": [
            {
                "canonical_id": "mapper:1",
                "quantized_score": -0.8,
                "integral_score": -0.9,
            }
        ],
        "resources": {"cpu_ms": 1.0, "rss_bytes": None, "io_bytes": 8192},
        "status": "ok",
        "generation": "g1",
    }


class VectorContractTest(unittest.TestCase):
    def test_manifest_accepts_and_does_not_mutate_input(self) -> None:
        payload = manifest()
        original = copy.deepcopy(payload)
        self.assertIs(payload, validate_vector_index_manifest(payload))
        self.assertEqual(original, payload)

    def test_manifest_rejects_unknown_schema_and_unsafe_segments(self) -> None:
        payload = manifest()
        payload["schema"] = "simplicio.fast-vector-index/v2"
        with self.assertRaises(VectorContractError) as error:
            validate_vector_index_manifest(payload)
        self.assertEqual("unsupported_schema", error.exception.reason_code)

        payload = manifest()
        payload["segments"][1]["offset"] = 4096
        with self.assertRaises(VectorContractError) as error:
            validate_vector_index_manifest(payload)
        self.assertEqual("segment_overlap", error.exception.reason_code)

    def test_manifest_rejects_non_mapper_ids_and_bad_digest(self) -> None:
        payload = manifest()
        payload["canonical_id_mapping"]["owner"] = "fast"
        with self.assertRaises(VectorContractError) as error:
            validate_vector_index_manifest(payload)
        self.assertEqual("canonical_id_owner_invalid", error.exception.reason_code)

        payload = manifest()
        payload["quantizer"]["codebook_hash"] = "not-a-digest"
        with self.assertRaises(VectorContractError) as error:
            validate_vector_index_manifest(payload)
        self.assertEqual("digest_invalid", error.exception.reason_code)

    def test_receipt_accepts_and_keeps_negative_resource_null(self) -> None:
        payload = receipt()
        self.assertIs(payload, validate_vector_query_receipt(payload))
        self.assertIsNone(payload["resources"]["rss_bytes"])

    def test_receipt_rejects_candidate_bounds_nan_and_schema_version(self) -> None:
        payload = receipt()
        payload["candidate_k"] = 0
        with self.assertRaises(VectorContractError) as error:
            validate_vector_query_receipt(payload)
        self.assertEqual("field_invalid", error.exception.reason_code)

        payload = receipt()
        payload["results"][0]["integral_score"] = math.nan
        with self.assertRaises(VectorContractError) as error:
            validate_vector_query_receipt(payload)
        self.assertEqual("field_invalid", error.exception.reason_code)

        payload = receipt()
        payload["schema"] = "simplicio.fast-vector-query-receipt/v2"
        with self.assertRaises(VectorContractError) as error:
            validate_vector_query_receipt(payload)
        self.assertEqual("unsupported_schema", error.exception.reason_code)

    def test_adr_names_the_frozen_contracts_and_residuals(self) -> None:
        document = Path("docs/ADR-0002-turboquant-vector-contracts.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(VECTOR_INDEX_SCHEMA, document)
        self.assertIn(VECTOR_QUERY_RECEIPT_SCHEMA, document)
        self.assertIn("Rust", document)
        self.assertIn("re-ranking", document)

    def test_fail_closed_reason_codes_cover_schema_and_bounds(self) -> None:
        invalid_manifest_cases = [
            (None, "payload_not_object"),
            ({}, "schema_mismatch"),
        ]
        for payload, reason in invalid_manifest_cases:
            with (
                self.subTest(reason=reason),
                self.assertRaises(VectorContractError) as error,
            ):
                validate_vector_index_manifest(payload)
            self.assertEqual(reason, error.exception.reason_code)

        cases = [
            ("repository", "", "field_invalid"),
            ("segments", [], "segments_invalid"),
            ("metric", "euclidean", "metric_unsupported"),
            ("normalization", "unit", "normalization_unsupported"),
        ]
        for field, value, reason in cases:
            payload = manifest()
            payload[field] = value
            with (
                self.subTest(field=field),
                self.assertRaises(VectorContractError) as error,
            ):
                validate_vector_index_manifest(payload)
            self.assertEqual(reason, error.exception.reason_code)

        nested_cases = [
            ("quantizer", "algorithm", "other", "quantizer_unsupported"),
            ("integral_store", "format", "fp8", "integral_format_unsupported"),
            ("canonical_id_mapping", "owner", "fast", "canonical_id_owner_invalid"),
        ]
        for section, field, value, reason in nested_cases:
            payload = manifest()
            payload[section][field] = value
            with (
                self.subTest(field=f"{section}.{field}"),
                self.assertRaises(VectorContractError) as error,
            ):
                validate_vector_index_manifest(payload)
            self.assertEqual(reason, error.exception.reason_code)

        payload = manifest()
        payload["segments"][0]["name"] = "hot/unsafe"
        with self.assertRaises(VectorContractError) as error:
            validate_vector_index_manifest(payload)
        self.assertEqual("segment_name_invalid", error.exception.reason_code)

        payload = manifest()
        payload["segments"][0]["alignment"] = 3
        with self.assertRaises(VectorContractError) as error:
            validate_vector_index_manifest(payload)
        self.assertEqual("segment_alignment_invalid", error.exception.reason_code)

        payload = manifest()
        payload["segments"][0]["endianness"] = "big"
        with self.assertRaises(VectorContractError) as error:
            validate_vector_index_manifest(payload)
        self.assertEqual("endianness_unsupported", error.exception.reason_code)

        payload = manifest()
        payload["build_source_hashes"] = {}
        with self.assertRaises(VectorContractError) as error:
            validate_vector_index_manifest(payload)
        self.assertEqual("build_source_hashes_empty", error.exception.reason_code)

        payload = manifest()
        payload["compatibility_flags"] = ["", 1]
        with self.assertRaises(VectorContractError) as error:
            validate_vector_index_manifest(payload)
        self.assertEqual("compatibility_flags_invalid", error.exception.reason_code)

        payload = receipt()
        payload["requested_k"] = 3
        payload["candidate_k"] = 1
        with self.assertRaises(VectorContractError) as error:
            validate_vector_query_receipt(payload)
        self.assertEqual("candidate_k_invalid", error.exception.reason_code)

        payload = receipt()
        payload["cache"]["hit"] = 1
        with self.assertRaises(VectorContractError) as error:
            validate_vector_query_receipt(payload)
        self.assertEqual("cache_invalid", error.exception.reason_code)

        payload = receipt()
        payload["fallback"]["used"] = "no"
        with self.assertRaises(VectorContractError) as error:
            validate_vector_query_receipt(payload)
        self.assertEqual("fallback_invalid", error.exception.reason_code)

        payload = receipt()
        payload["results"] = [
            {"canonical_id": str(index), "quantized_score": 0.1, "integral_score": 0.2}
            for index in range(5)
        ]
        with self.assertRaises(VectorContractError) as error:
            validate_vector_query_receipt(payload)
        self.assertEqual("results_invalid", error.exception.reason_code)


if __name__ == "__main__":
    unittest.main()
