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
    """The non-archived repos of every owner in SIMPLICIO_247_OWNERS. `name` is the full name, `owner/repo`.

    No name filter: a repo is watched when its own `.simplicio-loop/loop.toml` opts it in, which the tick checks.
    """
    out = []
    for owner in config.owners():
        rows = await gh_json([
            "repo", "list", owner, "--limit", "200",
            "--json", "name,isArchived,defaultBranchRef",
        ], timeout=90)
        for row in rows:
            name = row.get("name") or ""
            if row.get("isArchived") or not name:
                continue
            branch = ((row.get("defaultBranchRef") or {}).get("name")) or "main"
            out.append({"name": f"{owner}/{name}", "branch": branch})
    return out


async def open_issues(repo: str) -> list[dict]:
    """The open issues of `repo` (`owner/repo`), without the PRs that the issues route also lists."""
    try:
        rows = await gh_json([
            "api", "--paginate", "-X", "GET", f"repos/{repo}/issues",
            "-f", "state=open", "-F", "per_page=100",
        ], timeout=120)
    except RuntimeError as exc:
        if "issues are disabled" in str(exc).lower():
            await state.mark_issues_disabled(repo)
            return []
        raise
    return [row for row in rows if "pull_request" not in row]  # /issues also lists PRs


def skipped(issue: dict) -> bool:
    for label in issue.get("labels") or []:
        name = (label.get("name") if isinstance(label, dict) else str(label)).lower()
        if name in {"simplicio-loop:skip", "wontfix"}:
            return True
    return False
