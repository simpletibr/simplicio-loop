"""video_evidence (pr stage): records the running app with Playwright, the default evidence flow of a front-end change.

The default engine runs `scripts/video_evidence.py verify --url <app>`: the live session is recorded on the installed
Playwright of the loop's evidence tools. The app is the URL web_verify drives (SIMPLICIO_247_WEB_VERIFY_URL); without it the
point is skipped|no_url, never a fake pass. hyperframes (a captioned slideshow of the web_verify screenshots) runs only when
the work item explicitly asks for a video, the request `video_evidence.py detect` recognises.

Fires only when SIMPLICIO_247_VIDEO_EVIDENCE=1. ok only when the script exits 0 and left the recording; any nonzero exit is an error.
"""
import os
import sys
from pathlib import Path

from . import _scripts
from .registry import PointContext, PointResult, register
from .web_verify import URL_ENV

NAME = "video_evidence"
ENABLE_ENV = "SIMPLICIO_247_VIDEO_EVIDENCE"
TIMEOUT_S = 600
VIDEO_NAME = "evidence"
_ERROR_CODE = {1: "video_evidence_failed", 3: "video_evidence_blocked"}  # 3 = the evidence tools, ffmpeg or hyperframes not ready


def applies(ctx: PointContext) -> bool:
    """Opt-in by env; what each engine needs (the app URL, or the web_verify screenshots) is checked by run()."""
    return os.environ.get(ENABLE_ENV) == "1" and ctx.run_dir is not None


def _explainer_requested(issue: dict | None) -> bool:
    """True when the work item explicitly asks for a video: the request matcher of scripts/video_evidence.py `detect`."""
    text = "\n".join(str(part) for part in ((issue or {}).get("title"), (issue or {}).get("body")) if part)
    return bool(_scripts.load_script("video_evidence.py").is_video_request(text))


def _recording(out_dir: Path, issue: str) -> Path | None:
    """The clip the worker left: the mp4 when FFmpeg converted the recording, else Playwright's .webm."""
    mp4 = out_dir / f"{VIDEO_NAME}-{issue}.mp4"
    if mp4.is_file():
        return mp4
    return next(iter(sorted(out_dir.rglob("*.webm"))), None)


async def run(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    if ctx.run_dir is None:
        return PointResult(NAME, "skipped", {}, "no_run_dir")
    script = _scripts.script_path("video_evidence.py")
    if script is None:
        return PointResult(NAME, "skipped", {}, "script_unavailable")
    issue = str((ctx.issue or {}).get("number", "x"))
    out_dir = ctx.run_dir / "video_evidence"
    if _explainer_requested(ctx.issue):  # hyperframes: only for an explicit request, from the web_verify screenshots
        frames = ctx.run_dir / "web_verify"
        if not any(frames.glob("*.png")):
            return PointResult(NAME, "skipped", {}, "no_screenshots")
        title = str((ctx.issue or {}).get("title") or ctx.repo)[:80].lstrip("-") or ctx.repo
        argv = [sys.executable, str(script), "verify", "--engine", "hyperframes", "--frames", str(frames),
                "--name", VIDEO_NAME, "--title", title, "--issue", issue, "--out", str(out_dir)]
    else:  # Playwright: the recording of a front-end change, of the app web_verify drives
        files, error = await _scripts.changed_files(ctx)
        if error:
            return PointResult(NAME, "error", {"error": error}, "git_failed")
        if not _scripts.frontend_files(files):
            return PointResult(NAME, "skipped", {}, "not_applicable")
        url = os.environ.get(URL_ENV, "").strip()
        if not url:
            return PointResult(NAME, "skipped", {}, "no_url")
        argv = [sys.executable, str(script), "verify", "--url", url, "--name", VIDEO_NAME, "--issue", issue,
                "--out", str(out_dir)]
    out_dir.mkdir(parents=True, exist_ok=True)
    done = await _scripts.sandboxed(argv, clone=ctx.clone, state_dir=out_dir, timeout=TIMEOUT_S)
    if done.returncode != 0:
        code = _ERROR_CODE.get(done.returncode, "video_evidence_error")
        return PointResult(NAME, "error", {"return_code": done.returncode, "output": _scripts.tail(done)}, code)
    video = _recording(out_dir, issue)
    if video is None:
        return PointResult(NAME, "error", {"expected": str(out_dir / f"{VIDEO_NAME}-{issue}.mp4")}, "no_video")
    return PointResult(NAME, "ok", {"artifact": str(video)})


register(NAME, "pr", run, applies=applies)
