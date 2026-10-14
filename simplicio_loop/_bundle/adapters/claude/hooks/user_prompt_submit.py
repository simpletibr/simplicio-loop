#!/usr/bin/env python3
"""Claude UserPromptSubmit hook — materialize RouteDecision + skill subset."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT.parent.parent))

from adapters.claude.adapter import decide  # noqa: E402


def main() -> int:
    raw = sys.stdin.read() or "{}"
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        event = {}
    event.setdefault("hook_event_name", "UserPromptSubmit")
    decision = decide(event)
    print(json.dumps(decision, ensure_ascii=False))
    return 0 if decision.get("decision") != "block" else 2


if __name__ == "__main__":
    raise SystemExit(main())
