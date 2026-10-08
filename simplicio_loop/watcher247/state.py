"""State management for the 24/7 watcher."""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from . import config

def now() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

async def load(path: Path, default: Any = None) -> Any:
    try:
        loop = asyncio.get_event_loop()
        content = await loop.run_in_executor(None, path.read_text)
        return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

async def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    content = json.dumps(data, ensure_ascii=False, indent=2) + chr(10)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, tmp.write_text, content)
    tmp.replace(path)

def key_of(repo: str, number: int) -> str:
    return f'{repo}#{number}'

def due(ident: str, claims: dict) -> bool:
    claim = claims.get(ident)
    if not claim:
        return True
    status = claim.get('status')
    if status in {'done', 'done_no_diff', 'dead', 'running', 'preexisting'}:
        return False
    if status == 'retry':
        raw = claim.get('next_try_at') or ''
        try:
            when = datetime.strptime(raw, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        return now() >= when
    return False
