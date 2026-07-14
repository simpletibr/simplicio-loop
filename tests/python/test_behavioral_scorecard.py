import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class BehavioralScorecardTest(unittest.TestCase):
    def test_real_cli_scorecard_is_deterministic_and_measured(self) -> None:
        # NOTE: the script backing this scorecard is scripts/evaluation_scorecard.py
        # (schema "simplicio.behavioral-scorecard/v1", see docs/behavioral-scorecard.md).
        # scripts/behavioral_scorecard.py never existed in this repo; this test was
        # written against a name that was never landed. Point it at the real script.
        command = [sys.executable, "scripts/evaluation_scorecard.py", "--json"]
        first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        left = json.loads(first.stdout)
        right = json.loads(second.stdout)
        self.assertEqual(left["schema"], "simplicio.behavioral-scorecard/v1")
        self.assertEqual(left["status"], "pass")
        self.assertEqual(left["measurements"]["target_recall_at_k"], 1.0)
        self.assertEqual(left["measurements"]["test_recall_at_k"], 1.0)
        self.assertEqual(left["measurements"]["determinism"], 1.0)
        self.assertEqual(right["measurements"]["determinism"], 1.0)
        # `context_pack.pack_hash` is intentionally root-path-scoped
        # (simplicio_mapper/context_pack.py `root_hash = _sha256_text(abs_root)`,
        # by design -- prevents cross-repo cache collisions on identical content).
        # Each scorecard run copies fixtures into a fresh random tempdir
        # (`scripts/evaluation_scorecard.py::_copy_case`), so the fingerprint
        # itself legitimately differs run-to-run; per-run determinism is what
        # `first_fingerprint == second_fingerprint` inside a single run
        # measures, and that is already asserted via `measurements.determinism`
        # above. What must stay stable across independent runs is the case
        # identity/count and every per-case "deterministic" verdict.
        self.assertEqual([item["id"] for item in left["cases"]], [item["id"] for item in right["cases"]])
        self.assertTrue(all(item["deterministic"] for item in left["cases"]))
        self.assertTrue(all(item["deterministic"] for item in right["cases"]))
