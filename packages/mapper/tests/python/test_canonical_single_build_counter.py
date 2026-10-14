"""Requests from several worktrees at once cause exactly ONE base build, proven by a counter (#1574)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_CHILD = textwrap.dedent(
    """
    import json, os, sys
    from simplicio_mapper.mapper import canonical_builder as cb
    real = cb.build_artifacts
    def counted(*args, **kwargs):
        with open(os.environ["BUILD_COUNTER"], "a", encoding="utf-8") as handle:
            handle.write("x\\n")
        return real(*args, **kwargs)
    cb.build_artifacts = counted
    result = cb.build_canonical_manifest_with_diagnostics(sys.argv[1], sys.argv[2], "cfg")
    print(json.dumps({"reason": result.reason_code, "digest": result.manifest.key.digest()}))
    """
)


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout


class SingleBuildAcrossWorktreesTests(unittest.TestCase):
    def test_six_processes_from_three_worktrees_build_the_base_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            main = base / "main"
            main.mkdir()
            _git(["init", "-q", "--initial-branch", "main"], main)
            _git(["config", "user.email", "t@example.com"], main)
            _git(["config", "user.name", "T"], main)
            for index in range(30):
                (main / f"mod{index}.py").write_text(f"def f{index}():\n    return {index}\n", encoding="utf-8")
            _git(["add", "-A"], main)
            _git(["commit", "-q", "-m", "init"], main)
            worktrees = [main]
            for index in range(2):
                path = base / f"wt{index}"
                _git(["worktree", "add", "-q", "-b", f"w{index}", str(path)], main)
                worktrees.append(path)
            # A worktree with its own uncommitted edit asks for the SAME base.
            (worktrees[1] / "mod0.py").write_text("def changed():\n    return 0\n", encoding="utf-8")

            cache = base / "cache"
            counter = base / "builds.count"
            env = dict(os.environ, PYTHONPATH=str(ROOT), BUILD_COUNTER=str(counter))
            procs = [
                subprocess.Popen(
                    [sys.executable, "-c", _CHILD, str(worktrees[index % 3]), str(cache)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                )
                for index in range(6)
            ]
            payloads = []
            for proc in procs:
                out, err = proc.communicate(timeout=120)
                self.assertEqual(proc.returncode, 0, err)
                payloads.append(json.loads(out.strip()))

            self.assertEqual(counter.read_text(encoding="utf-8").count("x"), 1, "the pipeline ran more than once")
            reasons = sorted(payload["reason"] for payload in payloads)
            self.assertEqual(reasons.count("built") + reasons.count("built_after_wait"), 1, reasons)
            self.assertTrue(
                all(reason in {"built", "reused_cache_hit", "reused_after_wait"} for reason in reasons), reasons
            )
            self.assertEqual(len({payload["digest"] for payload in payloads}), 1)
            self.assertEqual(len(os.listdir(cache / "canonical")), 1)
            self.assertFalse((cache / "scratch").exists() and os.listdir(cache / "scratch"))


if __name__ == "__main__":
    unittest.main()
