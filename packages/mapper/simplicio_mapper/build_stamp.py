"""Write the build stamp read by ``build_identity``. Called only by the wheel build hooks."""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .build_identity import ORIGIN, STATE_DIR, _git_head


def write_stamp(source_root: Path, out: Path) -> dict[str, str | None]:
    """Record the origin and the HEAD commit of ``source_root``; ``None`` when git cannot say."""
    payload = {"version": __version__, "origin": ORIGIN,
               "source_commit": _git_head(Path(source_root)), "state_dir": STATE_DIR}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return payload
