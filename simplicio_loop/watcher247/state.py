"""State files, clock, log and claim scheduling for the 24/7 watcher."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

_ISO = "%Y-%m-%dT%H:%M:%SZ"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_ISO)


def log(msg: str) -> None:
    print(f"{iso(now())} {msg}", flush=True)


def _load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


async def load(path: Path, default: Any = None) -> Any:
    return await asyncio.to_thread(_load, path, default)


async def save(path: Path, data: Any) -> None:
    await asyncio.to_thread(_save, path, data)


async def write_status(**extra: Any) -> None:
    await save(config.STATUS, {"updated_at": iso(now()), "stopped": config.STOP.exists(), **extra})


async def issues_disabled() -> set[str]:
    return set(await load(config.DISABLED, []))


async def mark_issues_disabled(name: str) -> None:
    names = await issues_disabled()
    names.add(name)
    await save(config.DISABLED, sorted(names))


def key_of(repo: str, number: int) -> str:
    return f"{repo}#{number}"
