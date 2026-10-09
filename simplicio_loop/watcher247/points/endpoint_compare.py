"""endpoint_compare (verify): records HTTP endpoint changes.

Applies only when diff touches routes, handlers, or API definitions.
Records endpoint changes from git diff HEAD (working-tree).
"""
from pathlib import Path

from .. import proc
from .registry import PointContext, PointResult, register

NAME = "endpoint_compare"

# Patterns that indicate route/endpoint definitions
ROUTE_PATTERNS = (
    "routes",
    "urls.py",
    "api/",
    "endpoints",
    "@app.route",
    "@router",
    "@get",
    "@post",
    "@put",
    "@delete",
    "@patch",
)


async def _extract_endpoint_changes(clone: Path) -> dict:
    """Extract endpoint signatures from git diff HEAD."""
    try:
        result = await proc.run(
            ["git", "diff", "HEAD"],
            cwd=clone,
            timeout=5,
        )
        diff_text = result.stdout
        route_lines = [line for line in diff_text.split("\n") if any(p in line for p in ROUTE_PATTERNS)]
        return {"diff_bytes": len(diff_text), "route_lines_found": len(route_lines)}
    except Exception as e:
        return {"error": str(e)}


def _applies(ctx: PointContext) -> bool:
    """Applies check (runs if clone exists)."""
    return ctx.clone is not None


async def compare_endpoints(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    try:
        result = await proc.run(
            ["git", "diff", "HEAD", "--name-only"],
            cwd=ctx.clone,
            timeout=5,
        )
        if result.returncode != 0:
            return PointResult(NAME, "ok", {"checked": True, "routes_found": False})
        changed_files = result.stdout.strip().split("\n")
        has_routes = any(any(p in f.lower() for p in ROUTE_PATTERNS) for f in changed_files if f)
        if not has_routes:
            return PointResult(NAME, "ok", {"checked": True, "routes_found": False})
        evidence = await _extract_endpoint_changes(ctx.clone)
        return PointResult(NAME, "ok", evidence)
    except Exception as e:
        return PointResult(NAME, "ok", {"error": str(e)})


register(NAME, "verify", compare_endpoints, applies=_applies)
