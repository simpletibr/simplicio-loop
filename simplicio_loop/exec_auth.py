"""Check authentication state of exec CLIs (claude, codex, grok, gemini) as service user.

Part of #1467: detect login state in preflight without storing/printing secrets.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ExecFamily = Literal["claude", "codex", "grok", "gemini"]


@dataclass(frozen=True)
class AuthCheckResult:
    """Result of checking CLI authentication state."""

    family: ExecFamily
    status: Literal["ok", "login_missing", "cli_missing"]
    reason_code: str = ""

    def __str__(self) -> str:
        if self.status == "ok":
            return f"{self.family}: authenticated"
        return f"{self.status}:{self.family}" + (f" ({self.reason_code})" if self.reason_code else "")


# Credential file locations per CLI, relative to HOME
_CREDENTIAL_PATHS = {
    "claude": [
        ".config/claude/auth.json",
        ".config/claude/credentials.json",
        ".cache/claude/auth.token",
    ],
    "codex": [
        ".config/codex/auth.json",
        ".codex/auth",
        ".cache/codex/token",
    ],
    "grok": [
        ".config/grok/auth.json",
        ".grok/auth.json",
        ".grok/credentials",
        ".cache/grok/token",
    ],
    "gemini": [
        ".config/gemini/auth.json",
        ".gemini/credentials",
        ".cache/gemini/auth.token",
    ],
}

# Status subcommand args per CLI, verified against each CLI's --help:
#   claude: `claude auth status`   (auth login|logout|status)
#   codex:  `codex login status`   (`codex auth` does not exist)
#   grok:   no status subcommand (only login/logout); `grok auth status` would be
#           parsed as an interactive prompt, so it is never spawned -> credential files.
#   gemini: not verifiable (CLI not installed on the reference host) -> credential files.
_STATUS_ARGS = {
    "claude": ["auth", "status"],
    "codex": ["login", "status"],
}


async def check(family: ExecFamily) -> AuthCheckResult:
    """Check if a CLI is installed and authenticated.

    Returns:
        AuthCheckResult with status: ok, cli_missing, or login_missing
    """
    # Check if binary exists
    binary = shutil.which(family)
    if not binary:
        return AuthCheckResult(family, "cli_missing", f"{family}_not_in_path")

    # Try status command first (preferred: no secrets stored/printed)
    try:
        result = await _run_status_check(family, binary)
        if result:
            return AuthCheckResult(family, "ok")
    except Exception:
        pass  # Fall through to credential file check

    # Fall back to checking credential files
    home = Path.home()
    for cred_path in _CREDENTIAL_PATHS.get(family, []):
        cred_file = home / cred_path
        if cred_file.exists():
            return AuthCheckResult(family, "ok")

    return AuthCheckResult(family, "login_missing", "no_credentials_found")


async def check_all(families: list[ExecFamily]) -> list[AuthCheckResult]:
    """Check authentication state for multiple CLIs concurrently.

    Args:
        families: List of CLI families to check (e.g. ["claude", "codex"])

    Returns:
        List of AuthCheckResult in the same order as input families
    """
    tasks = [check(family) for family in families]
    return await asyncio.gather(*tasks)


async def _run_status_check(family: ExecFamily, binary: str) -> bool:
    """Run the CLI's verified status subcommand (resolved `binary` path), check exit code.

    Returns True if the status check exited 0; False if the family has no verified
    status subcommand, or on failure/timeout. Never captures stdout/stderr (avoids secrets).
    """
    args = _STATUS_ARGS.get(family)
    if not args:
        return False

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        returncode = await asyncio.wait_for(proc.wait(), timeout=5.0)
        return returncode == 0
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        if proc is not None and proc.returncode is None:
            proc.kill()
        return False


def check_sync(family: ExecFamily) -> AuthCheckResult:
    """Synchronous wrapper: runs check() using asyncio.run().

    Call this from sync context when an async loop is not running.
    """
    return asyncio.run(check(family))
