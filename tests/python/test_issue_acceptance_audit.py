import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class IssueAcceptanceAuditTest(unittest.TestCase):
    def _run(self) -> dict:
        proc = subprocess.run(
            [sys.executable, "scripts/issue_acceptance_audit.py", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_audit_is_deterministic_and_honest_about_boundaries(self) -> None:
        first = self._run()
        second = self._run()
        self.assertEqual(first, second)
        self.assertEqual(first["schema"], "simplicio.issue-acceptance-audit/v1")
        self.assertEqual(first["repo"], "simplicio-mapper")

        issues = {issue["issue"]: issue for issue in first["issues"]}
        self.assertEqual(sorted(issues), [199, 208, 213])

        self.assertEqual(issues[199]["status"], "PARTIAL")
        self.assertEqual(issues[208]["status"], "PARTIAL")
        self.assertEqual(issues[213]["status"], "DONE")

        ac_199_17 = next(item for item in issues[199]["criteria"] if item["criterion_id"] == "199-AC17")
        self.assertEqual(ac_199_17["status"], "UNVERIFIED")
        self.assertIn("runtime-scale", ac_199_17["boundary"])

        ac_208_01 = next(item for item in issues[208]["criteria"] if item["criterion_id"] == "208-AC01")
        self.assertEqual(ac_208_01["status"], "DONE")
        self.assertTrue(ac_208_01["receipts"])

        ac_208_06 = next(item for item in issues[208]["criteria"] if item["criterion_id"] == "208-AC06")
        self.assertEqual(ac_208_06["status"], "DONE")
        self.assertTrue(ac_208_06["receipts"])

        ac_213_05 = next(item for item in issues[213]["criteria"] if item["criterion_id"] == "213-AC05")
        self.assertEqual(ac_213_05["status"], "DONE")
        self.assertTrue(ac_213_05["receipts"])

        all_boundaries = "\n".join(
            boundary
            for issue in issues.values()
            for boundary in issue["residual_boundaries"]
        )
        self.assertIn("simplicio-runtime", all_boundaries)
        self.assertIn("simplicio-dev-cli", all_boundaries)
        self.assertIn("simplicio-loop", all_boundaries)

    def test_every_criterion_has_replay_command_and_receipt_or_boundary(self) -> None:
        payload = self._run()
        for issue in payload["issues"]:
            for criterion in issue["criteria"]:
                self.assertTrue(criterion["commands"], criterion["criterion_id"])
                self.assertTrue(
                    criterion["receipts"] or criterion.get("boundary"),
                    criterion["criterion_id"],
                )


if __name__ == "__main__":
    unittest.main()
