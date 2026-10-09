"""Paths and constants for the 24/7 watcher (port of simplicio-loop-247.py).

Paths are module attributes recomputed by set_state_dir(); every other module
reads them as config.X at call time so tests and --state-dir can relocate them.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

ORG = "simpletibr"
INTERVAL_S = 120
TURBO_TIMEOUT_S = 900
MAX_ATTEMPTS = 2
RETRY_AFTER = timedelta(hours=6)
BODY_CAP = 6000

# Login (shared with the Simplicio CLI)
LOGIN = Path("/root/.simplicio/login.json")
VALIDATE_URL = "https://simpleti.com.br/api/simplicio/validate.php"
TOKEN_URL = "https://simpleti.com.br/api/simplicio/token"
MCP_CLIENT_ID = "simplicio-cli"
PAID_STATUS = {"active", "trialing"}
PAID_SOURCES = {"subscription", "stripe", "admin"}


def concurrency() -> int:
    """Max issues processed at once (SIMPLICIO_247_CONCURRENCY, default 1)."""
    try:
        return max(1, int(os.environ.get("SIMPLICIO_247_CONCURRENCY", "1")))
    except ValueError:
        return 1


def set_state_dir(path: str | Path) -> None:
    """Point every state path at `path`."""
    global STATE_DIR, ROOT, WORK, LOGS, BASELINE, CLAIMS, STATUS, STOP, DISABLED
    STATE_DIR = ROOT = Path(path)
    WORK = ROOT / "work"
    LOGS = ROOT / "logs"
    BASELINE = ROOT / "baseline.json"
    CLAIMS = ROOT / "claims.json"
    STATUS = ROOT / "status.json"
    STOP = ROOT / "STOP"
    DISABLED = ROOT / "issues-disabled.json"


set_state_dir(os.environ.get("SIMPLICIO_247_STATE_DIR", "/var/lib/simplicio-loop-247"))
