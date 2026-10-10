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
    """M10: reject unsafe base_digest (path traversal attempts)."""

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

    def _test_m10_guard(self, unsafe_value: object) -> None:
        """Test that M10 guard rejects unsafe base_digest."""
        overlay_file = self.state / "overlay.json"
        state = json.loads(overlay_file.read_text(encoding="utf-8"))
        state["base_digest"] = unsafe_value
        overlay_file.write_text(json.dumps(state), encoding="utf-8")
        # M10 guard must cause inspect to treat overlay as invalid
        _, inspect_result = _run("inspect", str(self.wt), "--json")
        self.assertFalse(inspect_result["status"]["artifacts_present"],
                        f"M10: base_digest={unsafe_value!r} must be invalid")

    def test_m10_empty(self) -> None:
        """M10: empty base_digest rejected."""
        self._test_m10_guard("")

    def test_m10_double_dot(self) -> None:
        """M10: '..' base_digest rejected."""
        self._test_m10_guard("..")

    def test_m10_slash(self) -> None:
        """M10: base_digest with slash rejected."""
        self._test_m10_guard("a/b")

    def test_m10_absolute(self) -> None:
        """M10: absolute path rejected."""
        self._test_m10_guard("/etc")

    def test_m10_trailing_slash(self) -> None:
        """M10: trailing slash rejected."""
        self._test_m10_guard("a/")

    def test_m10_non_string_int(self) -> None:
        """M10: non-string (int) rejected."""
        self._test_m10_guard(42)

    def test_m10_non_string_null(self) -> None:
        """M10: non-string (null) rejected."""
        self._test_m10_guard(None)


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
        """M12: overlay with wrong schema is invalid."""
        state = json.loads((self.state / "overlay.json").read_text(encoding="utf-8"))
        state["schema"] = "wrong"
        (self.state / "overlay.json").write_text(json.dumps(state), encoding="utf-8")
        _, result = _run("inspect", str(self.wt), "--json")
        self.assertFalse(result["status"]["artifacts_present"])

    def test_m13_missing_artifact(self) -> None:
        """M13: overlay invalid when artifact files are missing."""
        _, before = _run("inspect", str(self.wt), "--json")
        self.assertTrue(before["status"]["artifacts_present"])
        (self.state / OVERLAY_ARTIFACT_FILES["project_map"]).unlink()
        _, after = _run("inspect", str(self.wt), "--json")
        self.assertFalse(after["status"]["artifacts_present"])

    def test_m11_overlay_no_full_artifacts(self) -> None:
        """M11: overlay with no full artifacts is still fresh."""
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
