from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.conformance import (
    DEFAULT_CORPUS,
    _canonical_digest,
    _corpus_digest,
    _json_command,
    _python_stats,
    _require_envelope,
    _rust_stats,
    normalize,
    run,
)


class ConformanceHarnessTest(unittest.TestCase):
    def test_real_engine_envelope_is_validated_at_harness_boundary(self) -> None:
        command = [
            sys.executable,
            "-c",
            "import json; print(json.dumps({'schema': 'simplicio.fast.stats/v1', 'engine': 'rust', 'stats': {}}))",
        ]
        payload = _json_command(command)
        self.assertEqual(
            _require_envelope(payload, schema="simplicio.fast.stats/v1", engine="rust")[
                "engine"
            ],
            "rust",
        )

    def test_normalize_maps_python_and_rust_stats_to_one_contract(self) -> None:
        python = {
            "version": 2,
            "bytes": 10,
            "files": 1,
            "symbols": 2,
            "relations": 3,
            "sections": ["symbols", "files"],
            "generation": "SFAST001:abc",
            "source_hashes": {"a": "1", "b": "2"},
            "budgets": {"max_bytes": 24000},
            "truncations": {"context": False},
            "reason_codes": ["budget", "partial"],
        }
        rust = {
            **python,
            "format_version": 2,
            "sections": ["files", "symbols"],
            "source_hashes": {"b": "2", "a": "1"},
            "reason_codes": ["partial", "budget"],
        }
        self.assertEqual(normalize(python), normalize(rust))

    def test_normalize_preserves_missing_optional_fields_as_null(self) -> None:
        normalized = normalize(
            {
                "version": 2,
                "bytes": 0,
                "files": 0,
                "symbols": 0,
                "relations": 0,
                "sections": [],
                "generation": "g",
            }
        )
        self.assertIsNone(normalized["source_hashes"])
        self.assertIsNone(normalized["budgets"])
        self.assertIsNone(normalized["truncations"])
        self.assertIsNone(normalized["reason_codes"])

    def test_normalize_preserves_drift_for_the_gate(self) -> None:
        python = {
            "version": 2,
            "bytes": 10,
            "files": 1,
            "symbols": 2,
            "relations": 3,
            "sections": [],
            "generation": "a",
        }
        rust = {
            "format_version": 2,
            "bytes": 11,
            "files": 1,
            "symbols": 2,
            "relations": 3,
            "sections": [],
            "generation": "a",
        }
        self.assertNotEqual(normalize(python), normalize(rust))

    def test_rust_envelope_requires_rust_engine_identity(self) -> None:
        payload = {"schema": "simplicio.fast.stats/v1", "stats": {}}
        with patch("scripts.conformance._json_command", return_value=payload):
            with self.assertRaisesRegex(RuntimeError, "engine_identity_mismatch"):
                _rust_stats(Path("rust"), Path("snapshot"))

    def test_python_envelope_rejects_schema_drift(self) -> None:
        payload = {"schema": "simplicio.fast.query/v1", "stats": {}}
        with patch("scripts.conformance._json_command", return_value=payload):
            with self.assertRaisesRegex(RuntimeError, "engine_schema_mismatch"):
                _python_stats(Path("snapshot"))

    def test_corpus_digest_is_stable_and_fails_closed_on_fixture_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "v1"
            shutil.copytree(DEFAULT_CORPUS, copy)
            first = _corpus_digest(copy)
            self.assertEqual(first, _corpus_digest(copy))
            target = copy / "python" / "service.py"
            target.write_text(
                target.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "corpus_digest_mismatch"):
                _corpus_digest(copy)

    def test_run_receipt_attaches_raw_engine_payloads_and_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "snapshot.bin"
            snapshot_path.write_bytes(b"snapshot")
            stats = {
                "version": 2,
                "bytes": 1,
                "files": 1,
                "symbols": 0,
                "relations": 0,
                "sections": [],
                "generation": "g",
            }
            with (
                patch("scripts.conformance._python_stats", return_value=stats),
                patch("scripts.conformance._rust_stats", return_value=dict(stats)),
            ):
                receipt = run(snapshot_path, Path("rust"), corpus=DEFAULT_CORPUS)
        self.assertEqual("pass", receipt["status"])
        self.assertEqual(stats, receipt["engine_raw"]["python"])
        self.assertEqual(_canonical_digest(stats), receipt["engine_sha256"]["python"])
        self.assertEqual(64, len(receipt["corpus_sha256"]))
