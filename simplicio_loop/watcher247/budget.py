"""Daily cap: per-UTC-day counters of issues attempted, model calls and PRs opened.

One JSON file in the state dir, rewritten atomically (temp file + os.replace). The
day is part of the file, so a stored counter from another UTC day reads as zero:
the cap resets at UTC midnight without a timer. Ceilings come from the env.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from . import config, state

COUNTERS = ("issues", "model_calls", "prs")
_LOCK = threading.Lock()  # one writer per process; a thread lock is loop-agnostic, unlike asyncio.Lock


def _ceiling(var: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(var, default)))
    except ValueError:
        return default


def max_issues_per_day() -> int:
    return _ceiling("SIMPLICIO_247_MAX_ISSUES_PER_DAY", 20)


def max_prs_per_day() -> int:
    return _ceiling("SIMPLICIO_247_MAX_PRS_PER_DAY", 10)


def _today() -> str:
    return state.iso(state.now())[:10]


def _fresh() -> dict[str, Any]:
    return {"day": _today(), **{name: 0 for name in COUNTERS}}


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _fresh()
    stored = json.loads(path.read_text())
    if stored.get("day") != _today():
        return _fresh()
    return {"day": stored["day"], **{name: int(stored.get(name, 0)) for name in COUNTERS}}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _bump(path: Path, counter: str, n: int) -> dict[str, Any]:
    with _LOCK:  # read-modify-write under one lock, so concurrent records are not lost
        data = _read(path)
        data[counter] += n
        _write(path, data)
    return data


async def snapshot() -> dict[str, Any]:
    data = await asyncio.to_thread(_read, config.BUDGET)
    return {**data, "max_issues": max_issues_per_day(), "max_prs": max_prs_per_day()}


async def record(counter: str, n: int = 1) -> dict[str, Any]:
    if counter not in COUNTERS:
        raise ValueError(f"unknown budget counter: {counter}")
    return await asyncio.to_thread(_bump, config.BUDGET, counter, n)


async def reached() -> str | None:
    """'issues' or 'prs' when that ceiling is hit today, else None."""
    data = await snapshot()
    if data["issues"] >= data["max_issues"]:
        return "issues"
    if data["prs"] >= data["max_prs"]:
        return "prs"
    return None


async def issues_left() -> int:
    data = await snapshot()
    return max(0, data["max_issues"] - data["issues"])


async def slots_left() -> int:
    """Workers the daily cap still allows: each one takes an issue and may open a PR, so the smaller room counts."""
    data = await snapshot()
    return max(0, min(data["max_issues"] - data["issues"], data["max_prs"] - data["prs"]))
