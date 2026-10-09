"""web_research (plan): optional web research gated by environment variable.

Applies only when SIMPLICIO_247_WEB_RESEARCH=1.
Default is disabled (off) for security. When enabled, documents the intent.
This is a documented hook point for future web search integration.
"""
import os

from .registry import PointContext, PointResult, register

NAME = "web_research"


def _is_enabled(ctx: PointContext) -> bool:
    """Check if web research is enabled via env var."""
    return os.getenv("SIMPLICIO_247_WEB_RESEARCH") == "1"


async def research_web(ctx: PointContext) -> PointResult:
    """Hook point for web research integration.
    
    Currently documents the intent and returns skipped by default.
    When enabled, this point will support optional web searches during planning.
    """
    if not _is_enabled(ctx):
        return PointResult(
            NAME,
            "skipped",
            {"reason": "web_research disabled by default for security"},
            "disabled",
        )
    
    # When enabled, document the search intent from task
    evidence = {
        "hook_status": "enabled",
        "note": "Hook point for future web search integration",
        "task_text_available": ctx.task_text is not None,
    }
    
    return PointResult(
        NAME,
        "ok",
        evidence,
    )


register(NAME, "plan", research_web, applies=_is_enabled)
