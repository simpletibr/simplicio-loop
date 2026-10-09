"""Startup check of the service env file (#1434): it holds the API keys, so only its owner may read it."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT = "/etc/simplicio-loop-247.env"  # EnvironmentFile of packaging/systemd/simplicio-loop-247.service


def env_file() -> Path:
    return Path(os.environ.get("SIMPLICIO_247_ENV_FILE") or DEFAULT)


def refusal(path: Path | None = None) -> str | None:
    """reason_code when the env file is group- or world-accessible, else None (a missing file is fine)."""
    try:
        mode = (path or env_file()).stat().st_mode
    except FileNotFoundError:
        return None
    return "env_file_permissions" if mode & 0o077 else None
