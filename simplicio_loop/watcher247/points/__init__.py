"""The stage points of the watcher (#1509). The contract is in `registry.py`; each point is one module here.

Importing this package imports every submodule (sorted by name), and each calls `register(...)` at import,
so a new point is a new file, never an edit to `tick.py`.
"""
import importlib
import pkgutil

from .registry import (STAGES, STATUSES, PointBlocked, PointContext, PointDeferred, PointInfo, PointResult,
                       raise_if_blocked, register, registered, run)

__all__ = ["STAGES", "STATUSES", "PointBlocked", "PointContext", "PointDeferred", "PointInfo", "PointResult",
           "raise_if_blocked", "register", "registered", "run"]

for _module in sorted(info.name for info in pkgutil.iter_modules(__path__)):
    if _module != "registry":
        importlib.import_module(f"{__name__}.{_module}")
