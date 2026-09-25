"""End-to-end contract for the public snapshot -> Fast handoff preparation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SnapshotFastHandoffIntegrationTest(unittest.TestCase):
    def _cli(self, repo: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(repo), env.get("PYTHONPATH", "")]
        ).strip(os.pathsep)
        executable = shutil.which("simplicio-mapper")
        if executable is None:
            executable_name = "simplicio-mapper.exe" if os.name == "nt" else "simplicio-mapper"
            candidate = Path(sys.executable).with_name(executable_name)
            executable = str(candidate) if candidate.is_file() else None
        if executable is None:
            self.fail("simplicio-mapper console script is required for this integration test")
        return subprocess.run(
            [executable, *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_public_snapshot_build_is_consumed_by_fast_handoff(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="mapper-snapshot-contract-") as temporary:
            workspace = Path(temporary)
            fixture = workspace / "fixture"
            launcher = workspace / "launcher"
            fixture.mkdir()
            launcher.mkdir()
            (fixture / "README.md").write_text("# fixture\n", encoding="utf-8")
            (fixture / "src").mkdir()
            (fixture / "src" / "main.py").write_text(
                "def main():\n    return 1\n", encoding="utf-8"
            )

            help_result = self._cli(repo, launcher, "--help")
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("simplicio-mapper snapshot build", help_result.stdout)

            index_result = self._cli(repo, launcher, "index", str(fixture), "--json")
            self.assertEqual(index_result.returncode, 0, index_result.stderr)

            snapshot_path = fixture / ".simplicio" / "context-snapshot.json"
            handoff_path = fixture / ".simplicio" / "fast-handoff.json"
            handoff_receipt_path = fixture / ".simplicio" / "fast-handoff-receipt.json"

            blocked = self._cli(repo, launcher, "fast-handoff", str(fixture))
            self.assertEqual(blocked.returncode, 2, blocked.stderr)
            blocked_envelope = json.loads(blocked.stdout)
            self.assertIsNone(blocked_envelope["handoff"])
            self.assertEqual(blocked_envelope["receipt"]["status"], "degraded")
            self.assertFalse(handoff_path.exists())

            build = self._cli(
                repo, launcher, "snapshot", "build", str(fixture), "--json"
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            snapshot = json.loads(build.stdout)
            self.assertEqual(snapshot["schema"], "simplicio.context-snapshot/v1")
            self.assertRegex(snapshot["snapshot_id"], r"^[0-9a-f]{64}$")
            self.assertRegex(snapshot["root_hash"], r"^[0-9a-f]{64}$")
            self.assertTrue(snapshot_path.is_file())
            self.assertEqual(json.loads(snapshot_path.read_text(encoding="utf-8")), snapshot)
            backend_receipt_path = fixture / ".simplicio" / "fast-backend-receipt.json"
            self.assertTrue(backend_receipt_path.is_file())
            backend_receipt = json.loads(backend_receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(
                backend_receipt["schema"],
                "simplicio.mapper-fast-backend-receipt/v1",
            )
            self.assertEqual(backend_receipt["selected_backend"], "mapper")
            self.assertEqual(backend_receipt["status"], "degraded")
            self.assertEqual(backend_receipt["reason"], "fast_manifest_absent")

            for digest in snapshot["freshness"]["artifact_hashes"].values():
                self.assertRegex(digest, r"^[0-9a-f]{64}$")

            validate = self._cli(
                repo,
                launcher,
                "snapshot",
                "validate",
                str(snapshot_path),
                "--json",
            )
            self.assertEqual(validate.returncode, 0, validate.stderr)
            validation = json.loads(validate.stdout)
            self.assertTrue(validation["valid"])

            ready = self._cli(repo, launcher, "fast-handoff", str(fixture))
            self.assertEqual(ready.returncode, 0, ready.stderr)
            envelope = json.loads(ready.stdout)
            handoff = envelope["handoff"]
            receipt = envelope["receipt"]
            self.assertEqual(handoff["schema"], "simplicio.mapper-fast-handoff/v1")
            self.assertIn("digest", handoff["canonical_map"])
            self.assertRegex(receipt["handoff_sha256"], r"^[0-9a-f]{64}$")
            self.assertIn(receipt["status"], {"parsed", "reused"})
            self.assertEqual(receipt["counters"]["degraded"], 0)
            self.assertTrue(handoff_path.is_file())
            self.assertTrue(handoff_receipt_path.is_file())

            verify = self._cli(
                repo, launcher, "fast-handoff", str(fixture), "--verify"
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertTrue(json.loads(verify.stdout)["valid"])

            artifact_digest = hashlib.sha256(
                snapshot_path.read_bytes()
            ).hexdigest()
            self.assertEqual(
                next(
                    item["sha256"]
                    for item in handoff["artifacts"]
                    if item["name"] == "context_snapshot"
                ),
                artifact_digest,
            )


if __name__ == "__main__":
    unittest.main()
