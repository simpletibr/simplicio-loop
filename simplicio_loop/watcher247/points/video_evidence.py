"""video_evidence (pr stage): runs `scripts/video_evidence.py verify --engine hyperframes` on the web_verify screenshots.

Fires only when SIMPLICIO_247_VIDEO_EVIDENCE=1 and web_verify left screenshots in <run_dir>/web_verify.
ok only when the script exits 0 and wrote the .mp4; any nonzero exit is an error.
"""
import os
import sys

from . import _scripts
from .registry import PointContext, PointResult, register

NAME = "video_evidence"
ENABLE_ENV = "SIMPLICIO_247_VIDEO_EVIDENCE"
TIMEOUT_S = 600
VIDEO_NAME = "evidence"
_ERROR_CODE = {1: "video_evidence_failed", 3: "video_evidence_blocked"}  # 3 = Node/ffmpeg/hyperframes missing


def applies(ctx: PointContext) -> bool:
    """Opt-in by env, and only with web_verify screenshots to assemble."""
    if os.environ.get(ENABLE_ENV) != "1" or ctx.run_dir is None:
        return False
    return any((ctx.run_dir / "web_verify").glob("*.png"))


async def run(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    if ctx.run_dir is None:
        return PointResult(NAME, "skipped", {}, "no_run_dir")
    frames = ctx.run_dir / "web_verify"
    if not any(frames.glob("*.png")):
        return PointResult(NAME, "skipped", {}, "no_screenshots")
    script = _scripts.script_path("video_evidence.py")
    if script is None:
        return PointResult(NAME, "skipped", {}, "script_unavailable")
    out_dir = ctx.run_dir / "video_evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    issue = str((ctx.issue or {}).get("number", "x"))
    title = str((ctx.issue or {}).get("title") or ctx.repo)[:80].lstrip("-") or ctx.repo
    argv = [sys.executable, str(script), "verify", "--engine", "hyperframes", "--frames", str(frames),
            "--name", VIDEO_NAME, "--title", title, "--issue", issue, "--out", str(out_dir)]
    done = await _scripts.sandboxed(argv, clone=ctx.clone, state_dir=out_dir, timeout=TIMEOUT_S)
    if done.returncode != 0:
        code = _ERROR_CODE.get(done.returncode, "video_evidence_error")
        return PointResult(NAME, "error", {"return_code": done.returncode, "output": _scripts.tail(done)}, code)
    video = out_dir / f"{VIDEO_NAME}-{issue}.mp4"
    if not video.is_file():
        return PointResult(NAME, "error", {"expected": str(video)}, "no_video")
    return PointResult(NAME, "ok", {"artifact": str(video)})


register(NAME, "pr", run, applies=applies)
