"""Schema/reproducibility smoke tests for the async-inventory benchmark
runner (issue #264, AC6 -- "add/adjust a test that asserts the benchmark
receipt schema or reproducibility").

Follows the same convention as `tests/python/test_runtime_scale_benchmark.py`
(import the `scripts/*_benchmark.py` module directly and assert on its
in-memory payload) rather than shelling out to the CLI, so this stays fast
enough to run in the regular unit suite -- it does not re-measure the real
small/medium/large sizes (that would be slow and belongs to manual
evidence-gathering runs, not CI), it exercises the exact same
`_benchmark_size`/`_render_markdown` code path against a tiny synthetic
tree so a schema regression here is a real regression, not a fixture
mismatch.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import async_inventory_benchmark as aib  # noqa: E402

_EXPECTED_PHASE_KEYS = {
    "wall_median_s",
    "wall_p95_s",
    "cpu_median_s",
    "peak_rss_mb",
    "files_per_sec",
}


class _TinySize(unittest.TestCase):
    """Shared helper: a tiny synthetic size spec so this test runs in well
    under a second, independent of the real report's small/medium/large
    sizes (those stay reserved for manual evidence-gathering runs).
    """

    SPEC = aib.SizeSpec(name="tiny", file_count=6)


class BenchmarkReceiptSchemaTest(_TinySize):
    def test_benchmark_size_reports_every_implementation_with_the_documented_shape(self) -> None:
        result = aib._benchmark_size(self.SPEC, runs=1)

        self.assertEqual(result["size"], "tiny")
        self.assertGreater(result["file_count"], 0)
        self.assertEqual(result["runs"], 1)

        # Every implementation this module knows about must appear, with the
        # exact same phase-level keys -- a missing implementation or a
        # renamed/missing metric is exactly the kind of schema drift this
        # test exists to catch.
        for label in aib._RUNNERS:
            self.assertIn(label, result, f"missing {label!r} in benchmark receipt")
            entry = result[label]
            self.assertIn("cold", entry)
            self.assertIn("warm", entry)
            self.assertIn("warm_vs_cold_speedup_ratio", entry)
            for phase in ("cold", "warm"):
                phase_payload = entry[phase]
                self.assertEqual(
                    set(phase_payload.keys()),
                    _EXPECTED_PHASE_KEYS,
                    f"{label}/{phase} phase keys drifted from the documented schema",
                )
                for key in _EXPECTED_PHASE_KEYS:
                    self.assertIsInstance(phase_payload[key], (int, float))

        # Every non-sync implementation must carry a speedup-vs-sync
        # comparison; the baseline (sync) itself must not carry one (it is
        # the reference, not a comparison against itself).
        self.assertNotIn("speedup_vs_sync", result["sync"])
        for label in aib._RUNNERS:
            if label == "sync":
                continue
            self.assertIn("speedup_vs_sync", result[label])
            self.assertEqual(set(result[label]["speedup_vs_sync"].keys()), {"cold", "warm"})

    def test_schema_shape_is_reproducible_across_independent_runs(self) -> None:
        """Running the same benchmark twice must yield the identical *shape*
        (same keys, same nesting, same value types) even though the actual
        timing numbers will differ run to run -- this is the
        "reproducibility" half of AC6: the schema is stable, not the wall
        clock.
        """

        def _shape(payload: dict, path: str = "") -> set[str]:
            keys: set[str] = set()
            for key, value in payload.items():
                full_key = f"{path}.{key}" if path else key
                keys.add(full_key)
                if isinstance(value, dict):
                    keys |= _shape(value, full_key)
            return keys

        first = aib._benchmark_size(self.SPEC, runs=1)
        second = aib._benchmark_size(self.SPEC, runs=1)

        self.assertEqual(_shape(first), _shape(second))
        # Sanity: the numbers themselves are allowed to differ (this is a
        # real wall-clock measurement, not a mock), but both runs must
        # still measure a positive amount of work.
        for label in aib._RUNNERS:
            self.assertGreater(first[label]["cold"]["wall_median_s"], 0.0)
            self.assertGreater(second[label]["cold"]["wall_median_s"], 0.0)


class BenchmarkTopLevelPayloadSchemaTest(_TinySize):
    def test_run_report_payload_matches_the_documented_json_schema_id(self) -> None:
        # Mirrors `_run_report`'s payload construction without writing to
        # disk (`write=False` semantics inline) so this test never touches
        # `docs/` during a normal `unittest`/CI run.
        original_sizes = aib.SIZES
        try:
            aib.SIZES = [self.SPEC]
            results = [aib._benchmark_size(spec, runs=1) for spec in aib.SIZES]
        finally:
            aib.SIZES = original_sizes

        payload = {
            "schema": aib.SCHEMA,
            "implementations": list(aib._RUNNERS.keys()),
            "results": results,
        }
        self.assertEqual(payload["schema"], "simplicio.async-inventory-benchmark/v1")
        self.assertIn("sync", payload["implementations"])
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["size"], "tiny")

    def test_markdown_render_includes_every_implementation_and_the_limitations_section(self) -> None:
        result = aib._benchmark_size(self.SPEC, runs=1)
        markdown = aib._render_markdown([result], "2026-01-01T00:00:00+00:00", "3.14.5", 1)
        for label in aib._RUNNERS:
            self.assertIn(f"`{label}`", markdown)
        self.assertIn("## Limitations", markdown)
        self.assertIn("## Reading these numbers", markdown)


if __name__ == "__main__":
    unittest.main()
