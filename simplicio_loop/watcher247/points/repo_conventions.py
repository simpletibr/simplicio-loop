"""repo_conventions (intake): read target repo's conventions for branch rules, commit style, test command.

The summary is the one `scripts/repo_conventions.py learn` prints: branch scheme, commit style, ticket
pattern, PR sections, docs and the test/lint command, mined from the clone's git history and files by
`simplicio_loop.repo_conventions` (no second implementation here).
"""
import asyncio

from ... import repo_conventions as mined
from .registry import PointContext, PointResult, register

NAME = "repo_conventions"


async def read_conventions(ctx: PointContext) -> PointResult:
    # Not conditional on the issue on purpose: the conventions belong to the clone, so it runs for every task.
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    profile = await asyncio.to_thread(mined.profile_for_repo, str(ctx.clone))
    return PointResult(NAME, "ok", {"summary": " | ".join(mined.summary_lines(profile))})


register(NAME, "intake", read_conventions)
