"""Single owner of the loop's `.simplicio-loop/` state directory.

`ensure_state_dir(root)` is the one place that first creates the state
directory for a repo, and it keeps that directory out of `git status` by
using `.git/info/exclude`, which is never tracked. This prevents the watcher
from seeing reused clones as dirty on subsequent runs.

Call this from every entry point that may be the first to touch the state dir for a repo: `orient`, `prepare` and
`turbo` (its request, its apply and its provider mode).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

STATE_DIR_NAME = ".simplicio-loop"
EXCLUDE_LINE = ".simplicio-loop/"


def _git_info_exclude_path(root: Path) -> Path | None:
    """Return the repo's info/exclude path, or None if `root` isn't a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = (root / path).resolve()
    return path


def _append_exclude_line_once(exclude_path: Path) -> None:
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if exclude_path.exists():
        existing = exclude_path.read_text(encoding="utf-8")
    lines = existing.splitlines()
    if EXCLUDE_LINE in lines:
        return
    with exclude_path.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(EXCLUDE_LINE + "\n")


def ensure_state_dir(root: Path) -> Path:
    """Create `<root>/.simplicio-loop/` and keep it out of `git status`.

    Uses `.git/info/exclude` (which is never tracked) to ensure reused clones
    don't appear dirty on subsequent runs. Idempotent: calling it repeatedly
    never duplicates a line.
    """
    root = Path(root)
    state_dir = root / STATE_DIR_NAME
    state_dir.mkdir(parents=True, exist_ok=True)

    exclude_path = _git_info_exclude_path(root)
    if exclude_path is not None:
        _append_exclude_line_once(exclude_path)

    return state_dir
