"""Portable Codex hook bridge for the installed Simplicio CLI.

Codex sends hook context as JSON on stdin.  This module deliberately keeps
the hook observational: malformed input, unsupported events, and detector
errors never block the host agent.  UserPromptSubmit is the one event with a
useful side effect: it emits the existing deterministic task hint on stderr.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from .detect import detect


def _payload(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _event(payload: dict[str, Any]) -> str:
    value = payload.get("hook_event_name") or payload.get("event") or payload.get("type")
    return str(value or "").strip().lower()


def _prompt(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def main() -> int:
    if os.environ.get("SIMPLICIO_HOOK_GUARD"):
        return 0

    payload = _payload(sys.stdin.read())
    if _event(payload) not in {"userpromptsubmit", "user_prompt_submit"}:
        return 0

    prompt = _prompt(payload)
    if not prompt:
        return 0

    try:
        result = detect(prompt)
        if result.is_code_task:
            print(result.hint, file=sys.stderr)
    except Exception:
        # Hooks must never take down or block the host agent.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
