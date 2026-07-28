"""Small helpers shared by more than one `simplicio/commands/*.py` handler.

Not a subcommand itself — just factored out of `cli.py` (issue #103) so
`read_text_source` and `try_route_via_simplicio` have one home instead of
being duplicated across handlers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def read_text_source(path: str) -> str:
    """Read *path*, or stdin when *path* is the literal string ``"-"``."""
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        print(f"{Path(sys.argv[0]).name}: error: cannot read {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def force_local_if_requested(a: argparse.Namespace) -> None:
    """Reject the removed local-LLM execution mode."""
    if getattr(a, "local", False):
        raise SystemExit("simplicio-py: local LLM execution is disabled")


def parse_rust_flags(args: list[str]) -> tuple[list[str], bool, bool]:
    """Strip ``--native`` and ``--python`` flags from *args*.

    Returns ``(cleaned_args, native_flag, python_flag)`` where the flags
    have been removed from the argument list.
    """
    cleaned: list[str] = []
    native = False
    python = False
    for a in args:
        if a == "--native":
            native = True
        elif a == "--python":
            python = True
        else:
            cleaned.append(a)
    return cleaned, native, python


def try_route_via_simplicio(
    cmd_name: str,
    args: list[str],
    *,
    prefer_native: bool = True,
    prefer_python: bool = False,
) -> int | None:
    """Attempt to route *cmd_name* via the Rust ``simplicio`` binary.

    Returns the exit code if the binary handled the command, or ``None``
    if the caller should fall back to the Python implementation.
    """
    try:
        from . import route_command

        return route_command(
            cmd_name,
            args,
            prefer_native=prefer_native,
            prefer_python=prefer_python,
        )
    except ImportError:
        return None
