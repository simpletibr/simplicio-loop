from __future__ import annotations

import json
import sys
from importlib import metadata, resources
from pathlib import Path

BINARY = "binary"
PIP = "pip"
SOURCE = "source"


class UnsupportedPlatform(ValueError):
    pass


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def kind(
    *,
    frozen: bool | None = None,
    editable: bool | None = None,
    checkout: bool | None = None,
) -> str:
    # Detect frozen if not provided
    if frozen is None:
        frozen = is_frozen()
    
    # Rule 1: frozen -> BINARY
    if frozen:
        return BINARY
    
    # Rule 2: editable or checkout -> SOURCE
    if editable is None:
        # Detect editable
        try:
            dist = metadata.distribution("simplicio-loop")
            direct_url_text = dist.read_text("direct_url.json")
            direct_url = json.loads(direct_url_text)
            editable = direct_url.get("dir_info", {}).get("editable", False)
        except (metadata.PackageNotFoundError, FileNotFoundError, json.JSONDecodeError):
            editable = False
    
    if editable:
        return SOURCE
    
    if checkout is None:
        # Detect checkout (.git exists)
        git_path = Path(__file__).resolve().parent.parent / ".git"
        checkout = git_path.exists()
    
    if checkout:
        return SOURCE
    
    # Rule 3: distribution exists -> PIP
    try:
        metadata.distribution("simplicio-loop")
        return PIP
    except metadata.PackageNotFoundError:
        pass
    
    # Rule 4: fallback -> SOURCE
    return SOURCE


def platform_key(system: str | None = None, machine: str | None = None) -> tuple[str, str]:
    if system is None:
        import platform
        system = platform.system()
    
    if machine is None:
        import platform
        machine = platform.machine()
    
    # Normalize system
    os_name = system.lower()
    if os_name not in ("linux", "darwin", "windows"):
        raise UnsupportedPlatform(f"Unsupported system: {system}")
    
    # Normalize machine/arch
    machine_lower = machine.lower()
    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    
    arch = arch_map.get(machine_lower)
    if arch is None:
        raise UnsupportedPlatform(f"Unsupported machine: {machine}")
    
    return (os_name, arch)


def binary_asset_name(version: str, os_name: str, arch: str) -> str:
    # Validate os_name
    if os_name not in ("linux", "darwin", "windows"):
        raise UnsupportedPlatform(f"Invalid os_name: {os_name}")
    
    # Validate arch
    if arch not in ("x86_64", "aarch64"):
        raise UnsupportedPlatform(f"Invalid arch: {arch}")
    
    # Normalize version: strip leading 'v' if present, then add exactly one
    if version.startswith("v") or version.startswith("V"):
        version = version[1:]
    
    name = f"simplicio-loop-v{version}-{os_name}-{arch}"
    
    # Add .exe for Windows
    if os_name == "windows":
        name += ".exe"
    
    return name


def bundle_root():
    return resources.files("simplicio_loop") / "_bundle"
