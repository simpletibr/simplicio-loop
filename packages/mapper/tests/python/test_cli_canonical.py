"""End-to-end CLI coverage for `simplicio-mapper canonical gc <path>` (issue #268).

Drives the real `main()` entry point end to end, exactly as a user invoking
`simplicio-mapper canonical gc ...` would -- exercises argv dispatch
(`simplicio_mapper/cli/_canonical.py`), `--json`/`--apply` flags, and the
integration with `simplicio_mapper.mapper.canonical_gc.scan_canonical_gc`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "--initial-branch", "main"], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test User"], path)
    (path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)


class CanonicalGcCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        _init_repo(self.repo)
        self.cache_root = str(self.base / "cache")
        old = os.environ.get("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR")
        os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = self.cache_root

        def _restore() -> None:
            if old is None:
                os.environ.pop("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
            else:
                os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = old

        self.addCleanup(_restore)

    def test_gc_help(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "gc", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("canonical gc", out.getvalue())

    def test_gc_json_on_empty_storage_root(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "gc", str(self.repo), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.canonical-gc/v1")
        self.assertFalse(payload["apply"])
        self.assertEqual(payload["candidates"], [])

    def test_gc_dry_run_then_apply_reclaims_dead_temp_dir(self) -> None:
        from simplicio_mapper.mapper.canonical_builder import build_canonical_manifest

        build_canonical_manifest(str(self.repo), self.cache_root, "cfg-1")

        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait(timeout=10)
        tmp_dir = Path(self.cache_root) / "canonical" / f"digest-cli.tmp-{proc.pid}"
        tmp_dir.mkdir(parents=True)
        past = time.time() - 1000
        os.utime(tmp_dir, (past, past))

        dry_out = StringIO()
        with redirect_stdout(dry_out):
            code = main(["canonical", "gc", str(self.repo), "--json"])
        self.assertEqual(code, 0)
        dry_payload = json.loads(dry_out.getvalue())
        self.assertEqual(len(dry_payload["candidates"]), 1)
        self.assertEqual(dry_payload["recovered"], [])
        self.assertTrue(tmp_dir.is_dir())

        apply_out = StringIO()
        with redirect_stdout(apply_out):
            code = main(["canonical", "gc", str(self.repo), "--apply", "--json"])
        self.assertEqual(code, 0)
        apply_payload = json.loads(apply_out.getvalue())
        self.assertEqual(len(apply_payload["recovered"]), 1)
        self.assertFalse(tmp_dir.exists())

    def test_gc_human_readable_output_lists_candidates(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait(timeout=10)
        tmp_dir = Path(self.cache_root) / "canonical" / f"digest-human.tmp-{proc.pid}"
        tmp_dir.mkdir(parents=True)
        past = time.time() - 1000
        os.utime(tmp_dir, (past, past))

        out = StringIO()
        with redirect_stdout(out):
            code = main(["canonical", "gc", str(self.repo)])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("dry-run", text)
        self.assertIn("candidate", text)
        self.assertIn("temp_dir_builder_pid_dead", text)

    def test_unknown_canonical_subcommand_errors(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["canonical", "bogus"])
        self.assertEqual(code, 2)
        self.assertIn("unknown canonical subcommand", err.getvalue())

    def test_unknown_gc_option_errors(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["canonical", "gc", str(self.repo), "--nope"])
        self.assertEqual(code, 2)
        self.assertIn("unknown canonical gc option", err.getvalue())


if __name__ == "__main__":
    unittest.main()
