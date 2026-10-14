"""-z records stay aligned around renames (#1574 review): a rename record carries TWO paths."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.central_overlay import apply_overlay  # noqa: E402
from simplicio_mapper.mapper.parse import _git_status_map  # noqa: E402

import orjson  # noqa: E402


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


def _body(stem: str, tag: str) -> str:
    return f"def {stem}_{tag}():\n    return 1\n"


class RenameAlignmentTests(unittest.TestCase):
    def test_renames_interleaved_with_same_size_edits_keep_every_record_aligned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = str(base / "cache")
            self.addCleanup(os.environ.pop, "SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
            main, wt = base / "main", base / "wt"
            main.mkdir()
            _git(["init", "-q", "--initial-branch", "main"], main)
            _git(["config", "user.email", "t@example.com"], main)
            _git(["config", "user.name", "T"], main)
            names = ["Alpha_ren.py", "b_edit.py", "c_del.py", "Echo_ren.py", "f_edit.py", "h_ren.py", "i_edit.py", "j_edit.py"]
            for name in names:
                (main / name).write_text(_body(name[:-3], "aa"), encoding="utf-8")
            (main / ".gitignore").write_text(".simplicio-loop/\n", encoding="utf-8")
            _git(["add", "-A"], main)
            _git(["commit", "-q", "-m", "base"], main)
            _git(["worktree", "add", "-q", "-b", "feat", str(wt), "main"], main)
            self.assertEqual(apply_overlay(str(wt)).receipt["status"], "ok")  # builds the base

            # Committed hop: renames before and between same-size edits, a delete, an add.
            _git(["mv", "Alpha_ren.py", "Alpha_ren2.py"], wt)
            (wt / "b_edit.py").write_text(_body("b_edit", "bb"), encoding="utf-8")
            _git(["rm", "-q", "c_del.py"], wt)
            _git(["mv", "Echo_ren.py", "Echo_ren2.py"], wt)
            (wt / "f_edit.py").write_text(_body("f_edit", "bb"), encoding="utf-8")
            (wt / "d_add.py").write_text(_body("d_add", "bb"), encoding="utf-8")
            _git(["add", "-A"], wt)
            _git(["commit", "-q", "-m", "c1"], wt)
            # Uncommitted hop: a staged rename followed by same-size edits of later files.
            _git(["mv", "h_ren.py", "h_ren2.py"], wt)
            (wt / "i_edit.py").write_text(_body("i_edit", "bb"), encoding="utf-8")
            (wt / "j_edit.py").write_text(_body("j_edit", "bb"), encoding="utf-8")

            outcome = apply_overlay(str(wt))
            self.assertEqual(outcome.receipt["status"], "ok", outcome.receipt)
            self.assertEqual(
                outcome.receipt["delta"],
                {
                    "added": ["d_add.py"],
                    "modified": ["b_edit.py", "f_edit.py", "i_edit.py", "j_edit.py"],
                    "removed": ["c_del.py"],
                    "renamed": [
                        "Alpha_ren.py -> Alpha_ren2.py", "Echo_ren.py -> Echo_ren2.py", "h_ren.py -> h_ren2.py",
                    ],
                },
            )
            symbols = {s["name"] for s in orjson.loads((wt / ".simplicio-loop" / "symbol-index.json").read_bytes())["symbols"]}
            for fresh in ("b_edit_bb", "f_edit_bb", "d_add_bb", "i_edit_bb", "j_edit_bb"):
                self.assertIn(fresh, symbols)
            for stale in ("b_edit_aa", "f_edit_aa", "i_edit_aa", "j_edit_aa", "c_del_aa"):
                self.assertNotIn(stale, symbols)

    def test_git_status_map_has_exactly_the_real_paths_after_a_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _git(["init", "-q", "--initial-branch", "main"], repo)
            _git(["config", "user.email", "t@example.com"], repo)
            _git(["config", "user.name", "T"], repo)
            (repo / "Docs").mkdir()
            (repo / "Docs" / "Readme.md").write_text("# readme\n", encoding="utf-8")
            (repo / "yy.py").write_text("def yy():\n    return 1\n", encoding="utf-8")
            _git(["add", "-A"], repo)
            _git(["commit", "-q", "-m", "base"], repo)
            _git(["mv", "Docs/Readme.md", "Docs/Moved.md"], repo)
            status = _git_status_map(str(repo))
            self.assertEqual(sorted(status), ["Docs/Moved.md"], status)


if __name__ == "__main__":
    unittest.main()
