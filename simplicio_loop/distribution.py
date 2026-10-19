"""How this simplicio-loop was installed: as a binary, as a wheel (pip) or as a source checkout (#1575).

`update` acts on it (a binary replaces itself, a wheel is reinstalled, a checkout is left to git) and `doctor` shows it.
The release artifact names are the contract with the binary build: `simplicio-loop-v<version>-<os>-<arch>[.exe]`.
"""
from __future__ import annotations

import json
import platform
import sys
from importlib import metadata, resources
from pathlib import Path
from typing import Optional

BINARY = "binary"
PIP = "pip"
SOURCE = "source"
OS_NAMES = ("linux", "darwin", "windows")
ARCHS = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}


class UnsupportedPlatform(ValueError):
    """No release artifact exists for this operating system or CPU."""


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


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


def kind(*, frozen: Optional[bool] = None, editable: Optional[bool] = None, checkout: Optional[bool] = None) -> str:
    """binary | source | pip. An argument that is None is detected."""
    if is_frozen() if frozen is None else frozen:
        return BINARY
    if is_editable() if editable is None else editable:
        return SOURCE
    if in_checkout() if checkout is None else checkout:
        return SOURCE
    return PIP if install_record() is not None else SOURCE


def platform_key(system: Optional[str] = None, machine: Optional[str] = None) -> tuple:
    """(os, arch) of this machine as the release names them: linux|darwin|windows, x86_64|aarch64."""
    os_name = (platform.system() if system is None else system).lower()
    arch = ARCHS.get((platform.machine() if machine is None else machine).lower())
    if os_name not in OS_NAMES:
        raise UnsupportedPlatform(f"no release for the operating system {system or platform.system()!r}")
    if arch is None:
        raise UnsupportedPlatform(f"no release for the CPU {machine or platform.machine()!r}")
    return os_name, arch


def binary_asset_name(version: str, os_name: str, arch: str) -> str:
    """`simplicio-loop-v3.49.0-linux-x86_64` (plus `.exe` for windows). A leading v in `version` is accepted."""
    if os_name not in OS_NAMES:
        raise UnsupportedPlatform(f"unknown operating system {os_name!r}")
    if arch not in set(ARCHS.values()):
        raise UnsupportedPlatform(f"unknown CPU {arch!r}")
    name = f"simplicio-loop-v{version.lstrip('vV')}-{os_name}-{arch}"
    return name + ".exe" if os_name == "windows" else name


def bundle_root():
    """The bundled skills, hooks and rules as a Traversable: works from a wheel, a checkout and a frozen binary."""
    return resources.files("simplicio_loop") / "_bundle"
