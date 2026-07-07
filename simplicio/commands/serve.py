"""``simplicio-py serve`` — run simplicio-dev-cli as a server.

Extracted from `cli.py`'s `_run_serve_command` (issue #103); behavior
unchanged.
"""

from __future__ import annotations

import argparse
import sys

CLI_PROG = "simplicio-py"


def run(a: argparse.Namespace) -> int:
    if not a.mcp:
        print(f"{CLI_PROG} serve: only --mcp is supported today", file=sys.stderr)
        return 2
    from ..mcp_server import serve_stdio

    serve_stdio()
    return 0
