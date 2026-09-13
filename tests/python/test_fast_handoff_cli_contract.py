"""Regression contract for the public Mapper -> Fast preparation path.

The fixture deliberately has no ContextSnapshot.  The preparation commands
must remain observable, and ``fast-handoff`` must fail closed with a durable
receipt and actionable guidance.  The guidance must point to a command that
the top-level public help advertises.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main


def _invoke(argv: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = main(argv)
        except SystemExit as error:
            code = int(error.code or 0)
    return code, stdout.getvalue(), stderr.getvalue()


class FastHandoffCliContractTest(unittest.TestCase):
    def test_public_preparation_and_missing_snapshot_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("# mapper fast handoff fixture\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")

            for argv in (
                ["index", str(root), "--json"],
                ["scan", str(root), "--sync", "--await", "--json"],
                ["inspect", str(root), "--await", "--json"],
                ["handoff", str(root), "--execution-context", "--await", "--json"],
                ["delta", str(root), "--full-rescan", "--json"],
            ):
                code, _stdout, stderr = _invoke(argv)
                self.assertEqual(code, 0, msg=f"{argv!r}: {stderr}")

            snapshot_path = root / ".simplicio" / "context-snapshot.json"
            self.assertFalse(snapshot_path.exists(), "preparation must not fabricate a snapshot")

            help_code, help_stdout, help_stderr = _invoke(["--help"])
            self.assertEqual(help_code, 0, help_stderr)
            self.assertIn("simplicio-mapper snapshot build", help_stdout)

            code, stdout, stderr = _invoke(["fast-handoff", str(root)])
            self.assertEqual(code, 2, stderr)
            payload = json.loads(stdout)
            self.assertIsNone(payload["handoff"])
            receipt = payload["receipt"]
            self.assertEqual(receipt["status"], "degraded")
            self.assertEqual(receipt["counters"]["degraded"], 1)
            self.assertIn("canonical_artifact_unavailable", receipt["reason"])
            self.assertIn("simplicio-mapper snapshot build", receipt["reason"])
            self.assertTrue((root / ".simplicio" / "fast-handoff-receipt.json").is_file())
            self.assertFalse((root / ".simplicio" / "fast-handoff.json").exists())


if __name__ == "__main__":
    unittest.main()
