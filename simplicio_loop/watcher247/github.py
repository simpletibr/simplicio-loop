"""GitHub operations for the 24/7 watcher."""
from __future__ import annotations
import asyncio
import json
from typing import Any
from . import config

async def gh_json(args: list[str], timeout: int = 60) -> Any:
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            msg = (stderr.decode() or stdout.decode() or "gh failed").strip()[:500]
            raise RuntimeError(msg)
        return json.loads(stdout.decode() or "null")
    except asyncio.TimeoutError as exc:
        raise RuntimeError(f"gh timeout after {timeout}s") from exc

async def repos() -> list[dict]:
    rows = await gh_json(["repo", "list", config.ORG, "--limit", "200", "--json", "name,isArchived,defaultBranchRef"], timeout=90)
    out = []
    for row in rows:
        name = row.get("name") or ""
        if row.get("isArchived") or not name.startswith("simplicio"):
            continue
        branch = ((row.get("defaultBranchRef") or {}).get("name")) or "main"
        out.append({"name": name, "branch": branch})
    return out

async def open_issues(repo: str) -> list[dict]:
    try:
        return await gh_json(["issue", "list", "--repo", f"{config.ORG}/{repo}", "--state", "open", "--limit", "50", "--json", "number,title,body,createdAt,labels"])
    except RuntimeError as exc:
        if "disabled issues" in str(exc):
            return []
        raise

def skipped(issue: dict) -> bool:
    for label in issue.get("labels") or []:
        name = (label.get("name") if isinstance(label, dict) else str(label)).lower()
        if name in {"simplicio-loop:skip", "wontfix"}:
            return True
    return False

async def comment(repo: str, number: int, message: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "gh", "issue", "comment", str(number), "--repo", f"{config.ORG}/{repo}", "--body", message,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"comment failed {repo}#{number}: {stderr.decode()[:200]}")
