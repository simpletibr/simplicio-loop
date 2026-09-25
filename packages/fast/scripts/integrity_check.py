#!/usr/bin/env python3
"""Compatibility entry point for the canonical release-integrity gate (#216)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_GATE = ROOT / "scripts" / "check_release_integrity.py"


def _load_canonical_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_simplicio_fast_release_integrity", CANONICAL_GATE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("canonical release-integrity gate is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CANONICAL = _load_canonical_gate()
SCHEMA = _CANONICAL.SCHEMA


def evaluate(root: Path = ROOT) -> dict[str, Any]:
    """Delegate evaluation without maintaining a second policy engine."""
    return _CANONICAL.evaluate(root)


def main(argv: list[str] | None = None) -> int:
    """Delegate the legacy CLI while retaining its repository-root default."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--root" not in arguments:
        arguments.extend(("--root", str(ROOT)))
    return _CANONICAL.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
