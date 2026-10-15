"""Build hooks for the single simplicio-loop wheel and sdist.

Metadata lives in pyproject.toml. This file adds two build steps:

* the mapper build stamp (packages/mapper/simplicio_mapper/build_identity.py) records which commit
  built the bundled simplicio_mapper;
* the pip bundle ``simplicio_loop/_bundle/`` (#1817) is GENERATED from the canonical sources
  (``.claude/skills``, ``hooks``, the LEAN ``scripts``/``tests`` subsets, ``adapters/claude``,
  ``packaging/host-rules``) by ``scripts/sync_bundle.py`` right before the wheel or the sdist is
  built, so it is never committed. An sdist carries the bundle it was built with, so a wheel built
  from that sdist (where the canonical sources are absent) ships the same bundle unchanged.
"""

import importlib.util
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "packages" / "mapper"))

from simplicio_mapper.build_identity import STAMP_FILENAME
from simplicio_mapper.build_stamp import write_stamp


def _generate_bundle():
    """Regenerate simplicio_loop/_bundle/ from source; a no-op where the canonical sources are absent."""
    if not ((ROOT / ".claude" / "skills").is_dir() and (ROOT / "scripts" / "sync_bundle.py").is_file()):
        return
    # Load by path: putting scripts/ on sys.path would shadow unrelated module names during the build.
    spec = importlib.util.spec_from_file_location("_sync_bundle_build", ROOT / "scripts" / "sync_bundle.py")
    sync_bundle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync_bundle)
    sync_bundle.sync()


class StampedBuildPy(build_py):
    def run(self):
        _generate_bundle()
        super().run()
        write_stamp(ROOT, Path(self.build_lib) / "simplicio_mapper" / STAMP_FILENAME)


class BundledSdist(sdist):
    def run(self):
        _generate_bundle()
        super().run()


setup(cmdclass={"build_py": StampedBuildPy, "sdist": BundledSdist})
