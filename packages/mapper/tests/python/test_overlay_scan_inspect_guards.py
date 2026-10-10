"""Guards for overlay state validation: M10-M13 (#1673).

Each test verifies one guard is in place.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

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


class OverlayGuardsTests(unittest.TestCase):
    """Test that guards reject invalid overlays."""

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

    def test_m12_wrong_schema_makes_overlay_invalid(self) -> None:
        """M12: overlay with wrong schema is invalid."""
        state = json.loads((self.state / "overlay.json").read_text(encoding="utf-8"))
        state["schema"] = "wrong"
        (self.state / "overlay.json").write_text(json.dumps(state), encoding="utf-8")
        _, payload = _run("inspect", str(self.wt), "--json")
        self.assertFalse(payload["status"]["artifacts_present"])

    def test_m13_missing_artifact_file_makes_overlay_invalid(self) -> None:
        """M13: overlay is invalid when artifact files are missing."""
        _, before = _run("inspect", str(self.wt), "--json")
        self.assertTrue(before["status"]["artifacts_present"])
        # Delete one artifact
        (self.state / OVERLAY_ARTIFACT_FILES["project_map"]).unlink()
        _, after = _run("inspect", str(self.wt), "--json")
        self.assertFalse(after["status"]["artifacts_present"])

    def test_m11_overlay_with_no_full_artifacts_is_fresh(self) -> None:
        """M11: overlay with no full artifacts must still be treated as fresh."""
        # First, verify overlay is created and scan reports it
        code, scan_result = _run("scan", str(self.wt), "--sync", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(scan_result["artifact_service"]["mode"] == "overlay")
        # Delete all heavy artifacts to ensure no full artifacts exist
        for heavy in HEAVY:
            p = self.state / heavy
            if p.exists():
                p.unlink()
        # Verify the overlay artifacts still exist
        for name in ["project_map", "symbol_index", "precedent_index"]:
            self.assertTrue((self.state / OVERLAY_ARTIFACT_FILES[name]).exists())
        # Verify that inspect still treats it as fresh with overlay artifacts
        code, inspect_result = _run("inspect", str(self.wt), "--json")
        self.assertEqual(code, 0)
        # With M11 guard in place, inspect should recognize the overlay as valid
        # and report fresh=True even without full artifacts
        self.assertTrue(inspect_result["status"]["fresh"],
                       "overlay with no full artifacts must be treated as fresh")
        self.assertTrue(inspect_result["status"]["artifacts_present"],
                       "overlay artifacts must be considered as artifacts_present")


if __name__ == "__main__":
    unittest.main()
