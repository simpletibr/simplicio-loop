"""Public bridge to the installed ``simplicio-mapper`` package.

This keeps ``simplicio-cli`` as the operational CLI while exposing the
underlying mapper dependency for downstream Python consumers that want a
single import surface from this distribution.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import version
from types import ModuleType
from typing import Any

_DIST_NAME = "simplicio-mapper"
_MODULE_NAME = "simplicio_mapper"


def mapper_module() -> ModuleType:
    """Return the installed ``simplicio_mapper`` module."""
    return import_module(_MODULE_NAME)


def mapper_version() -> str:
    """Return the installed ``simplicio-mapper`` distribution version."""
    return version(_DIST_NAME)


def __getattr__(name: str) -> Any:
    """Proxy attributes to the underlying ``simplicio_mapper`` module."""
    return getattr(mapper_module(), name)


__all__ = ["mapper_module", "mapper_version"]
