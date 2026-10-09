"""Test helper for the split runner (#1606): replace one name in every runner module that binds it.

Before the split every helper lived in ``simplicio_loop.runner`` and one ``setattr`` on that
module changed all callers. The code now lives in the ``runner_*`` modules, and a caller reads
the name in its own module. ``patch_runner`` reproduces the old single patch: it sets the name
in each runner module that binds it, and fails when no module does (a typo cannot pass silently).
"""
from __future__ import annotations

from simplicio_loop import (
    runner,
    runner_core,
)

RUNNER_MODULES = (
    runner,
    runner_core,
)


def patch_runner(monkeypatch, name, value, **kwargs):
    bound = [module for module in RUNNER_MODULES if name in vars(module)]
    assert bound, f"{name!r} is not bound in any runner module"
    for module in bound:
        monkeypatch.setattr(module, name, value, **kwargs)
