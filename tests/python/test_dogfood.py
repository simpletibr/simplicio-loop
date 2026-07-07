"""Tests for scripts/dogfood.py (issue #165, ecosystem self-dogfooding).

Loaded via importlib.util (hyphen-free but still a standalone CLI script,
same loading convention as tests/python/test_generate_ecosystem_doc.py).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "dogfood.py"
REAL_DOGFOOD_DIR = ROOT / "examples" / "ecosystem-dogfood"


def _load_module():
    spec = importlib.util.spec_from_file_location("dogfood", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CommittedSnapshotTest(unittest.TestCase):
    """The examples/ecosystem-dogfood/ snapshot this script produced is committed;
    verify it is actually present, current-shaped, and contract-valid via the
    script's own --check path (real execution, not a mock)."""

    def test_check_passes_against_the_committed_snapshot(self) -> None:
        module = _load_module()
        rc = module.main(["--check"])
        self.assertEqual(rc, 0)

    def test_curated_artifacts_present_and_schema_tagged(self) -> None:
        module = _load_module()
        for name in module.CURATED_ARTIFACTS:
            path = REAL_DOGFOOD_DIR / name
            self.assertTrue(path.exists(), f"missing {path}")
            data = json.loads(path.read_text())
            self.assertTrue(str(data.get("schema", "")).startswith("simplicio."))

    def test_meta_file_records_provenance(self) -> None:
        meta = json.loads((REAL_DOGFOOD_DIR / "_meta.json").read_text())
        self.assertEqual(meta["schema"], "simplicio.ecosystem-dogfood-meta/v1")
        self.assertEqual(meta["generated_by"], "scripts/dogfood.py")
        self.assertEqual(set(meta["curated_artifacts"]), {"project-map.json", "precedent-index.json", "architecture-inventory.json"})

    def test_readme_documents_the_cross_repo_recipe_as_documented_only(self) -> None:
        readme = (REAL_DOGFOOD_DIR / "README.md").read_text()
        self.assertIn("documented, not executed here", readme.lower())
        self.assertIn("simplicio-dev-cli", readme)
        self.assertIn("simplicio-loop", readme)


class CheckModeFailureTest(unittest.TestCase):
    """--check must fail loudly (never silently pass) when the snapshot is absent."""

    def test_check_fails_when_dogfood_dir_is_empty(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            module.DOGFOOD_DIR = tmp  # empty dir, no curated artifacts
            rc = module.check(None)
            self.assertEqual(rc, 1)


class RegenerateOnAFixtureTest(unittest.TestCase):
    """Runs the real regeneration path (real CLI subprocess, real contract
    validation) against a tiny synthetic fixture -- not this whole repo --
    to keep the test fast while still exercising genuine execution."""

    def test_regenerate_produces_valid_curated_artifacts(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            fixture_root = Path(tmp) / "fixture-repo"
            fixture_root.mkdir()
            (fixture_root / "src").mkdir()
            (fixture_root / "src" / "index.js").write_text("module.exports = () => 'hi';\n")
            (fixture_root / "package.json").write_text('{"name": "dogfood-fixture"}')

            dogfood_out = Path(tmp) / "dogfood-out"

            module.ROOT = str(fixture_root)
            module.SIMPLICIO_DIR = str(fixture_root / ".simplicio")
            module.DOGFOOD_DIR = str(dogfood_out)

            rc = module.regenerate(None)
            self.assertEqual(rc, 0)

            for name in module.CURATED_ARTIFACTS:
                self.assertTrue((dogfood_out / name).exists())
            self.assertTrue((dogfood_out / "_meta.json").exists())
            self.assertTrue((dogfood_out / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
