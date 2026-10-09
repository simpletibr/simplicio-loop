"""Stamps the origin and source commit into the bundled simplicio_mapper of the single wheel.

Metadata lives in pyproject.toml; this file only adds the build step that records which commit
built the mapper (see packages/mapper/simplicio_mapper/build_identity.py).
"""

import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "packages" / "mapper"))

from simplicio_mapper.build_identity import STAMP_FILENAME
from simplicio_mapper.build_stamp import write_stamp


class StampedBuildPy(build_py):
    def run(self):
        super().run()
        write_stamp(ROOT, Path(self.build_lib) / "simplicio_mapper" / STAMP_FILENAME)


setup(cmdclass={"build_py": StampedBuildPy})
