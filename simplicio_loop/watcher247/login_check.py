"""`simplicio-loop watch247 login-check` (#1467): is each enabled exec CLI logged in as the service user?

Prints one line per CLI: ``ok``, or the exact command that fixes it. Exit 0 when all are ok, 1 otherwise. The check
is exec_auth.check_all (status subcommand or credential file); no token is read or printed.
"""
from __future__ import annotations

import asyncio

from .. import exec_auth, executor_select

SERVICE_USER = "simplicio-loop"  # User= of packaging/systemd/simplicio-loop-247.service


def login_command(family: str) -> str:
    return f"sudo -u {SERVICE_USER} -H {family} login"


def line(result: exec_auth.AuthCheckResult) -> str:
    if result.status == "ok":
        return f"{result.family}: ok"
    fix = login_command(result.family)
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
