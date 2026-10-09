"""web_verify (verify stage): runs `scripts/web_verify.py run` when the clone's working tree changed front-end files.

The watcher does not serve the clone's UI, so the URL of an already running app comes from
SIMPLICIO_247_WEB_VERIFY_URL; without it the point is skipped|no_url (never a fake pass). ok only when the
script exits 0 and wrote the screenshot; any nonzero exit is an error.
"""
import os
import sys

from . import _scripts
from .registry import PointContext, PointResult, register

NAME = "web_verify"
URL_ENV = "SIMPLICIO_247_WEB_VERIFY_URL"
TIMEOUT_S = 300
_ERROR_CODE = {1: "web_verify_failed", 3: "web_verify_blocked"}  # 1 = assertion failed, 3 = toolchain missing


def applies(ctx: PointContext) -> bool:
    """Cheap precheck; the diff of the clone is async (proc.run), so run() skips with not_applicable on no FE change."""
    return ctx.clone is not None


async def run(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    if ctx.run_dir is None:
        return PointResult(NAME, "skipped", {}, "no_run_dir")
    script = _scripts.script_path("web_verify.py")
    if script is None:
        return PointResult(NAME, "skipped", {}, "script_unavailable")
    files, error = await _scripts.changed_files(ctx)
    if error:
        return PointResult(NAME, "error", {"error": error}, "git_failed")
    frontend = _scripts.frontend_files(files)
    if not frontend:
        return PointResult(NAME, "skipped", {}, "not_applicable")
    url = os.environ.get(URL_ENV, "").strip()
    if not url:
        return PointResult(NAME, "skipped", {"frontend_files": frontend[:20]}, "no_url")
    out_dir = ctx.run_dir / "web_verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    issue = str((ctx.issue or {}).get("number", "x"))
    argv = [sys.executable, str(script), "run", "--url", url, "--issue", issue, "--out", str(out_dir)]
    done = await _scripts.sandboxed(argv, clone=ctx.clone, writable=out_dir, timeout=TIMEOUT_S)
    if done.returncode != 0:
        code = _ERROR_CODE.get(done.returncode, "web_verify_error")
        return PointResult(NAME, "error", {"return_code": done.returncode, "output": _scripts.tail(done)}, code)
    screenshot = out_dir / f"{issue}-web.png"
    if not screenshot.is_file():
        return PointResult(NAME, "error", {"expected": str(screenshot)}, "no_screenshot")
    return PointResult(NAME, "ok", {"screenshot": str(screenshot), "url": url, "frontend_files": frontend[:20]})


register(NAME, "verify", run, applies=applies)
