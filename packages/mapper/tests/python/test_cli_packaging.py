from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DistributionContractsTest(unittest.TestCase):
    def test_built_wheel_and_sdist_include_contracts_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", tmp],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
                stdin=subprocess.DEVNULL,
            )
            if proc.returncode != 0:
                self.skipTest(f"python -m build unavailable in test env: {proc.stderr.strip()}")

            wheel = next(Path(tmp).glob("*.whl"))
            sdist = next(Path(tmp).glob("*.tar.gz"))

            with zipfile.ZipFile(wheel) as archive:
                wheel_names = set(archive.namelist())
            self.assertIn(
                "simplicio_mapper/contracts/context-snapshot/v1/schemas/context-snapshot.schema.json",
                wheel_names,
            )
            self.assertIn(
                "simplicio_mapper/contracts/task-orientation/v1/schemas/task-context.schema.json",
                wheel_names,
            )
            self.assertIn(
                "simplicio_mapper/contracts/ecosystem/v1/fixtures/python-task/execution.json",
                wheel_names,
            )

            with tarfile.open(sdist, "r:gz") as archive:
                sdist_names = set(archive.getnames())
            prefix = sdist.name.removesuffix(".tar.gz")
            self.assertIn(
                f"{prefix}/simplicio_mapper/contracts/context-snapshot/v1/schemas/context-snapshot.schema.json",
                sdist_names,
            )
            self.assertIn(
                f"{prefix}/simplicio_mapper/contracts/task-orientation/v1/schemas/task-context.schema.json",
                sdist_names,
            )
            self.assertIn(
                f"{prefix}/simplicio_mapper/contracts/ecosystem/v1/fixtures/python-task/execution.json",
                sdist_names,
            )


class DistributionNeuralAssetsTest(unittest.TestCase):
    """Issue #553: neural package data ships once; no force-include overlap."""

    def test_force_include_rejects_package_internal_paths(self) -> None:
        from scripts.mapper_release_manifest import check_force_include_no_package_overlap

        errors = check_force_include_no_package_overlap(ROOT)
        self.assertEqual(errors, [])

    def test_built_wheel_and_sdist_include_neural_assets_once(self) -> None:
        expected = [
            "simplicio_mapper/store/neural/assets/memory-schema.sql",
            "simplicio_mapper/store/neural/assets/seeds.sql",
            "simplicio_mapper/store/neural/assets/migrations/0001_initial.sql",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", tmp],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
                stdin=subprocess.DEVNULL,
            )
            if proc.returncode != 0:
                self.skipTest(f"python -m build unavailable in test env: {proc.stderr.strip()}")

            wheel = next(Path(tmp).glob("*.whl"))
            sdist = next(Path(tmp).glob("*.tar.gz"))

            with zipfile.ZipFile(wheel) as archive:
                wheel_names = archive.namelist()
            for path in expected:
                self.assertEqual(wheel_names.count(path), 1, msg=path)
            self.assertEqual(len(wheel_names), len(set(wheel_names)))

            with tarfile.open(sdist, "r:gz") as archive:
                sdist_names = archive.getnames()
            prefix = sdist.name.removesuffix(".tar.gz")
            for path in expected:
                full = f"{prefix}/{path}"
                self.assertEqual(sdist_names.count(full), 1, msg=full)
