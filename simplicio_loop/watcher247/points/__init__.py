"""The stage points of the watcher (#1509). The contract is in `registry.py`; each point is one module here.

Importing this package imports every submodule (sorted by name), and each calls `register(...)` at import,
so a new point is a new file, never an edit to `tick.py`.
"""
import importlib
import pkgutil

from .. import state
from .registry import (STAGES, STATUSES, PointBlocked, PointContext, PointInfo, PointResult, raise_if_blocked,
                       register, registered, run)

__all__ = ["STAGES", "STATUSES", "PointBlocked", "PointContext", "PointInfo", "PointResult", "raise_if_blocked",
           "register", "registered", "run"]

_IMPORT_FAILURES: list[tuple[str, BaseException]] = []


def _failed_import_point(module: str, exc: BaseException, stage: str) -> None:
    """Register a point that reports, at `stage`, that `module` failed to import; the watcher keeps running."""
    name = f"import_failed:{module}:{stage}"

    async def report(ctx: PointContext) -> PointResult:
        evidence = {"module": module, "type": type(exc).__name__, "error": str(exc)[:300]}
        return PointResult(name, "error", evidence, "point_import_failed")

    register(name, stage, report)


def _load_submodules() -> None:
    """Import every point module; one that fails is isolated and reported on every stage, never raised."""
    for module in sorted(info.name for info in pkgutil.iter_modules(__path__)):
        if module == "registry":
            continue
        try:
            importlib.import_module(f"{__name__}.{module}")
        except Exception as exc:
            _IMPORT_FAILURES.append((module, exc))
            state.log(f"point import failed {module}: {exc}")
            for stage in STAGES:
                _failed_import_point(module, exc, stage)


_load_submodules()
