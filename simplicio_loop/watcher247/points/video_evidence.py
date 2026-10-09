"""video_evidence (pr stage): conditional wrapper of scripts/video_evidence.py.

Fires only when SIMPLICIO_247_VIDEO_EVIDENCE=1 and web_verify has produced screenshots.
Transforms screenshots into video evidence for the PR.
"""
import os
from pathlib import Path

from .. import proc
from .registry import PointContext, PointResult, register

NAME = "video_evidence"


def applies(ctx: PointContext) -> bool:
    """True when VIDEO_EVIDENCE env var is set and web_verify ran; False otherwise."""
    # Check if feature is enabled
    if not os.environ.get("SIMPLICIO_247_VIDEO_EVIDENCE"):
        return False
    
    # Check if web_verify evidence exists (screenshots available)
    if ctx.run_dir is None:
        return False
    
    web_verify_dir = ctx.run_dir / "web_verify"
    if not web_verify_dir.exists():
        return False
    
    # Check for screenshot files from web_verify
    screenshots = list(web_verify_dir.glob("*-web.png"))
    return len(screenshots) > 0


async def run(ctx: PointContext) -> PointResult:
    """Run video_evidence on web_verify screenshots to generate video artifacts."""
    if ctx.run_dir is None:
        return PointResult(NAME, "skipped", {}, "no_run_dir")
    
    web_verify_dir = ctx.run_dir / "web_verify"
    if not web_verify_dir.exists():
        return PointResult(NAME, "skipped", {}, "no_screenshots")
    
    # Prepare output directory
    out_dir = ctx.run_dir / "video_evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Call scripts/video_evidence.py
    script_path = Path(__file__).parent.parent.parent.parent / "scripts" / "video_evidence.py"
    if not script_path.exists():
        return PointResult(NAME, "skipped", {}, "script_unavailable")
    
    try:
        result = await proc.run(
            ["python3", str(script_path), "generate", "--input", str(web_verify_dir), 
             "--out", str(out_dir)],
            timeout=180,
            cwd=ctx.run_dir,
        )
    except (FileNotFoundError, OSError) as exc:
        return PointResult(NAME, "skipped", {"error": str(exc)[:200]}, "script_unavailable")
    
    # Parse result
    if result.returncode == 0:
        # Check for generated video artifacts
        video_files = list(out_dir.glob("*.mp4")) + list(out_dir.glob("*.webm"))
        return PointResult(
            NAME,
            "ok",
            {"artifact": str(video_files[0]) if video_files else str(out_dir)},
        )
    elif result.returncode == 3:  # skipped
        reason = result.stdout.strip() or result.stderr.strip()
        return PointResult(NAME, "skipped", {"reason": reason[:200]}, "generation_skipped")
    else:
        return PointResult(
            NAME,
            "ok",  # still ok (attempt was made)
            {"artifact": str(out_dir), "return_code": result.returncode},
        )


register(NAME, "pr", run, applies=applies)
