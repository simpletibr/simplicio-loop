"""Package-side access to the ``simplicio.dashboard-event/v1`` stream (issue #1398).

The implementation lives in ``scripts/dashboard_events.py`` (stdlib only) so the hooks of a plugin
install can import it without the package. This module loads that one file from the source
checkout (``scripts/``) or from the installed wheel (``simplicio_loop/_bundle/scripts/``) and
exposes fail-open seams for the runner. Consumers such as the dashboard backend read with
``read_events(run_dir, since_seq)``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Mapping, Optional

_MODULE_NAME = "dashboard_events"
_CANDIDATES = (
    Path(__file__).resolve().parent.parent / "scripts" / "dashboard_events.py",
    Path(__file__).resolve().parent / "_bundle" / "scripts" / "dashboard_events.py",
)
_loaded: List[ModuleType] = []


def load() -> Optional[ModuleType]:
    """Return the emitter module, or None when neither copy is present."""
    if _loaded:
        return _loaded[0]
    existing = sys.modules.get(_MODULE_NAME)
    if existing is not None and hasattr(existing, "emit_batch"):
        _loaded.append(existing)
        return existing
    for path in _CANDIDATES:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(_MODULE_NAME, None)
            continue
        _loaded.append(module)
        return module
    return None


def emit_runner_event(run_dir: Any, state: Mapping[str, Any], event: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Map and append one runner progress event. Never raises (fail-open)."""
    try:
        module = load()
        return module.emit_runner_event(run_dir, dict(state), dict(event)) if module else []
    except Exception:
        return []


def emit_transition(run_dir: Any, entry: Mapping[str, Any], run_id: str = "") -> List[Dict[str, Any]]:
    """Append the lifecycle events of one ``transitions.jsonl`` entry. Never raises (fail-open)."""
    try:
        module = load()
        return module.emit_transition(run_dir, dict(entry), run_id=run_id or None) if module else []
    except Exception:
        return []


def emit_token_usage(run_dir: Any, only: Optional[str] = None) -> List[Dict[str, Any]]:
    """Append the token usage a run recorded in its execution-route files. Never raises (fail-open)."""
    try:
        module = load()
        return module.emit_token_usage(run_dir, only=only) if module else []
    except Exception:
        return []


def read_events(run_dir: Any, since_seq: int = 0) -> List[Dict[str, Any]]:
    """A run's events: the live stream, or the ``derived: true`` reconstruction for older runs."""
    module = load()
    return module.read_events(run_dir, since_seq=since_seq) if module else []
