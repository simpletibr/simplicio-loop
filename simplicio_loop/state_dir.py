"""Single owner of the loop's `.simplicio-loop/` state directory.

`ensure_state_dir(root)` is the one place that first creates the state
directory for a repo, and it keeps that directory out of `git status`, so a
fresh clone never has to gitignore loop state by hand. It idempotently
- appends `.simplicio-loop/` to the repo's `<git-dir>/info/exclude`, which covers a repo that has no `.gitignore`;
- appends `.simplicio-loop/` to `<root>/.gitignore` when that file EXISTS and no line already covers the
  directory (see `COVERING_LINES`), so the entry is there for every clone and every cloud worker. It never creates a
  `.gitignore`, keeps the file's own line endings, and leaves a file it cannot read or write untouched.

Call this from every entry point that may be the first to touch the state dir for a repo: `orient`, `prepare` and
`turbo` (its request, its apply and its provider mode).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

STATE_DIR_NAME = ".simplicio-loop"
EXCLUDE_LINE = ".simplicio-loop/"
# A stripped line of a .gitignore that already ignores the whole state directory.
COVERING_LINES = frozenset({
    ".simplicio-loop", ".simplicio-loop/", "/.simplicio-loop", "/.simplicio-loop/",
    ".simplicio-loop/*", "/.simplicio-loop/*", ".simplicio-loop/**", "/.simplicio-loop/**",
})


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


def _append_gitignore_line_once(gitignore: Path) -> None:
    """Append the state directory to an EXISTING `.gitignore` unless a line already covers it.

    Bytes in, bytes out: a CRLF file stays CRLF, a file without a final newline gets one first, and a file that is
    not UTF-8 or cannot be written is left as it is. Losing the entry is better than damaging the user's file.
    """
    try:
        if not gitignore.is_file():
            return
        raw = gitignore.read_bytes()
        text = raw.decode("utf-8-sig")
        if any(line.strip() in COVERING_LINES for line in text.splitlines()):
            return
        newline = "\r\n" if "\r\n" in text else "\n"
        lead = "" if not raw or raw.endswith(b"\n") else newline
        with gitignore.open("ab") as handle:
            handle.write((lead + EXCLUDE_LINE + newline).encode("utf-8"))
    except (OSError, UnicodeDecodeError):
        return


def ensure_state_dir(root: Path) -> Path:
    """Create `<root>/.simplicio-loop/` and keep it out of `git status`.

    Idempotent: calling it repeatedly never duplicates a line, and it never fails when `root` is not a git
    repository (it creates the directory, skips the info/exclude step and still edits an existing `.gitignore`).
    """
    root = Path(root)
    state_dir = root / STATE_DIR_NAME
    state_dir.mkdir(parents=True, exist_ok=True)

    exclude_path = _git_info_exclude_path(root)
    if exclude_path is not None:
        _append_exclude_line_once(exclude_path)
    _append_gitignore_line_once(root / ".gitignore")

    return state_dir
