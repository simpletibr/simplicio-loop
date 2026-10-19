"""Adapter for hosts whose surface is `.claude/skills/` plus an `AGENTS.md` marker block.

`adapters/<host>/adapter.py` is one row for one host: it builds an `AgentsMdHost` from the facts that host's docs state
and binds its functions. The behaviour is written once, here. These hosts expose no hook the loop can bind, so every
decision is self-paced (the loop re-reads its scratchpad every turn) and nothing here claims native interception.
Standard library only.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.host-adapter/v1"
ADAPTER_VERSION = "3.50.0"
ENTRY = "AGENTS.md"
SKILLS = ".claude/skills/"
SELF_PACED_STAGES = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop")


class AgentsMdHost:
    """One host of the AGENTS.md surface. `markers` are project directories the host's docs name."""

    def __init__(self, *, host: str, name: str, source: str, markers: Sequence[str] = (),
                 entry_verified: bool = True, note: str = "") -> None:
        self.host = host
        self.name = name
        self.source = source
        self.markers = tuple(markers)
        self.entry_verified = entry_verified
        self.note = note

    def detect(self, root: str | Path | None = None) -> dict[str, Any]:
        workspace = Path(root).resolve() if root else Path.cwd()
        signals = []
        if (workspace / ENTRY).is_file():
            signals.append("file:AGENTS.md")
        signals += [f"dir:{marker}" for marker in self.markers if (workspace / marker).is_dir()]
        return {
            "schema": SCHEMA,
            "host": self.host,
            "detected": bool(signals),
            "signals": signals,
            "workspace": str(workspace),
        }

    def capabilities(self, root: str | Path | None = None) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "host": self.host,
            "name": self.name,
            "version": ADAPTER_VERSION,
            "source": self.source,
            "note": self.note,
            "surfaces": {"entry": {"path": ENTRY, "status": "VERIFIED" if self.entry_verified else "UNVERIFIED"},
                         "skills": {"path": SKILLS}},
            "loop_drive": "self_paced",
            "self_paced": True,
            "native_interception": False,
            "stages": {
                **{stage: {"supported": True, "enforcement": "self_paced"} for stage in SELF_PACED_STAGES},
                "PreToolUse": {"supported": False, "enforcement": "unenforceable_native",
                               "reason": "the installer binds no pre-tool hook for this host"},
            },
        }

    def decide(self, event: Mapping[str, Any], *, timeout: bool = False) -> dict[str, Any]:
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

    def verify_shipped_hooks(self, root: str | Path | None = None) -> dict[str, Any]:
        return {"schema": SCHEMA, "host": self.host, "verified": True, "claimed_native": []}
