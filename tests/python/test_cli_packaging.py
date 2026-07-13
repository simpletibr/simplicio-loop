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
                f"{prefix}/contracts/context-snapshot/v1/schemas/context-snapshot.schema.json",
                sdist_names,
            )
            self.assertIn(
                f"{prefix}/contracts/task-orientation/v1/schemas/task-context.schema.json",
                sdist_names,
            )
            self.assertIn(
                f"{prefix}/contracts/ecosystem/v1/fixtures/python-task/execution.json",
                sdist_names,
            )
