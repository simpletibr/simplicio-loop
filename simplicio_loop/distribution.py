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


def _installed() -> Optional[metadata.Distribution]:
    try:
        return metadata.distribution("simplicio-loop")
    except metadata.PackageNotFoundError:
        return None


def is_editable() -> bool:
    """Installed with `pip install -e` (pip records it in direct_url.json)."""
    dist = _installed()
    try:
        raw = dist.read_text("direct_url.json") if dist else None
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
    return PIP if _installed() is not None else SOURCE


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
