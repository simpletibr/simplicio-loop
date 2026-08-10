from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.mapper_release_manifest import build_manifest, validate_manifest


class ReleaseManifestTest(unittest.TestCase):
    def test_manifest_binds_versions_and_artifact_checksum(self) -> None:
        root = Path(__file__).parents[2]
        manifest = build_manifest(root, ["pyproject.toml"])
        validate_manifest(root, manifest)
        self.assertEqual(manifest["schema"], "simplicio.mapper-release-manifest/v1")
        self.assertEqual(manifest["versions"]["pyproject"], manifest["versions"]["python"])

    def test_checksum_tampering_fails_closed(self) -> None:
        root = Path(__file__).parents[2]
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "artifact.whl"
            artifact.write_bytes(b"wheel")
            manifest = build_manifest(root, ["pyproject.toml"])
            manifest["artifacts"].append({"path": str(artifact), "sha256": "sha256:bad"})
            with self.assertRaises(ValueError):
                validate_manifest(root, manifest)

    def test_manifest_metadata_tampering_fails_closed(self) -> None:
        root = Path(__file__).parents[2]
        manifest = build_manifest(root)
        manifest["commit"] = "tampered"
        with self.assertRaises(ValueError):
            validate_manifest(root, manifest)




class ForceIncludeOverlapGateTest(unittest.TestCase):
    def test_current_pyproject_has_no_package_internal_force_include(self) -> None:
        from scripts.mapper_release_manifest import check_force_include_no_package_overlap

        root = Path(__file__).parents[2]
        self.assertEqual(check_force_include_no_package_overlap(root), [])

    def test_neural_force_include_is_rejected(self) -> None:
        from scripts.mapper_release_manifest import (
            _parse_hatch_packages_and_force_include,
            check_force_include_no_package_overlap,
        )

        root = Path(__file__).parents[2]
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
        packages, force = _parse_hatch_packages_and_force_include(text)
        self.assertIn("simplicio_mapper", packages)
        self.assertNotIn(
            "simplicio_mapper/store/neural/assets",
            force,
            msg="neural assets must not be force-included (issue #553)",
        )

        # Synthetic regression: re-adding the bad force-include entry must fail the gate.
        force_line = '"contracts" = "simplicio_mapper/contracts"'
        self.assertIn(force_line, text)
        poisoned = text.replace(
            force_line,
            force_line
            + "\n"
            + '"simplicio_mapper/store/neural/assets" = "simplicio_mapper/store/neural/assets"',
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)
            (fake / "pyproject.toml").write_text(poisoned, encoding="utf-8")
            errors = check_force_include_no_package_overlap(fake)
            self.assertTrue(any("neural" in e for e in errors), msg=errors)


if __name__ == "__main__":
    unittest.main()
