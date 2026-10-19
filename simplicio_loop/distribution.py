"""How this simplicio-loop was installed: as a wheel (pip) or as a source checkout (#1575).

`update` acts on it (a wheel is reinstalled, a checkout is left to git) and `doctor` shows it.
"""
from __future__ import annotations

import json
from importlib import metadata, resources
from pathlib import Path
from typing import Optional

PIP = "pip"
SOURCE = "source"


DISTRIBUTION = "simplicio-loop"


def install_record() -> Optional[metadata.Distribution]:
    """The simplicio-loop distribution pip wrote, or None when none is installed.

    `importlib.metadata` answers with the first match on sys.path, and the daemon puts its own checkout first there
    (daemon/client.py `_CHILD_BOOT`). An editable install leaves `simplicio_loop.egg-info` in that checkout: a build
    artifact with no direct_url.json, which would hide the record pip wrote (its version and its editable flag). So the
    record whose direct_url.json exists wins; with none, the first match. Every reader of the installed version or of
    the install kind goes through here, so the daemon and an in-process run give the same answer.
    """
    found = list(metadata.distributions(name=DISTRIBUTION))
    for record in found:
        if record.read_text("direct_url.json"):
            return record
    return found[0] if found else None


def installed_version() -> Optional[str]:
    """The version of the install record, or None when there is none."""
    record = install_record()
    return str(record.version) if record is not None and record.version else None


def is_editable() -> bool:
    """Installed with `pip install -e` (pip records it in direct_url.json)."""
    record = install_record()
    try:
        raw = record.read_text("direct_url.json") if record else None
        return bool(raw and json.loads(raw).get("dir_info", {}).get("editable"))
    except (ValueError, AttributeError, OSError):
        return False


def in_checkout() -> bool:
    """This code runs from a git checkout (`.git` is a folder, or a file in a worktree)."""
    return (Path(__file__).resolve().parent.parent / ".git").exists()


def kind(*, editable: Optional[bool] = None, checkout: Optional[bool] = None) -> str:
    """pip | source. An argument that is None is detected."""
    if is_editable() if editable is None else editable:
        return SOURCE
    if in_checkout() if checkout is None else checkout:
        return SOURCE
    return PIP if install_record() is not None else SOURCE


def bundle_root():
    """The bundled skills, hooks and rules as a Traversable: works from a wheel and a checkout."""
    return resources.files("simplicio_loop") / "_bundle"
