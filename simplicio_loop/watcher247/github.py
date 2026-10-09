"""GitHub (gh CLI) operations of the 24/7 watcher."""
from __future__ import annotations

import json
from typing import Any

from . import config, proc, state


async def gh_json(args: list[str], timeout: int = 60) -> Any:
    result = await proc.run(["gh", *args], timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "gh failed").strip()[:500])
    return json.loads(result.stdout or "null")


async def repos() -> list[dict]:
    rows = await gh_json([
        "repo", "list", config.ORG, "--limit", "200",
        "--json", "name,isArchived,defaultBranchRef",
    ], timeout=90)
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
        return await gh_json([
            "issue", "list", "--repo", f"{config.ORG}/{repo}", "--state", "open",
            "--limit", "50", "--json", "number,title,body,createdAt,labels",
        ])
    except RuntimeError as exc:
        if "disabled issues" in str(exc):
            await state.mark_issues_disabled(repo)
            return []
        raise


def skipped(issue: dict) -> bool:
    for label in issue.get("labels") or []:
        name = (label.get("name") if isinstance(label, dict) else str(label)).lower()
        if name in {"simplicio-loop:skip", "wontfix"}:
            return True
    return False


async def comment(repo: str, number: int, message: str) -> None:
    """Comment on the issue; a failure is logged, never raised."""
    result = await proc.run([
        "gh", "issue", "comment", str(number), "--repo", f"{config.ORG}/{repo}", "--body", message,
    ], timeout=60)
    if result.returncode != 0:
        state.log(f"comment failed {repo}#{number}: {(result.stderr or '')[:200]}")
