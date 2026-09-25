from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "context_cache_benchmark.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("context_cache_benchmark", SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib failure
        raise RuntimeError("failed to load context_cache_benchmark module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContextCacheBenchmarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def test_run_covers_all_required_scenarios(self) -> None:
        report = self.module.run()
        self.assertEqual(report["schema"], "simplicio.context-cache-benchmark/v1")
        names = [scenario["name"] for scenario in report["scenarios"]]
        self.assertEqual(
            names,
            [
                "cold-warm",
                "one-file-changed",
                "schema-changed",
                "corrupted-cache",
                "concurrent-access",
            ],
        )

        cold_warm = report["scenarios"][0]
        self.assertEqual(cold_warm["runs"][0]["cache"]["block"]["receipt"]["outcome"], "miss")
        self.assertEqual(cold_warm["runs"][1]["cache"]["block"]["receipt"]["outcome"], "hit")
        self.assertEqual(cold_warm["observations"]["warm_tokens_avoided"]["status"], "estimated")

        changed = report["scenarios"][1]
        self.assertNotEqual(
            changed["file"]["before_sha256"]["value"],
            changed["file"]["after_sha256"]["value"],
        )
        self.assertEqual(changed["runs"][1]["cache"]["block"]["receipt"]["outcome"], "miss")
        self.assertEqual(changed["runs"][2]["cache"]["block"]["receipt"]["outcome"], "hit")

        schema = report["scenarios"][2]
        self.assertEqual(schema["runs"][1]["cache"]["block"]["receipt"]["outcome"], "miss")
        self.assertEqual(schema["runs"][2]["cache"]["block"]["receipt"]["outcome"], "hit")
        self.assertEqual(schema["runs"][3]["cache"]["block"]["receipt"]["outcome"], "hit")

        corrupted = report["scenarios"][3]
        self.assertTrue(corrupted["preflight_quarantine"]["value"]["quarantined"])
        # The lookup right after tampering detects the checksum mismatch and
        # is honestly labeled "corrupt" (never silently served) rather than
        # a generic "miss" -- see context_cache.OUTCOME_CORRUPT / invariant 3.
        self.assertEqual(corrupted["runs"][1]["cache"]["block"]["receipt"]["outcome"], "corrupt")
        self.assertEqual(corrupted["runs"][2]["cache"]["block"]["receipt"]["outcome"], "hit")

        concurrent = report["scenarios"][4]
        self.assertEqual(concurrent["errors"]["value"], [])
        self.assertEqual(concurrent["workers"]["status"], "measured")
        self.assertEqual(concurrent["follow_up"]["cache"]["block"]["receipt"]["outcome"], "hit")
        self.assertGreaterEqual(len(concurrent["runs"]), 1)

    def test_cli_writes_replayable_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "benchmark.json"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--scenario", "cold-warm", "--out", str(out_path)],
                check=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            )
            report = json.loads(completed.stdout)
            written = json.loads(out_path.read_text(encoding="utf-8"))

        self.assertEqual(report["schema"], "simplicio.context-cache-benchmark/v1")
        self.assertEqual(written["schema"], report["schema"])
        self.assertEqual([scenario["name"] for scenario in report["scenarios"]], ["cold-warm"])


if __name__ == "__main__":
    unittest.main()
