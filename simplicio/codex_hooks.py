"""Portable Codex hook bridge for the installed Simplicio CLI.

Codex sends hook context as JSON on stdin.  Non-routing events remain
observational.  The installed UserPromptSubmit Runtime route is fail-closed
so a developer task cannot continue outside Runtime when routing or evidence
fails.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from .codex_wrapper import HOOK_MARKER, route_through_runtime
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


def _codex_argv(payload: dict[str, Any]) -> list[str]:
    value = payload.get("codex_argv", [])
    argv = list(value) if isinstance(value, list) and all(isinstance(item, str) for item in value) else []
    for key, flag in (("sandbox_mode", "--sandbox"), ("approval_policy", "--ask-for-approval")):
        policy = payload.get(key)
        if isinstance(policy, str) and policy:
            argv.extend((flag, policy))
    permission_mode = payload.get("permission_mode", payload.get("permissionMode"))
    if isinstance(permission_mode, str) and permission_mode:
        argv.extend(("--permission-mode", permission_mode))
    if (
        payload.get("dangerously_bypass_approvals_and_sandbox") is True
        or permission_mode == "bypassPermissions"
    ):
        argv.append("--dangerously-bypass-approvals-and-sandbox")
    return argv


def _runtime_response(payload: dict[str, Any], prompt: str) -> dict[str, Any]:
    argv = _codex_argv(payload)
    cwd = payload.get("cwd") or payload.get("working_directory")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    try:
        result = route_through_runtime(prompt, argv, cwd=cwd)
    except Exception as exc:
        return {
            "decision": "block",
            "reason": f"{HOOK_MARKER}: Runtime unavailable; Codex task was not started: {exc}",
        }
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Runtime rejected the task").strip()
        return {
            "decision": "block",
            "reason": f"{HOOK_MARKER}: Runtime rejected the task: {detail}",
        }
    from .codex_wrapper import _receipt_from_output

    if _receipt_from_output(result.stdout or "") is None:
        return {
            "decision": "block",
            "reason": (
                f"{HOOK_MARKER}: Runtime returned no valid evidence receipt; Codex task was not started"
            ),
        }
    return {
        "decision": "block",
        "reason": f"{HOOK_MARKER}: Runtime completed the developer task; Codex was not started",
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": (result.stdout or "").strip(),
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="simplicio.codex_hooks")
    parser.add_argument("--route", choices=("hint", "runtime"), default="hint")
    parser.add_argument("--marker", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args([] if argv is None else argv)

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
        if args.route == "runtime" and (result.is_code_task or result.score >= 2):
            sys.stdout.write(json.dumps(_runtime_response(payload, prompt), sort_keys=True) + "\n")
            return 0
        if result.is_code_task:
            sys.stderr.write(f"{result.hint}\n")
    except Exception:
        if args.route == "runtime":
            sys.stdout.write(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": f"{HOOK_MARKER}: task classification failed; Codex task was not started",
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            return 0
        # The legacy hint route remains observational.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
