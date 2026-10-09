"""The canonical builder materializes the base without a checkout copy that can leak (#1574).

Before: ``git worktree add --detach`` into an OS temp dir. A SIGTERM/SIGKILL mid-build left the
copy in /tmp and a registration in ``.git/worktrees`` behind. Now: a private-index
``read-tree`` + ``checkout-index`` into ``<cache>/scratch/<build>/`` (no ``git worktree``
registration, a ``build.lock`` the GC honours) that is removed in ``finally`` and on SIGTERM.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper import canonical_builder  # noqa: E402
from simplicio_mapper.mapper.canonical_builder import (  # noqa: E402
    build_canonical_manifest_with_diagnostics,
)


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout


def _repo(path: Path, files: int = 5) -> None:
    path.mkdir(parents=True)
    _git(["init", "-q", "--initial-branch", "main"], path)
    _git(["config", "user.email", "t@example.com"], path)
    _git(["config", "user.name", "T"], path)
    for index in range(files):
        (path / f"mod{index}.py").write_text(f"def f{index}():\n    return {index}\n", encoding="utf-8")
    (path / "run.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    os.chmod(path / "run.sh", 0o755)
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "init"], path)


class BuilderLeavesNothingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.repo = base / "repo"
        _repo(self.repo)
        self.cache = base / "cache"

    def _scratch_entries(self) -> list[str]:
        scratch = self.cache / "scratch"
        return sorted(os.listdir(scratch)) if scratch.is_dir() else []

    def _leftovers(self) -> list[str]:
        canonical = self.cache / "canonical"
        tmp = sorted(n for n in os.listdir(canonical) if ".tmp-" in n) if canonical.is_dir() else []
        return self._scratch_entries() + tmp

    def _build(self):
        return build_canonical_manifest_with_diagnostics(str(self.repo), str(self.cache), "cfg")

    def test_a_failing_pipeline_leaves_no_scratch_no_staging_no_worktree(self) -> None:
        with mock.patch.object(canonical_builder, "build_artifacts", side_effect=RuntimeError("boom")):
            result = self._build()
        self.assertIsNone(result.manifest)
        self.assertEqual(result.reason_code, "pipeline_failed")
        self.assertEqual(self._leftovers(), [])
        self.assertEqual(_git(["worktree", "list"], self.repo).count("\n"), 1)
        self.assertFalse((self.repo / ".git" / "worktrees").exists())

    def test_an_interrupt_inside_the_pipeline_still_cleans_up(self) -> None:
        with mock.patch.object(canonical_builder, "build_artifacts", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self._build()
        self.assertEqual(self._leftovers(), [])

    def test_a_successful_build_leaves_only_the_promoted_base(self) -> None:
        result = self._build()
        self.assertEqual(result.reason_code, "built")
        self.assertEqual(self._leftovers(), [])
        self.assertEqual(len(os.listdir(self.cache / "canonical")), 1)

    def test_no_git_worktree_is_registered_and_the_real_index_is_untouched(self) -> None:
        (self.repo / "mod0.py").write_text("def changed():\n    return 0\n", encoding="utf-8")
        _git(["add", "mod0.py"], self.repo)  # staged change the builder must not disturb
        staged_before = _git(["diff", "--cached", "--name-status"], self.repo)
        seen: dict[str, object] = {}
        real = canonical_builder.build_artifacts

        def spy(cwd, *args, **kwargs):
            seen["worktrees"] = _git(["worktree", "list"], self.repo).count("\n")
            seen["registered"] = (self.repo / ".git" / "worktrees").exists()
            seen["files"] = sorted(
                os.path.relpath(os.path.join(d, n), cwd)
                for d, _dirs, names in os.walk(cwd) for n in names
            )
            seen["mode"] = os.stat(os.path.join(cwd, "run.sh")).st_mode & 0o111
            seen["content"] = Path(cwd, "mod0.py").read_text(encoding="utf-8")
            seen["inside_scratch"] = os.path.commonpath([cwd, str(self.cache / "scratch")]) == str(
                self.cache / "scratch"
            )
            return real(cwd, *args, **kwargs)

        with mock.patch.object(canonical_builder, "build_artifacts", side_effect=spy):
            result = self._build()
        self.assertEqual(result.reason_code, "built")
        self.assertEqual(seen["worktrees"], 1)
        self.assertFalse(seen["registered"])
        self.assertTrue(seen["inside_scratch"])
        # The base is the committed default-branch tree, not the staged edit.
        self.assertIn("def f0()", seen["content"])
        self.assertEqual(seen["files"], sorted(_git(["ls-tree", "-r", "--name-only", "main"], self.repo).split()))
        self.assertTrue(seen["mode"], "the executable bit survives the checkout")
        self.assertEqual(_git(["diff", "--cached", "--name-status"], self.repo), staged_before)

    def test_sigterm_in_the_middle_of_a_build_cleans_up_before_exiting(self) -> None:
        script = textwrap.dedent(
            """
            import sys, time
            from simplicio_mapper.mapper import canonical_builder as cb
            def slow(cwd, *a, **k):
                print("READY", flush=True)
                time.sleep(60)
            cb.build_artifacts = slow
            cb.build_canonical_manifest_with_diagnostics(sys.argv[1], sys.argv[2], "cfg")
            """
        )
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        proc = subprocess.Popen(
            [sys.executable, "-c", script, str(self.repo), str(self.cache)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        )
        try:
            self.assertEqual(proc.stdout.readline().strip(), "READY")
            self.assertEqual(len(self._scratch_entries()), 1, "the build is in flight")
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=20)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(self._leftovers(), [])
        self.assertEqual(_git(["worktree", "list"], self.repo).count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
