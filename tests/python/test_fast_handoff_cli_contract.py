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

    def test_task_aware_handoff_never_overwrites_the_canonical_snapshot_fast_reads(self) -> None:
        """Regression: a budget-pruned, task-aware `handoff --goal` used to
        overwrite the canonical `.simplicio/context-snapshot.json` with an
        alphabetical-prefix, symbol-starved graph — breaking `fast-handoff`
        (mapper_id_missing) for any consumer relying on the canonical file.
        """
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("# canonical snapshot fixture\n", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text(
                "def target_fn():\n    return 1\n", encoding="utf-8"
            )

            code, _stdout, stderr = _invoke(["index", str(root), "--json"])
            self.assertEqual(code, 0, stderr)

            build_code, build_stdout, build_stderr = _invoke(
                ["snapshot", "build", str(root), "--json"]
            )
            self.assertEqual(build_code, 0, build_stderr)
            canonical = json.loads(build_stdout)
            snapshot_path = root / ".simplicio" / "context-snapshot.json"
            self.assertTrue(snapshot_path.is_file())
            before = snapshot_path.read_text(encoding="utf-8")

            handoff_code, _handoff_stdout, handoff_stderr = _invoke(
                [
                    "handoff",
                    str(root),
                    "--goal",
                    "target_fn",
                    "--token-budget",
                    "64",
                    "--await",
                    "--json",
                ]
            )
            self.assertEqual(handoff_code, 0, handoff_stderr)

            after = snapshot_path.read_text(encoding="utf-8")
            self.assertEqual(before, after, "task-aware handoff must not mutate the canonical snapshot")
            self.assertEqual(json.loads(after)["snapshot_id"], canonical["snapshot_id"])

            scoped_path = root / ".simplicio" / "context-snapshot.task.json"
            self.assertTrue(scoped_path.is_file(), "bounded snapshot must be written to a task-scoped path")


if __name__ == "__main__":
    unittest.main()
