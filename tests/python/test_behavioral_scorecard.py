import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class BehavioralScorecardTest(unittest.TestCase):
    def test_real_cli_scorecard_is_deterministic_and_measured(self) -> None:
        command = [sys.executable, "scripts/behavioral_scorecard.py", "--json"]
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
        self.assertEqual(
            [item["first_fingerprint"] for item in left["cases"]],
            [item["first_fingerprint"] for item in right["cases"]],
        )
