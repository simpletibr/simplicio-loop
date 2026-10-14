"""Hatch build hook: ships the origin and source commit of this build inside the wheel."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from simplicio_mapper.build_identity import STAMP_FILENAME  # noqa: E402
from simplicio_mapper.build_stamp import write_stamp  # noqa: E402


class StampHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        out = Path(tempfile.mkdtemp(prefix="mapper-stamp-")) / STAMP_FILENAME
        write_stamp(_HERE, out)
        build_data["force_include"][str(out)] = f"simplicio_mapper/{STAMP_FILENAME}"
