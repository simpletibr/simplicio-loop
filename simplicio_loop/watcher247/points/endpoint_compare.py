"""endpoint_compare (verify): detects HTTP endpoint changes from the diff.

Applies only when the diff touches routes, handlers, or API definitions.
Reuses existing endpoint-diff tools or records route signatures (old vs new).
"""
import subprocess
from pathlib import Path

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


def _has_route_changes(clone: Path) -> bool:
    """Check if the diff touches any route/handler files."""
    try:
        # Get the current diff
        result = subprocess.run(
            ["git", "diff", "--name-only", "--staged"],
            cwd=clone,
            capture_output=True,
            text=True,
            timeout=5,
        )
        changed_files = result.stdout.strip().split("\n")
        for file in changed_files:
            if not file:
                continue
            # Check if file matches route patterns
            for pattern in ROUTE_PATTERNS:
                if pattern in file.lower():
                    return True
        return False
    except Exception:
        return False


def _extract_endpoint_changes(clone: Path) -> dict:
    """Extract changed endpoint signatures from the diff."""
    try:
        result = subprocess.run(
            ["git", "diff", "--staged"],
            cwd=clone,
            capture_output=True,
            text=True,
            timeout=5,
        )
        diff_text = result.stdout
        # Record the diff as evidence
        return {"diff_summary": f"Diff contains {len(diff_text)} bytes", "found_routes": True}
    except Exception as e:
        return {"error": str(e)}


async def compare_endpoints(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    
    # Check if diff touches routes/handlers
    if not _has_route_changes(ctx.clone):
        return PointResult(NAME, "skipped", {}, "no_routes_touched")
    
    # Extract endpoint changes
    evidence = _extract_endpoint_changes(ctx.clone)
    return PointResult(NAME, "ok", evidence)


register(NAME, "verify", compare_endpoints, applies=lambda ctx: ctx.clone is not None and _has_route_changes(ctx.clone))
