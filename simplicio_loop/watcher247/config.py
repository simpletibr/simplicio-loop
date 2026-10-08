"""Configuration and constants for the 24/7 watcher."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

# State directory (configurable for testing)
STATE_DIR = Path(os.environ.get("SIMPLICIO_247_STATE_DIR", "/var/lib/simplicio-loop-247"))

# State files
BASELINE = STATE_DIR / "baseline.json"
CLAIMS = STATE_DIR / "claims.json"
STATUS = STATE_DIR / "status.json"
STOP = STATE_DIR / "STOP"

# Work directory
WORK = STATE_DIR / "work"
LOGS = STATE_DIR / "logs"

# GitHub
ORG = "simpletibr"

# Timing
INTERVAL_S = 120
TURBO_TIMEOUT_S = 900
MAX_ATTEMPTS = 2
RETRY_AFTER = timedelta(hours=6)

# Content limits
BODY_CAP = 6000

# Login (shared with CLI)
LOGIN = Path("/root/.simplicio/login.json")

# MCP subscription URLs
VALIDATE_URL = "https://simpleti.com.br/api/simplicio/validate.php"
TOKEN_URL = "https://simpleti.com.br/api/simplicio/token"
MCP_CLIENT_ID = "simplicio-cli"

# Subscription validation
PAID_STATUS = {"active", "trialing"}
PAID_SOURCES = {"subscription", "stripe", "admin"}

# Concurrency
CONCURRENCY = int(os.environ.get("SIMPLICIO_247_CONCURRENCY", "1"))
