"""Regression tests for issue #482's release asset gate."""

from __future__ import annotations

import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from scripts.check_release_assets import GateError, inspect_dist, receipt


class ReleaseAssets482Test(unittest.TestCase):
    def test_valid_wheel_and_sdist_have_stable_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            metadata = b"Metadata-Version: 2.1\nName: simplicio-fast\nVersion: 2.0.27\n"
            with zipfile.ZipFile(
                dist / "simplicio_fast-2.0.27-py3-none-any.whl", "w"
            ) as archive:
                archive.writestr("simplicio_fast-2.0.27.dist-info/METADATA", metadata)
            with tarfile.open(dist / "simplicio_fast-2.0.27.tar.gz", "w:gz") as archive:
                info = tarfile.TarInfo("simplicio_fast-2.0.27/PKG-INFO")
                info.size = len(metadata)
                archive.addfile(info, io.BytesIO(metadata))

            assets = inspect_dist(dist, "2.0.27")
            first = receipt(assets, "2.0.27", "0123456789abcdef0123456789abcdef01234567")
            second = receipt(assets, "2.0.27", "0123456789abcdef0123456789abcdef01234567")
            self.assertEqual(first["artifact_digest"], second["artifact_digest"])
            self.assertEqual(2, len(first["artifacts"]))

    def test_wrong_version_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            with zipfile.ZipFile(
                dist / "simplicio_fast-2.0.26-py3-none-any.whl", "w"
            ) as archive:
                archive.writestr(
                    "simplicio_fast-2.0.26.dist-info/METADATA",
                    "Name: simplicio-fast\nVersion: 2.0.26\n",
                )
            with self.assertRaises(GateError):
                inspect_dist(dist, "2.0.27")


if __name__ == "__main__":
    unittest.main()
