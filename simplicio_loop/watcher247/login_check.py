"""`simplicio-loop watch247 login-check` (#1467): is each enabled exec CLI logged in as the service user?

Prints one line per CLI: ``ok``, or the exact command that fixes it. Exit 0 when all are ok, 1 otherwise. The check
is exec_auth.check_all (status subcommand or credential file); no token is read or printed.
"""
from __future__ import annotations

import asyncio

from .. import exec_auth, executor_select

SERVICE_USER = "simplicio-loop"  # User= of packaging/systemd/simplicio-loop-247.service


# Login command per family. VERIFIED against each CLI's --help on the reference host:
#   claude   `claude auth --help`     -> auth login|logout|status (bare `claude login` is not a subcommand)
#   codex    `codex login --help`     -> bare `codex login` signs in; `status` is the only subcommand
#   grok     `grok login --help`      -> `grok login` (--oauth / --device-auth select the flow)
#   opencode `opencode auth --help`   -> auth login|logout|list
#   agy      `agy --help`             -> no login subcommand; sign-in happens when the interactive CLI starts
# Status (#1513): see exec_auth._STATUS_ARGS / _CREDENTIAL_PATHS (opencode: `auth list` count; agy: token file stat).
_LOGIN = {
    "claude": "claude auth login",
    "codex": "codex login",
    "grok": "grok login",
    "opencode": "opencode auth login",
    "agy": "agy",
    # DOC-BASED: gemini is not installed on the reference host. Per the Gemini CLI docs, running `gemini` starts the
    # interactive sign-in. Replace by the verified command once the CLI is installed and `gemini --help` is checked.
    "gemini": "gemini",
}
DOC_BASED_FAMILIES = frozenset({"gemini"})


def login_command(family: str) -> str:
    return f"sudo -u {SERVICE_USER} -H {_LOGIN[family]}"


def line(result: exec_auth.AuthCheckResult) -> str:
    if result.status == "ok":
        return f"{result.family}: ok"
    fix = login_command(result.family)
    if result.family in DOC_BASED_FAMILIES:
        fix += "  (doc-based, not verified)"
    if result.status == "cli_missing":
        return f"{result.family}: cli_missing: install it on the service host, then run: {fix}"
    return f"{result.family}: {result.status}: {fix}"


def main() -> int:
    try:
        families = executor_select.exec_families()
    except executor_select.ExecutorSelectError as exc:
        print(f"executor_invalid: {exc}")
        return 1
    results = asyncio.run(exec_auth.check_all(families))
    for result in results:
        print(line(result))
    return 0 if all(r.status == "ok" for r in results) else 1
