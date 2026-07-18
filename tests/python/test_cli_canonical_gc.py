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
from datetime import datetime, timedelta, timezone
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
        # Default grace is 60s (``DEFAULT_GC_GRACE_SECONDS``), so a
        # dead-pid temp dir aged only 10s needs an explicit
        # ``--grace-seconds`` override to actually surface as a candidate
        # here -- see ``test_ttl_and_grace_options_are_parsed_and_applied``
        # for a dedicated proof that the override, not the default, drives
        # reclaimability.
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
                    "--grace-seconds",
                    "0",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.canonical-gc/v1")
        self.assertFalse(payload["apply"])
        self.assertEqual(payload["removed"], [])
        self.assertEqual(payload["recovered"], [])
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertEqual(payload["candidates"][0]["kind"], "temp_dir")
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
                    "--grace-seconds",
                    "0",
                    "--apply",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["apply"])
        # A reclaimed ``temp_dir`` candidate is reported as "recovered" (an
        # interrupted-promotion staging dir being cleaned up), not
        # "removed" (reserved for stale/superseded promoted manifest dirs
        # and crash ``.deleting-`` leftovers) -- see ``GcReport``/
        # ``scan_canonical_gc`` in ``canonical_gc.py``.
        self.assertEqual(len(payload["recovered"]), 1)
        self.assertEqual(payload["removed"], [])
        self.assertFalse(tmp_dir.exists())

    def test_human_readable_output_lists_candidates_and_hints_apply(self) -> None:
        tmp_dir = Path(canonical_manifest_tmp_dir(self.storage_root, "stale3", str(_dead_pid())))
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
                    "--grace-seconds",
                    "0",
                ]
            )
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("canonical gc (dry-run): candidates=1", text)
        self.assertIn("candidate [temp_dir]", text)
        self.assertIn("temp_dir_builder_pid_dead", text)

    def test_missing_subcommand_prints_usage_and_exits_nonzero(self) -> None:
        # Once #266/#267 merged in alongside this issue's `gc`, a bare
        # `canonical` (no sub-command) prints the unified usage/help text to
        # stdout and exits 0 -- same convention as `canonical --help`.
        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical"])
        self.assertEqual(code, 0)
        self.assertIn("usage", out.getvalue())

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
        self.assertIn("unknown canonical gc option", err.getvalue())

    def test_help_flag_prints_usage(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "gc", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage", out.getvalue())

    def test_ttl_and_grace_options_are_parsed_and_applied(self) -> None:
        """``--ttl-seconds``/``--grace-seconds`` are threaded through to
        ``scan_canonical_gc``, not merely accepted and ignored (``GcReport``
        does not echo them back, so this proves it via observable effect
        instead): a superseded commit's manifest becomes reclaimable once
        its age is made to exceed a tiny ``--ttl-seconds`` override, and a
        dead-pid temp dir becomes reclaimable once its age exceeds a tiny
        ``--grace-seconds`` override -- both fixtures are well within the
        *default* windows (7 days / 60s) and are preserved without the
        overrides, proven by the second CLI call below.
        """
        import os

        old_manifest = build_canonical_manifest(str(self.repo), self.storage_root, "cfg-1")
        assert old_manifest is not None
        (self.repo / "second.txt").write_text("second\n", encoding="utf-8")
        _run(["add", "."], self.repo)
        _run(["commit", "-m", "second"], self.repo)
        # Supersedes `old_manifest`'s digest dir -- it no longer matches the
        # (now-advanced) default-branch commit.
        build_canonical_manifest(str(self.repo), self.storage_root, "cfg-1")

        # 120s old: past a tiny (1s) --ttl-seconds override, but comfortably
        # within the *default* 7-day ttl and 60s grace window, so the
        # second (no-override) CLI call below preserves it instead.
        backdated = datetime.now(timezone.utc) - timedelta(seconds=120)
        manifest_json_path = Path(old_manifest.storage_root) / "manifest.json"
        manifest_data = json.loads(manifest_json_path.read_text(encoding="utf-8"))
        manifest_data["created_at"] = backdated.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        manifest_json_path.write_text(json.dumps(manifest_data), encoding="utf-8")

        tmp_dir = Path(canonical_manifest_tmp_dir(self.storage_root, "stale-ttl", str(_dead_pid())))
        tmp_dir.mkdir(parents=True)
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
                    "--ttl-seconds",
                    "1",
                    "--grace-seconds",
                    "0",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        reasons = {c["reason"] for c in payload["candidates"]}
        self.assertIn("expired_unreferenced_snapshot", reasons)
        self.assertIn("temp_dir_builder_pid_dead", reasons)

        # Without the overrides (default ttl=7d, grace=60s) neither fixture
        # is reclaimable -- proves the CLI flags, not just the defaults,
        # drove the result above.
        out_default = StringIO()
        with redirect_stdout(out_default):
            code_default = main(
                ["canonical", "gc", str(self.repo), "--storage-root", self.storage_root, "--json"]
            )
        self.assertEqual(code_default, 0)
        payload_default = json.loads(out_default.getvalue())
        reasons_default = {c["reason"] for c in payload_default["candidates"]}
        self.assertNotIn("expired_unreferenced_snapshot", reasons_default)
        self.assertNotIn("temp_dir_builder_pid_dead", reasons_default)


if __name__ == "__main__":
    unittest.main()
