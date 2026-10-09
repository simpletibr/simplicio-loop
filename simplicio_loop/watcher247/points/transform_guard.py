"""transform_guard (verify): records removed symbol usage for refactors.

Applies only when task mentions refactor, rename, migrate, or transform.
Records evidence of symbol removals; not blocking (documentation only).
"""
import re
from pathlib import Path

from .. import proc
from .registry import PointContext, PointResult, register

NAME = "transform_guard"
TRANSFORM_KEYWORDS = ("refactor", "rename", "migrate", "transform", "restructure")


def _is_transform_task(task_text: str | None) -> bool:
    """Check if task mentions transformation keywords."""
    if not task_text:
        return False
    task_lower = task_text.lower()
    return any(keyword in task_lower for keyword in TRANSFORM_KEYWORDS)


async def _find_removed_symbols(clone: Path) -> list[str]:
    """Extract symbol names from removed lines using git diff HEAD."""
    try:
        result = await proc.run(
            ["git", "diff", "HEAD"],
            cwd=clone,
            timeout=5,
        )
        diff_text = result.stdout
        removed_symbols = []
        patterns = [
            r"^-\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(",
            r"^-\s*class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[\(:]" ,
            r"^-\s*from\s+.*\s+import\s+([a-zA-Z_][a-zA-Z0-9_,\s]*)",
        ]
        for line in diff_text.split("\n"):
            if not line.startswith("-"):
                continue
            for pattern in patterns:
                match = re.search(pattern, line)
                if match:
                    symbol = match.group(1).strip()
                    if symbol and symbol not in removed_symbols:
                        removed_symbols.append(symbol)
        return removed_symbols
    except Exception:
        return []


async def _check_references(clone: Path, symbols: list[str]) -> dict:
    """Use git grep to find if removed symbols are referenced."""
    if not symbols:
        return {"checked": False, "references": []}
    try:
        references = []
        for symbol in symbols:
            result = await proc.run(
                ["git", "grep", "-n", symbol],
                cwd=clone,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                refs = result.stdout.strip().split("\n")
                references.extend([(symbol, ref) for ref in refs[:3]])  # limit to 3 refs per symbol
        return {"checked": True, "references": references}
    except Exception as e:
        return {"error": str(e)}


def _applies(ctx: PointContext) -> bool:
    """Check if this is a transform task."""
    return _is_transform_task(ctx.task_text)


async def guard_transform(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    if not _is_transform_task(ctx.task_text):
        return PointResult(NAME, "skipped", {}, "not_a_transform")
    removed_symbols = await _find_removed_symbols(ctx.clone)
    if not removed_symbols:
        return PointResult(NAME, "ok", {"symbols_checked": 0})
    refs_info = await _check_references(ctx.clone, removed_symbols)
    if refs_info.get("references"):
        return PointResult(
            NAME,
            "ok",
            {"removed_symbols": removed_symbols, "still_referenced": len(refs_info.get("references", []))},
        )
    return PointResult(NAME, "ok", {"symbols_checked": len(removed_symbols), "all_safe": True})


register(NAME, "verify", guard_transform, applies=_applies)
