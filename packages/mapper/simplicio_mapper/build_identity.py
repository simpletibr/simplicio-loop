"""Identity of this simplicio-mapper build: where it came from and which commit it was built at.

Two builds can share a version number (0.26.35 exists both in this monorepo and in the
standalone repo), so the version alone cannot tell them apart. A wheel build stamps
``origin`` and ``source_commit`` into ``_build_stamp.json`` (see ``build_stamp``). An editable
install of this monorepo has no stamp and falls back to the checkout's git HEAD. Anything
else reports ``source == "unstamped"`` and a ``None`` origin and commit.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import __version__

ORIGIN = "simplicio-loop/packages/mapper"
STATE_DIR = ".simplicio-loop"
STAMP_FILENAME = "_build_stamp.json"

_PACKAGE_DIR = Path(__file__).resolve().parent
_STAMP_PATH = _PACKAGE_DIR / STAMP_FILENAME
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _git_head(cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and _SHA.match(sha) else None


def _checkout_commit() -> str | None:
    """HEAD of the monorepo, only when this package really lives inside that checkout."""
    try:
        result = subprocess.run(["git", "-C", str(_PACKAGE_DIR), "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    top = Path(result.stdout.strip()).resolve()
    if (top / "packages" / "mapper" / "simplicio_mapper").resolve() != _PACKAGE_DIR:
        return None
    return _git_head(top)


def build_identity() -> dict[str, str | None]:
    """Return the identity of the mapper that is actually imported."""
    try:
        stamp = json.loads(_STAMP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stamp = None
    if isinstance(stamp, dict):
        source, origin, commit = "build", stamp.get("origin"), stamp.get("source_commit")
    else:
        commit = _checkout_commit()
        source, origin = ("checkout", ORIGIN) if commit else ("unstamped", None)
    return {"version": __version__, "origin": origin, "source_commit": commit,
            "state_dir": STATE_DIR, "source": source}


__all__ = ["ORIGIN", "STATE_DIR", "STAMP_FILENAME", "build_identity"]
