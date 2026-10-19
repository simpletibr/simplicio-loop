"""Paths and constants for the 24/7 watcher (port of simplicio-loop-247.py).

Paths are module attributes recomputed by set_state_dir(); every other module
reads them as config.X at call time so tests and --state-dir can relocate them.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

from .. import auth

OWNERS_ENV = "SIMPLICIO_247_OWNERS"
OWNERS_INVALID = "owners_env_invalid"  # the reason_code of a start refused for SIMPLICIO_247_OWNERS
OWNER_LOGIN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?")  # a GitHub user or org login: up to 39, single hyphens, lower case
INTERVAL_S = 120
TURBO_TIMEOUT_S = 900
MAX_ATTEMPTS = 2
PLAN_TIMEOUT_S = 300  # one exec-CLI planner call (host mode)
MAX_STEPS = 4  # planner+apply steps in one process() run; the escalation ceilings may stop it sooner
RETRY_AFTER = timedelta(hours=6)
BODY_CAP = 6000
OWNER = "simplicio-loop-247"  # the claim owner on GitHub and in the lease store
LEASE_TTL_S = 180  # a lease expires this long after its last heartbeat
HEARTBEAT_S = 60


def default_login() -> Path:
    """The login file of the service user: where `simplicio_loop.auth` keeps it (shared with the Runtime)."""
    return auth.login_path()


# Login (shared with the Simplicio CLI)
LOGIN = default_login()
VALIDATE_URL = "https://simpleti.com.br/api/simplicio/validate.php"
TOKEN_URL = "https://simpleti.com.br/api/simplicio/token"
MCP_CLIENT_ID = auth.MCP_CLIENT_ID
PAID_STATUS = {"active", "trialing"}
PAID_SOURCES = {"subscription", "stripe", "admin"}


# Max issues processed at once. Unset = automatic (squad_capacity: demand against the measured machine); a number pins it.
CONCURRENCY_ENV = "SIMPLICIO_247_CONCURRENCY"


def owners(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """The GitHub owners (users or orgs) the watcher serves, from SIMPLICIO_247_OWNERS (comma separated).

    There is no default. Unset or empty raises ValueError naming the variable, and so does a value that is not a login, so the
    watcher refuses to start rather than watch an owner nobody named. Logins are case-insensitive on GitHub, so they are kept in
    lower case: one owner has one spelling in every claim key and directory. Each owner is listed once, in the order given.
    """
    raw = (os.environ if environ is None else environ).get(OWNERS_ENV, "")
    names = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if not names:
        raise ValueError(f"{OWNERS_ENV} is not set: name the GitHub owners (orgs or users) to watch, comma separated, e.g. {OWNERS_ENV}=acme")
    if invalid := [name for name in names if not OWNER_LOGIN.fullmatch(name)]:
        raise ValueError(f"{OWNERS_ENV} has a value that is not a GitHub login: {invalid[0]!r} (letters, digits and single hyphens, up to 39)")
    return tuple(dict.fromkeys(names))


def set_state_dir(path: str | Path) -> None:
    """Point every state path at `path`."""
    global STATE_DIR, ROOT, WORK, LOGS, BASELINE, CLAIMS, STATUS, STOP, DISABLED, BUDGET, FIXES
    STATE_DIR = ROOT = Path(path)
    WORK = ROOT / "work"
    LOGS = ROOT / "logs"
    BASELINE = ROOT / "baseline.json"
    CLAIMS = ROOT / "claims.json"
    STATUS = ROOT / "status.json"
    STOP = ROOT / "STOP"
    DISABLED = ROOT / "issues-disabled.json"
    BUDGET = ROOT / "budget.json"
    FIXES = ROOT / "fixes.json"  # queued PR-review fixes, see tick._enqueue_fixes


set_state_dir(os.environ.get("SIMPLICIO_247_STATE_DIR", "/var/lib/simplicio-loop-247"))
