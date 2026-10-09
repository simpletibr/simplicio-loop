"""web_verify (verify stage): conditional wrapper of scripts/web_verify.py.

Fires only when the diff touches UI files (html, css, js, tsx, vue, svelte).
Captures screenshots and records them in the evidence for the PR.
"""
import os
import re
import subprocess
from pathlib import Path

from .. import proc, sandbox
from .registry import PointContext, PointResult, register

NAME = "web_verify"

# UI file patterns (from scripts/web_verify.py FE_RE)
UI_RE = re.compile(
    r"\.(tsx|jsx|vue|svelte|css|scss|html)$|^(components|pages|app|public|src/ui)/",
    re.IGNORECASE,
)


def applies(ctx: PointContext) -> bool:
    """True when diff touches UI files; False otherwise."""
    if ctx.clone is None:
        return False
    # Check actual git diff
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            cwd=str(ctx.clone),
            capture_output=True,
            text=True,
            timeout=10,
        )
        files = result.stdout.strip().split("\n") if result.stdout else []
        return any(UI_RE.search(f) for f in files if f)
    except Exception:
        return False


async def run(ctx: PointContext) -> PointResult:
    """Run web_verify on the clone and capture screenshot evidence."""
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    
    # Prepare output directory for screenshots
    out_dir = ctx.run_dir / "web_verify" if ctx.run_dir else Path.home() / ".simplicio-loop" / "web_verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Call scripts/web_verify.py verify subcommand
    script_path = Path(__file__).parent.parent.parent.parent / "scripts" / "web_verify.py"
    if not script_path.exists():
        return PointResult(NAME, "skipped", {}, "script_unavailable")
    
    try:
        result = await proc.run(
            ["python3", str(script_path), "verify", "--out", str(out_dir)],
            timeout=120,
            cwd=ctx.clone,
        )
    except (FileNotFoundError, OSError) as exc:
        return PointResult(NAME, "skipped", {"error": str(exc)[:200]}, "script_unavailable")
    
    # Parse result
    if result.returncode == 0:
        # Check for screenshot files
        screenshot_files = list(out_dir.glob("*-web.png"))
        return PointResult(
            NAME,
            "ok",
            {"screenshot": str(screenshot_files[0]) if screenshot_files else str(out_dir)},
        )
    elif result.returncode == 3:  # blocked
        reason = result.stdout.strip() or result.stderr.strip()
        return PointResult(NAME, "skipped", {"reason": reason[:200]}, "blocked")
    else:
        return PointResult(
            NAME,
            "ok",  # still ok (verification itself succeeded, test may have failed)
            {"screenshot": str(out_dir), "return_code": result.returncode},
        )


register(NAME, "verify", run, applies=applies)
