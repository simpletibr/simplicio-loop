"""Exporter configuration: ``loop.toml`` keys, environment overrides and the 0600 credentials file."""

from __future__ import annotations

import json
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "https://cloud.langfuse.com"
DEFAULT_BATCH_SECONDS = 60
MAX_BATCH_SECONDS = 3600
CREDENTIALS_FILE = "credentials.json"


class CredentialFileError(ValueError):
    """The credentials file exists but is readable by group or others."""


@dataclass(frozen=True)
class LangfuseConfig:
    enabled: bool = False
    host: str = DEFAULT_HOST
    capture_content: bool = False
    batch_seconds: int = DEFAULT_BATCH_SECONDS


@dataclass(frozen=True)
class Credentials:
    public_key: str
    secret_key: str


def load_config(table: Mapping[str, object], env: Mapping[str, str]) -> LangfuseConfig:
    """Build the config from the parsed loop.toml table. Bad values raise: no silent fallback."""
    enabled = table.get("langfuse_enabled", False)
    if not isinstance(enabled, bool):
        raise TypeError("langfuse_enabled must be a boolean")
    capture = table.get("langfuse_capture_content", False)
    if not isinstance(capture, bool):
        raise TypeError("langfuse_capture_content must be a boolean")
    batch = table.get("langfuse_batch_seconds", DEFAULT_BATCH_SECONDS)
    if (
        isinstance(batch, bool)
        or not isinstance(batch, int)
        or not 1 <= batch <= MAX_BATCH_SECONDS
    ):
        raise ValueError(
            f"langfuse_batch_seconds must be an integer in 1..{MAX_BATCH_SECONDS}"
        )
    host = env.get("LANGFUSE_HOST") or table.get("langfuse_host") or DEFAULT_HOST
    if not isinstance(host, str) or not host.startswith(("https://", "http://")):
        raise TypeError("langfuse_host must be an http(s) URL")
    return LangfuseConfig(
        enabled=enabled,
        host=host.rstrip("/"),
        capture_content=capture,
        batch_seconds=batch,
    )


def resolve_credentials(
    env: Mapping[str, str], langfuse_dir: Path
) -> Credentials | None:
    """Keys come from the environment first, then from ``credentials.json`` (mode 0600 only)."""
    public_key = env.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = env.get("LANGFUSE_SECRET_KEY", "")
    if public_key and secret_key:
        return Credentials(public_key=public_key, secret_key=secret_key)
    path = Path(langfuse_dir) / CREDENTIALS_FILE
    if not path.is_file():
        return None
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise CredentialFileError(f"{path} must be mode 0600 (no group/other access)")
    data = json.loads(path.read_text(encoding="utf-8"))
    pk, sk = data.get("public_key"), data.get("secret_key")
    if isinstance(pk, str) and isinstance(sk, str) and pk and sk:
        return Credentials(public_key=pk, secret_key=sk)
    return None
