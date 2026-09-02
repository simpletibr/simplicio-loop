from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from simplicio_mapper.release_manifest import RELEASE_CAPABILITIES, RELEASE_COMPATIBILITY


ROOT = Path(__file__).resolve().parents[2]


class ReleaseSurfaceTest(unittest.TestCase):
    def test_package_version_sources_are_aligned(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/check-version-sync.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0.26.26", result.stdout)

    def test_readme_uses_live_release_routes(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("releases/tag/v0.25.0", readme)
        self.assertIn("releases/latest", readme)
        self.assertIn("GitHub releases", readme)

    def test_changelog_has_current_and_unreleased_boundaries(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [0.26.26] - 2026-09-02", changelog)
        self.assertIn("[Unreleased]: https://github.com/wesleysimplicio/simplicio-mapper/compare/v0.26.26...HEAD", changelog)
        self.assertIn("[0.26.25]: https://github.com/wesleysimplicio/simplicio-mapper/releases/tag/v0.26.25", changelog)

    def test_component_release_schema_and_manifest_vocabulary_exist(self) -> None:
        schema = json.loads(
            (ROOT / "contracts/component-release/v1/schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("capabilities", schema["required"])
        self.assertIn("compatibility", schema["required"])
        self.assertIn("simplicio.plugin.context-handle/v2", RELEASE_CAPABILITIES)
        self.assertEqual(RELEASE_COMPATIBILITY["simplicio-dev-cli"]["plugin-context-handle"], "v1|v2")


if __name__ == "__main__":
    unittest.main()
