#!/usr/bin/env python3
"""Run the canonical Claude adapter for UserPromptSubmit."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "adapters" / "claude" / "adapter.py").is_file():
            return candidate
    return current.parents[1]


ROOT = _repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.claude.adapter import decide  # noqa: E402


def _dashboard_prompt_event(event: dict, decision: dict) -> None:
    """#1398: an operator prompt starts a new turn -> `iteration_started` (source=operator).
    The prompt text is never recorded, only its size. Fail-open."""
    try:
        import _dashboard_emit

        prompt = str(event.get("prompt") or event.get("user_prompt") or "")
        blocked = decision.get("decision") == "block"
        _dashboard_emit.emit(
            "iteration_started", source="operator", severity="warning" if blocked else "info",
            payload={"trigger": "user_prompt", "decision": str(decision.get("decision") or ""),
                     "reason": str(decision.get("reason") or ""), "prompt_chars": len(prompt)},
        )
    except Exception:
        pass


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}
    event.setdefault("hook_event_name", "UserPromptSubmit")
    decision = decide(event)
    _dashboard_prompt_event(event, decision)
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if decision.get("decision") != "block" else 2


if __name__ == "__main__":
    raise SystemExit(main())
