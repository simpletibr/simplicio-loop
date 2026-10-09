"""Check authentication state of exec CLIs (claude, codex, grok, gemini, agy, opencode) as service user.

Part of #1467: detect login state in preflight without storing/printing secrets.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ExecFamily = Literal["claude", "codex", "grok", "gemini", "agy", "opencode"]


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
    # agy: `agy --help` has no auth/status subcommand; the OAuth token file below is what a sign-in leaves (#1513).
    "agy": [
        ".gemini/antigravity-cli/antigravity-oauth-token",
    ],
    # opencode: deliberately no file here; `opencode auth list` is the check (a present-but-empty auth.json is `0`).
}

# Status subcommand args per CLI, verified against each CLI's --help:
#   claude: `claude auth status`   (auth login|logout|status)
#   codex:  `codex login status`   (`codex auth` does not exist)
#   grok:   no status subcommand (only login/logout); `grok auth status` would be
#           parsed as an interactive prompt, so it is never spawned -> credential files.
#   gemini: not verifiable (CLI not installed on the reference host) -> credential files.
#   agy:    `agy --help` has no status subcommand and bare `agy` starts the interactive CLI -> credential file.
#   opencode: `opencode auth list` always exits 0; its last line is `N credentials`, so the count decides (#1513).
_STATUS_ARGS = {
    "claude": ["auth", "status"],
    "codex": ["login", "status"],
    "opencode": ["auth", "list"],
}
_COUNT_FAMILIES = frozenset({"opencode"})  # exit code alone is not the answer; stdout is reduced to a count
_CREDENTIAL_COUNT = re.compile(r"^\W*(\d+) credentials?\s*$", re.MULTILINE)


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
        if _credential_present(home / cred_path):
            return AuthCheckResult(family, "ok")

    return AuthCheckResult(family, "login_missing", "no_credentials_found")


def _credential_present(path: Path) -> bool:
    """stat only (regular file, non-empty); the content of a credential file is never opened."""
    try:
        info = path.stat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size > 0


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

    if family in _COUNT_FAMILIES:
        return await _run_count_check(binary, args)

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


async def _run_count_check(binary: str, args: list[str]) -> bool:
    """Exit 0 and a `N credentials` line with N > 0. stdout is reduced to that integer and dropped (it lists
    provider names); stderr is never captured."""
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        if proc is not None and proc.returncode is None:
            proc.kill()
        return False
    if proc.returncode != 0:
        return False
    counts = _CREDENTIAL_COUNT.findall(out.decode("utf-8", "replace"))
    return bool(counts) and int(counts[-1]) > 0


def check_sync(family: ExecFamily) -> AuthCheckResult:
    """Synchronous wrapper: runs check() using asyncio.run().

    Call this from sync context when an async loop is not running.
    """
    return asyncio.run(check(family))
