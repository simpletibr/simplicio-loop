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
        rows = await gh_json([
            "api", "-X", "GET", f"repos/{config.ORG}/{repo}/issues",
            "-f", "state=open", "-F", "per_page=50",
        ])
    except RuntimeError as exc:
        exc_str = str(exc).lower()
        if "disabled issues" in exc_str or "issues are disabled" in exc_str:
            await state.mark_issues_disabled(repo)
            return []
        raise
    # Filter out pull requests (REST API /issues returns both issues and PRs)
    # Also map REST API field names to the old format for backward compatibility
    out = []
    for row in rows:
        if "pull_request" in row:
            continue
        # Map REST API fields to old format for backward compatibility
        row["createdAt"] = row.get("created_at", "")
        row["author"] = {"login": (row.get("user") or {}).get("login", "")}
        row["authorAssociation"] = row.get("author_association", "")
        out.append(row)
    return out


def skipped(issue: dict) -> bool:
    for label in issue.get("labels") or []:
        name = (label.get("name") if isinstance(label, dict) else str(label)).lower()
        if name in {"simplicio-loop:skip", "wontfix"}:
            return True
    return False
