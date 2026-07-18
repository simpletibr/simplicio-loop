"""Doc/receipt-schema drift guard for the async pipeline operational guide
(issue #264, ADR-009).

Issue #264's acceptance criteria require documenting
``SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES``/``SIMPLICIO_MAPPER_FILE_TIMEOUT_S``,
uvloop opt-in/fallback, Windows fallback, cancellation/backpressure, and
rollback/troubleshooting -- and require that the benchmark receipt schema
stay reproducible. This module does not re-test pipeline behavior (that is
``test_async_pipeline.py``'s job); it asserts the *documentation* stays in
sync with the *code* it describes, so a future rename of either env var (or
a change to the benchmark JSON schema) fails a test instead of silently
leaving stale docs behind.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.async_pipeline import (  # noqa: E402
    _FILE_TIMEOUT_ENV,
    _MAX_CONCURRENT_ENV,
)

OPERATIONS_DOC = ROOT / "docs" / "async-pipeline-operations.md"
ADR_009 = ROOT / ".specs" / "architecture" / "ADR-009-async-mapping-pipeline.md"
BASELINE_JSON = ROOT / "docs" / "evidence" / "async-pipeline-baseline-benchmark.json"
AFTER_JSON = ROOT / "docs" / "evidence" / "async-pipeline-after-benchmark.json"
AFTER_LINUX_JSON = ROOT / "docs" / "evidence" / "async-pipeline-after-benchmark-linux-container.json"
AFTER_LINUX_MD = ROOT / "docs" / "async-pipeline-after-benchmark-linux-container.md"


class OperationalGuideExistsTest(unittest.TestCase):
    def test_operations_doc_exists(self) -> None:
        self.assertTrue(
            OPERATIONS_DOC.exists(),
            f"expected operational guide at {OPERATIONS_DOC}",
        )


class OperationalGuideEnvVarDriftTest(unittest.TestCase):
    """The two tunable env vars named in issue #264 AC4 must be documented
    under their REAL names, sourced from the code, not hardcoded in the
    test -- so a future rename of either constant in async_pipeline.py
    fails this test instead of leaving the doc silently stale."""

    def setUp(self) -> None:
        self.text = OPERATIONS_DOC.read_text(encoding="utf-8")

    def test_max_concurrent_files_env_var_documented(self) -> None:
        self.assertIn(_MAX_CONCURRENT_ENV, self.text)

    def test_file_timeout_env_var_documented(self) -> None:
        self.assertIn(_FILE_TIMEOUT_ENV, self.text)

    def test_uvloop_section_present(self) -> None:
        self.assertIn("uvloop", self.text.lower())

    def test_windows_fallback_section_present(self) -> None:
        self.assertIn("Windows fallback", self.text)

    def test_cancellation_and_backpressure_section_present(self) -> None:
        self.assertIn("Cancellation and backpressure", self.text)

    def test_rollback_disable_section_present(self) -> None:
        lowered = self.text.lower()
        self.assertIn("rollback", lowered)
        self.assertIn("disable", lowered)

    def test_troubleshooting_covers_timeout_cache_and_event_loop(self) -> None:
        lowered = self.text.lower()
        for keyword in ("timeout", "sqlite", "event-loop conflicts".lower(), "degraded"):
            self.assertIn(keyword, lowered, f"expected '{keyword}' in operational guide")


class Adr009CrossReferenceTest(unittest.TestCase):
    """ADR-009 is the canonical design doc; the operational guide and the
    ADR must point at each other so a reader following either one finds the
    other."""

    def test_adr_009_references_operations_doc(self) -> None:
        text = ADR_009.read_text(encoding="utf-8")
        self.assertIn("async-pipeline-operations.md", text)

    def test_operations_doc_references_adr_009(self) -> None:
        text = OPERATIONS_DOC.read_text(encoding="utf-8")
        self.assertIn("ADR-009", text)


class BenchmarkReceiptSchemaTest(unittest.TestCase):
    """Raw benchmark receipts (issue #264 AC3: 'machine-readable raw
    benchmark receipts') must be valid JSON, share a schema tag across
    platforms, and carry the fields the operational guide and ADR-009
    quote numbers from -- catches a future benchmark-script change that
    silently drops a field these docs depend on."""

    REQUIRED_TOP_LEVEL = ("schema", "generated_at", "python_version", "results")
    REQUIRED_RESULT_KEYS = ("size", "file_count", "cold", "warm")

    def _load(self, path: Path) -> dict:
        self.assertTrue(path.exists(), f"missing benchmark receipt: {path}")
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_baseline_receipt_shape(self) -> None:
        payload = self._load(BASELINE_JSON)
        for key in self.REQUIRED_TOP_LEVEL:
            self.assertIn(key, payload)

    def test_after_receipt_shape(self) -> None:
        payload = self._load(AFTER_JSON)
        for key in self.REQUIRED_TOP_LEVEL:
            self.assertIn(key, payload)
        for result in payload["results"]:
            for key in self.REQUIRED_RESULT_KEYS:
                self.assertIn(key, result)

    def test_linux_container_receipt_shape_matches_after_schema(self) -> None:
        after_payload = self._load(AFTER_JSON)
        linux_payload = self._load(AFTER_LINUX_JSON)
        self.assertEqual(after_payload["schema"], linux_payload["schema"])
        for key in self.REQUIRED_TOP_LEVEL:
            self.assertIn(key, linux_payload)
        for result in linux_payload["results"]:
            for key in self.REQUIRED_RESULT_KEYS:
                self.assertIn(key, result)
            for cold_or_warm in ("cold", "warm"):
                self.assertIn("wall_median_s", result[cold_or_warm])
                self.assertIn("files_per_sec", result[cold_or_warm])

    def test_linux_container_report_exists_and_is_reproducible(self) -> None:
        self.assertTrue(AFTER_LINUX_MD.exists())
        text = AFTER_LINUX_MD.read_text(encoding="utf-8")
        # Reproducibility requirement (issue #264 AC3): environment,
        # commands, sample size and limitations must all be stated, not
        # just the numbers.
        for required in ("Environment", "Confidence and limitations", "--runs"):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
