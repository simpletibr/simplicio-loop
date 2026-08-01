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


if __name__ == "__main__":
    unittest.main()
