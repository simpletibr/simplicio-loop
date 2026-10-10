"""Shared helpers of the evidence points (web_verify, video_evidence): the scripts/ workers and the clone's git state.

Every subprocess goes through sandbox.wrap + scrubbed_env and proc.run (async); nothing here is synchronous.
"""
import importlib.util
import os
import re
from pathlib import Path

from .. import proc, sandbox
from .registry import PointContext

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"  # not shipped in the wheel: absent there
_TAIL = 300


def script_path(name: str) -> Path | None:
    """scripts/<name> of the source checkout, or None (the point is then skipped|script_unavailable)."""
    path = SCRIPTS / name
    return path if path.is_file() else None


async def sandboxed(argv: list[str], *, clone: Path, state_dir: Path, timeout: float) -> proc.Result:
    """Run argv in the clone under the sandbox with the scrubbed env.

    `state_dir` is bound read-only: the script writes only its clone (a run dir inside the clone is writable for that reason)."""
    wrapped = sandbox.wrap(argv, clone=clone, state_dir=state_dir)
    env = sandbox.scrubbed_env(os.environ, home=Path.home())
    return await proc.run(wrapped, timeout=timeout, cwd=clone, env=env)


async def changed_files(ctx: PointContext) -> tuple[list[str], str | None]:
    """(files, error): the clone's working-tree changes: `git diff --name-only HEAD` plus untracked files."""
    env = sandbox.scrubbed_env(os.environ, home=Path.home())  # read-only git, as the tick runs git on the clone
    files: list[str] = []
    for argv in (["git", "diff", "--name-only", "HEAD"], ["git", "ls-files", "--others", "--exclude-standard"]):
        done = await proc.run(argv, timeout=30, cwd=Path(ctx.clone), env=env)
        if done.returncode != 0:
            return [], (done.stderr or done.stdout or f"exit {done.returncode}")[-_TAIL:]
        files += [line for line in done.stdout.splitlines() if line]
    return files, None


def frontend_files(files: list[str]) -> list[str]:
    """The files FE_RE of scripts/web_verify.py matches (imported, not copied)."""
    path = script_path("web_verify.py")
    if path is None:
        return []
    spec = importlib.util.spec_from_file_location("_scripts_web_verify", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pattern: re.Pattern = module.FE_RE
    return [f for f in files if pattern.search(f)]


def tail(result: proc.Result) -> str:
    return ((result.stdout or "") + (result.stderr or "")).strip()[-_TAIL:]
