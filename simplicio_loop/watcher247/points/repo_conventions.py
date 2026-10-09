"""repo_conventions (intake): read target repo's conventions for branch rules, commit style, test command.

Reads CONTRIBUTING.md, AGENTS.md, and .github/ conventions to extract branch rules, commit scope
style, and test commands. Returns a compact summary in evidence.
"""
from pathlib import Path

from .registry import PointContext, PointResult, register

NAME = "repo_conventions"


def _read_file_excerpt(path: Path, max_lines: int = 10) -> str | None:
    """Read file and return first few lines, or None if not found."""
    try:
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        return "\n".join(lines[:max_lines])
    except (OSError, UnicodeDecodeError):
        return None


async def read_conventions(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")

    clone_path = Path(ctx.clone)
    summary_parts = []

    # Read CONTRIBUTING.md if exists
    contrib = _read_file_excerpt(clone_path / "CONTRIBUTING.md")
    if contrib:
        summary_parts.append(f"CONTRIBUTING.md: {contrib[:100]}...")

    # Read AGENTS.md if exists
    agents = _read_file_excerpt(clone_path / "AGENTS.md")
    if agents:
        summary_parts.append(f"AGENTS.md: {agents[:100]}...")

    # Read .github/CONTRIBUTING.md if exists
    github_contrib = _read_file_excerpt(clone_path / ".github" / "CONTRIBUTING.md")
    if github_contrib:
        summary_parts.append(f".github/CONTRIBUTING.md: {github_contrib[:100]}...")

    summary = " | ".join(summary_parts) if summary_parts else "No conventions found"
    
    return PointResult(NAME, "ok", {"summary": summary})


register(NAME, "intake", read_conventions)
