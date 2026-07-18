"""End-to-end CLI coverage for `simplicio-mapper canonical gc` (issue #268).

Drives the real CLI entry point (`main()`, `cli/_canonical.py::run_canonical_cli`)
against a scratch git repo, exactly as a user invoking
`simplicio-mapper canonical gc <root> ...` would -- the integration/system
slices of this issue's DoD (unit-level classification logic itself is
covered by `tests/python/test_canonical_gc.py`).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main
from simplicio_mapper.mapper.canonical_builder import build_canonical_manifest
from simplicio_mapper.mapper.canonical_storage import canonical_manifest_tmp_dir


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["init", "--initial-branch", "main"], path)
    _run(["config", "user.email", "test@example.com"], path)
    _run(["config", "user.name", "Test User"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run(["add", "."], path)
    _run(["commit", "-m", "init"], path)


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


class CanonicalGCCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        _init_repo(self.repo)
        self.storage_root = str(self.base / "storage")
        build_canonical_manifest(str(self.repo), self.storage_root, "cfg-1")

    def test_dry_run_json_reports_candidates_without_mutating(self) -> None:
        tmp_dir = Path(canonical_manifest_tmp_dir(self.storage_root, "stale", str(_dead_pid())))
        tmp_dir.mkdir(parents=True)
        stamp = time.time() - 10
        import os

        os.utime(tmp_dir, (stamp, stamp))

        out = StringIO()
        with redirect_stdout(out):
            code = main(
                [
                    "canonical",
                    "gc",
                    str(self.repo),
                    "--storage-root",
                    self.storage_root,
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.canonical-gc-receipt/v1")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["removed"], [])
        self.assertTrue(tmp_dir.is_dir(), "dry-run must never mutate the filesystem")

    def test_apply_flag_actually_removes_reclaimable_entries(self) -> None:
        tmp_dir = Path(canonical_manifest_tmp_dir(self.storage_root, "stale2", str(_dead_pid())))
        tmp_dir.mkdir(parents=True)
        import os

        stamp = time.time() - 10
        os.utime(tmp_dir, (stamp, stamp))

        out = StringIO()
        with redirect_stdout(out):
            code = main(
                [
                    "canonical",
                    "gc",
                    str(self.repo),
                    "--storage-root",
                    self.storage_root,
                    "--json",
                    "--apply",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["mode"], "apply")
        self.assertEqual(len(payload["removed"]), 1)
        self.assertFalse(tmp_dir.exists())

    def test_human_readable_output_lists_candidates_and_hints_apply(self) -> None:
        tmp_dir = Path(canonical_manifest_tmp_dir(self.storage_root, "stale3", str(_dead_pid())))
        tmp_dir.mkdir(parents=True)
        import os

        stamp = time.time() - 10
        os.utime(tmp_dir, (stamp, stamp))

        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "gc", str(self.repo), "--storage-root", self.storage_root])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("canonical gc mode=dry_run", text)
        self.assertIn("would-remove", text)
        self.assertIn("--apply", text)

    def test_missing_subcommand_prints_usage_and_exits_nonzero(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["canonical"])
        self.assertEqual(code, 2)
        self.assertIn("usage", err.getvalue())

    def test_unknown_subcommand_is_rejected(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["canonical", "bogus", str(self.repo)])
        self.assertEqual(code, 2)
        self.assertIn("unknown canonical subcommand", err.getvalue())

    def test_unknown_option_is_rejected(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["canonical", "gc", str(self.repo), "--not-a-flag"])
        self.assertEqual(code, 2)
        self.assertIn("unknown canonical option", err.getvalue())

    def test_help_flag_prints_usage(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "gc", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage", out.getvalue())

    def test_ttl_and_grace_options_are_parsed_and_applied(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(
                [
                    "canonical",
                    "gc",
                    str(self.repo),
                    "--storage-root",
                    self.storage_root,
                    "--json",
                    "--ttl-seconds",
                    "1",
                    "--grace-seconds",
                    "0",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["ttl_seconds"], 1.0)
        self.assertEqual(payload["promoted_grace_seconds"], 0.0)


if __name__ == "__main__":
    unittest.main()
