"""Guards for overlay state validation: M10-M13 (#1673)."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.mapper.central_overlay import OVERLAY_ARTIFACT_FILES  # noqa: E402
from test_central_overlay import _git, make_repo  # noqa: E402

HEAVY = ("call-graph.json", "architecture-inventory.json", "retrieval-index.json", "artifact-manifest.json")


def _run(*argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(list(argv))
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


class M10UnsafeBasedigests(unittest.TestCase):
    """M10: guard rejects unsafe base_digest (paths with separators, parent refs, etc)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.main_repo = base / "main"
        self.rels = make_repo(self.main_repo)
        self.cache_dir = base / "cache"
        os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = str(self.cache_dir)
        self.addCleanup(os.environ.pop, "SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
        self.wt = base / "wt"
        _git(["worktree", "add", "-q", "-b", "b-wt", str(self.wt), "main"], self.main_repo)
        code, _ = _run("canonical", "overlay", str(self.wt), "--json")
        self.assertEqual(code, 0)
        self.state = self.wt / ".simplicio-loop"
        self.overlay_file = self.state / "overlay.json"
        
        # Verify overlay starts valid
        _, result = _run("inspect", str(self.wt), "--json")
        self.assertTrue(result["status"]["artifacts_present"], "setup: overlay must start valid")
        
        # Save real base_digest for control
        self.valid_state = json.loads(self.overlay_file.read_text(encoding="utf-8"))
        self.real_digest = self.valid_state["base_digest"]
        
        # Create directories that match unsafe paths
        (self.cache_dir / "a").mkdir(exist_ok=True)
        (self.cache_dir / "a" / "b").mkdir(exist_ok=True)
        (self.cache_dir / "x").mkdir(exist_ok=True)

    def _test_m10_guard_rejects(self, unsafe_value: str) -> None:
        """Test that M10 guard rejects unsafe base_digest via _deep_phase (inspect)."""
        state = json.loads(self.overlay_file.read_text(encoding="utf-8"))
        
        # Change ONLY base_digest
        state["base_digest"] = unsafe_value
        self.overlay_file.write_text(json.dumps(state), encoding="utf-8")
        
        # M10 guard (via _overlay_base_present used by _deep_phase) must make overlay invalid
        # Inspect uses _deep_phase which checks _artifacts_available -> _overlay_serves -> _overlay_base_present
        _, inspect_result = _run("inspect", str(self.wt), "--json")
        self.assertFalse(inspect_result["status"]["artifacts_present"],
                        f"M10: unsafe base_digest={unsafe_value!r} must be invalid (guard at line 446)")
        
        # Control: restore real digest and verify overlay is valid again
        state["base_digest"] = self.real_digest
        self.overlay_file.write_text(json.dumps(state), encoding="utf-8")
        _, control = _run("inspect", str(self.wt), "--json")
        self.assertTrue(control["status"]["artifacts_present"],
                       "M10: control with real digest must be valid")

    def test_m10_parent_directory(self) -> None:
        """M10: '..' rejected (parent directory exists, guard at 446)."""
        self._test_m10_guard_rejects("..")

    def test_m10_empty_string(self) -> None:
        """M10: '' rejected (cache dir itself, guard at 446)."""
        self._test_m10_guard_rejects("")

    def test_m10_absolute_path(self) -> None:
        """M10: '/etc' rejected (absolute path, guard at 446)."""
        self._test_m10_guard_rejects("/etc")

    def test_m10_slash_separator(self) -> None:
        """M10: 'a/b' rejected (has /, guard at 446)."""
        self._test_m10_guard_rejects("a/b")

    def test_m10_parent_escape(self) -> None:
        """M10: 'x/..' rejected (escapes via /, guard at 446)."""
        self._test_m10_guard_rejects("x/..")

    def test_m10_dot_slash(self) -> None:
        """M10: './' rejected (has /, guard at 446)."""
        self._test_m10_guard_rejects("./")


class OverlayGuardsTests(unittest.TestCase):
    """Test M11-M13 guards."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.main_repo = base / "main"
        self.rels = make_repo(self.main_repo)
        os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = str(base / "cache")
        self.addCleanup(os.environ.pop, "SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
        self.wt = base / "wt"
        _git(["worktree", "add", "-q", "-b", "b-wt", str(self.wt), "main"], self.main_repo)
        code, _ = _run("canonical", "overlay", str(self.wt), "--json")
        self.assertEqual(code, 0)
        self.state = self.wt / ".simplicio-loop"

    def test_m12_wrong_schema(self) -> None:
        """M12: overlay with wrong schema is invalid (guard at line 437)."""
        state = json.loads((self.state / "overlay.json").read_text(encoding="utf-8"))
        state["schema"] = "wrong"
        (self.state / "overlay.json").write_text(json.dumps(state), encoding="utf-8")
        _, result = _run("inspect", str(self.wt), "--json")
        self.assertFalse(result["status"]["artifacts_present"])

    def test_m13_missing_artifact(self) -> None:
        """M13: overlay invalid when artifact files are missing (guard at line 439)."""
        _, before = _run("inspect", str(self.wt), "--json")
        self.assertTrue(before["status"]["artifacts_present"])
        (self.state / OVERLAY_ARTIFACT_FILES["project_map"]).unlink()
        _, after = _run("inspect", str(self.wt), "--json")
        self.assertFalse(after["status"]["artifacts_present"])

    def test_m11_overlay_no_full_artifacts(self) -> None:
        """M11: overlay with no full artifacts is still fresh (guard at line 471)."""
        code, scan = _run("scan", str(self.wt), "--sync", "--json")
        self.assertEqual(code, 0)
        for heavy in HEAVY:
            p = self.state / heavy
            if p.exists():
                p.unlink()
        code, result = _run("inspect", str(self.wt), "--json")
        self.assertEqual(code, 0)
        self.assertTrue(result["status"]["fresh"])
        self.assertTrue(result["status"]["artifacts_present"])


if __name__ == "__main__":
    unittest.main()
