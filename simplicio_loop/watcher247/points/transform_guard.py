"""transform_guard (verify): ensures removed symbols are not referenced elsewhere.

Applies only when task mentions refactor, rename, migrate, or transform.
Uses git grep to verify no dangling references remain.
"""
import re
import subprocess
from pathlib import Path

from .registry import PointContext, PointResult, register

NAME = "transform_guard"
TRANSFORM_KEYWORDS = ("refactor", "rename", "migrate", "transform", "restructure")


def _is_transform_task(task_text: str | None) -> bool:
    """Check if task mentions transformation keywords."""
    if not task_text:
        return False
    task_lower = task_text.lower()
    return any(keyword in task_lower for keyword in TRANSFORM_KEYWORDS)


def _find_removed_symbols(clone: Path) -> list[str]:
    """Extract symbol names from removed lines in the diff."""
    try:
        result = subprocess.run(
            ["git", "diff", "--staged"],
            cwd=clone,
            capture_output=True,
            text=True,
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


def _check_references(clone: Path, symbols: list[str]) -> dict:
    """Use git grep to find if removed symbols are referenced."""
    if not symbols:
        return {"checked": False, "references": []}
    try:
        references = []
        for symbol in symbols:
            result = subprocess.run(
                ["git", "grep", "-n", symbol],
                cwd=clone,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout:
                refs = result.stdout.strip().split("\n")
                references.extend([(symbol, ref) for ref in refs])
        return {"checked": True, "references": references}
    except Exception as e:
        return {"error": str(e)}


async def guard_transform(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    if not _is_transform_task(ctx.task_text):
        return PointResult(NAME, "skipped", {}, "not_a_transform")
    removed_symbols = _find_removed_symbols(ctx.clone)
    if not removed_symbols:
        return PointResult(NAME, "ok", {"symbols_checked": 0})
    refs_info = _check_references(ctx.clone, removed_symbols)
    if refs_info.get("references"):
        return PointResult(
            NAME,
            "blocked",
            {"removed_symbols": removed_symbols, "references": refs_info.get("references", [])},
            "removed_symbols_still_referenced",
        )
    return PointResult(NAME, "ok", {"symbols_checked": len(removed_symbols), "all_safe": True})


register(NAME, "verify", guard_transform, applies=_is_transform_task, blocking=True)
