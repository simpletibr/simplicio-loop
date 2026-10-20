"""One install host's surface: where its files land, whether they are there, and how its loop is driven.

`adapters/<host>/adapter.py` binds one `HostSurface`, which is what makes a catalog entry "wired" (see
`tests/test_adapter_scope_honesty.py`). The surface is not declared twice: it is `planner.HOST_LAYOUT[runtime]`. A host
row passes only what its docs state beyond that layout (name, source, marker directories, whether the entry file is
verified). Every host bound here is self-paced: it exposes no hook the loop can bind, so each lifecycle decision is the
loop re-reading its scratchpad every turn, and nothing here claims native interception.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .planner import HOST_LAYOUT, runtime_for

SCHEMA = "simplicio.host-adapter/v1"
ADAPTER_VERSION = "3.51.0"
SELF_PACED_STAGES = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop")


class HostSurface:
    def __init__(self, host: str, *, loop_drive: str = "self_paced", name: str | None = None, source: str = "",
                 note: str = "", entry_verified: bool = True, markers: Sequence[str] = ()) -> None:
        self.host = host
        self.runtime = runtime_for(host)
        self.layout = HOST_LAYOUT[self.runtime]
        self.loop_drive = loop_drive
        self.name = name or host
        self.source = source
        self.note = note
        self.entry_verified = entry_verified
        self.markers = tuple(markers)

    def _expected(self, dest: str, kind: str) -> str:
        """The file that proves a layout row landed: the skill inside a skills root, the file itself otherwise."""
        return f"{dest}/simplicio-loop/SKILL.md" if kind == "skills" else dest

    def detect(self, root: str | Path | None = None) -> dict[str, Any]:
        """The layout rows and marker directories that exist in `root`; any of them detects the host."""
        base = Path(root).resolve() if root else Path.cwd()
        signals = sorted(dest for dest in self.layout if (base / dest).exists())
        signals += [marker for marker in self.markers if (base / marker).is_dir()]
        return {"schema": SCHEMA, "host": self.host, "detected": bool(signals), "signals": signals,
                "workspace": str(base)}

    def verify(self, root: str | Path) -> dict[str, Any]:
        base = Path(root).resolve()
        missing = sorted(self._expected(dest, kind) for dest, kind in self.layout.items()
                         if not (base / self._expected(dest, kind)).exists())
        return {"schema": SCHEMA, "host": self.host, "verified": not missing, "missing": missing}

    def capabilities(self) -> dict[str, Any]:
        entry = next((dest for dest, kind in self.layout.items() if kind == "entry"), None)
        return {
            "schema": SCHEMA,
            "host": self.host,
            "runtime": self.runtime,
            "name": self.name,
            "version": ADAPTER_VERSION,
            "source": self.source,
            "note": self.note,
            "loop_drive": self.loop_drive,
            "self_paced": self.loop_drive == "self_paced",
            "native_interception": False,
            "stores_credentials": False,
            "live_status": "UNVERIFIED",
            "surfaces": {
                "entry": None if entry is None else {
                    "path": entry, "status": "VERIFIED" if self.entry_verified else "UNVERIFIED"},
                "skills": {"path": ".claude/skills/"},
            },
            "surface": sorted(self._expected(dest, kind) for dest, kind in self.layout.items()),
            "stages": {
                **{stage: {"supported": True, "enforcement": "self_paced"} for stage in SELF_PACED_STAGES},
                "PreToolUse": {"supported": False, "enforcement": "unenforceable_native",
                               "reason": "the installer binds no pre-tool hook for this host"},
            },
        }

    def decide(self, event: Mapping[str, Any], *, timeout: bool = False) -> dict[str, Any]:
        """The lifecycle decision for one event. Self-paced hosts continue on the stages they fire; a PreToolUse is
        refused because no native hook exists to enforce it; a timeout never authorizes anything."""
        stage = str(event.get("hook_event_name") or event.get("stage") or "").strip()
        receipt: dict[str, Any] = {
            "schema": "simplicio.host-hook-decision/v1",
            "host": self.host,
            "stage": stage,
            "correlation_id": str(event.get("correlation_id") or uuid.uuid4()),
            "decided_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "native_interception": False,
        }
        if timeout:
            receipt.update({"decision": "block", "reason": "hook_timeout_does_not_authorize"})
        elif stage in SELF_PACED_STAGES:
            receipt.update({"decision": "continue", "reason": "self_paced_" + stage.lower(),
                            "enforcement": "self_paced"})
        elif stage == "PreToolUse":
            receipt.update({"decision": "block", "reason": "native_pretooluse_absent",
                            "enforcement": "unenforceable_native"})
        else:
            receipt.update({"decision": "block", "reason": "unknown_lifecycle_stage"})
        return receipt

    def verify_shipped_hooks(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "host": self.host, "verified": True, "claimed_native": []}
