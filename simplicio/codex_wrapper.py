"""Reversible, approval-preserving Codex CLI wrapper (issue #408)."""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

WRAPPER_MARKER = "# simplicio-codex-wrapper/v1"
DEFAULT_COMMAND = "codex"


def _wrapper_source(python_executable: str) -> str:
    return (
        f"#!{python_executable}\n"
        f"{WRAPPER_MARKER}\n"
        "from simplicio.codex_wrapper import run_wrapped\n"
        "raise SystemExit(run_wrapped())\n"
    )


def install_wrapper(path: str | Path, *, python_executable: str = sys.executable) -> Path:
    """Install only at an explicit path and refuse to overwrite another tool."""
    target = Path(path).expanduser().resolve()
    if target.exists():
        content = target.read_text(encoding="utf-8", errors="replace")
        if WRAPPER_MARKER not in content:
            raise FileExistsError(f"refusing to overwrite existing non-Simplicio wrapper: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_wrapper_source(python_executable), encoding="utf-8", newline="\n")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def uninstall_wrapper(path: str | Path) -> bool:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        return False
    content = target.read_text(encoding="utf-8", errors="replace")
    if WRAPPER_MARKER not in content:
        raise PermissionError(f"refusing to remove non-Simplicio wrapper: {target}")
    target.unlink()
    return True


def run_wrapped(argv: list[str] | None = None, *, command: str | None = None) -> int:
    """Forward Codex arguments unchanged without changing approval policy."""
    forwarded = list(sys.argv[1:] if argv is None else argv)
    codex = command or os.environ.get("SIMPLICIO_CODEX_COMMAND") or DEFAULT_COMMAND
    environment = os.environ.copy()
    # Prevent a nested Codex invocation from firing the same hook again. No
    # sandbox, approval-policy, or mutation flag is added or removed here.
    environment["SIMPLICIO_HOOK_GUARD"] = "1"
    completed = subprocess.run([codex, *forwarded], env=environment, check=False)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--install", metavar="PATH")
    actions.add_argument("--uninstall", metavar="PATH")
    actions.add_argument("--run", action="store_true")
    parser.add_argument("--python", dest="python_executable", default=sys.executable)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.install:
        sys.stdout.write(f"{install_wrapper(args.install, python_executable=args.python_executable)}\n")
        return 0
    if args.uninstall:
        return 0 if uninstall_wrapper(args.uninstall) else 1
    forwarded = args.args[1:] if args.args[:1] == ["--"] else args.args
    return run_wrapped(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
