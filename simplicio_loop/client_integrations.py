"""Client-requested integrations — never auto-wired into the core loop path.

Integrations (Orca card sync, vendor MCP hosts, third-party boards, …) run only
when the **client explicitly opts in**. Default is an empty set: a plain
Loop/Mapper/Fast/Dev-CLI armada has zero host side-channels.

Enable via either:

* env ``SIMPLICIO_LOOP_CLIENT_INTEGRATIONS`` — comma-separated names
  (e.g. ``orca`` or ``orca,linear``)
* file ``.simplicio-loop/client-integrations.json`` in the repo (or path in
  ``SIMPLICIO_LOOP_CLIENT_INTEGRATIONS_FILE``)::

      {"schema": "simplicio.client-integrations/v1", "integrations": ["orca"]}

Legacy env ``SIMPLICIO_LOOP_ORCA_LIFECYCLE_SYNC=1`` still enables the **orca**
integration alone (compat). New clients should use the list above.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, FrozenSet, Iterable, Mapping

SCHEMA = "simplicio.client-integrations/v1"
KNOWN = frozenset(
    {
        "orca",
        "linear",
        "jira",
        "azure-devops",
        "slack",
        "discord",
    }
)


def _split_csv(raw: str) -> list[str]:
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def _from_env() -> set[str]:
    out: set[str] = set()
    raw = str(os.environ.get("SIMPLICIO_LOOP_CLIENT_INTEGRATIONS") or "").strip()
    if raw:
        out.update(_split_csv(raw))
    # Legacy single-integration opt-in for Orca card projection.
    legacy = str(os.environ.get("SIMPLICIO_LOOP_ORCA_LIFECYCLE_SYNC") or "").strip().lower()
    if legacy in {"1", "true", "yes", "on", "enabled"}:
        out.add("orca")
    return out


def _from_file(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, Mapping):
        return set()
    items = data.get("integrations") or data.get("enabled") or []
    if not isinstance(items, Iterable) or isinstance(items, (str, bytes)):
        return set()
    return {str(item).strip().lower() for item in items if str(item).strip()}


def resolve_integrations(*, repo_root: str | Path | None = None) -> FrozenSet[str]:
    """Return the frozen set of client-requested integration names (may be empty)."""
    found = _from_env()
    file_raw = str(os.environ.get("SIMPLICIO_LOOP_CLIENT_INTEGRATIONS_FILE") or "").strip()
    if file_raw:
        found |= _from_file(Path(file_raw).expanduser())
    elif repo_root is not None:
        found |= _from_file(Path(repo_root) / ".simplicio-loop" / "client-integrations.json")
    else:
        # Best-effort: cwd project file (hosts often cwd at repo root).
        found |= _from_file(Path.cwd() / ".simplicio-loop" / "client-integrations.json")
    # Unknown names are kept (forward-compatible) but never invent defaults.
    return frozenset(found)


def integration_enabled(name: str, *, repo_root: str | Path | None = None) -> bool:
    """True only when the client explicitly requested ``name``."""
    key = str(name or "").strip().lower()
    if not key:
        return False
    return key in resolve_integrations(repo_root=repo_root)


def describe(*, repo_root: str | Path | None = None) -> dict[str, Any]:
    enabled = sorted(resolve_integrations(repo_root=repo_root))
    return {
        "schema": SCHEMA,
        "enabled": enabled,
        "known": sorted(KNOWN),
        "default": [],
        "policy": "opt-in-only-per-client-request",
        "orca_lifecycle_sync": integration_enabled("orca", repo_root=repo_root),
    }
