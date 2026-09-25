"""``simplicio-py file`` — dispatch to the ``file`` subcommand group.

Extracted from `cli.py`'s `_run_file_command` (issue #103); behavior
unchanged. The actual ``file read`` implementation lives in
`simplicio/commands/file_read.py`.
"""

from __future__ import annotations

import argparse
import sys

CLI_PROG = "simplicio-py"


def run(a: argparse.Namespace) -> int:
    from .file_read import run as file_read_run

    if a.file_cmd == "read":
        return file_read_run(a)
    print(f"{CLI_PROG} file: unsupported command", file=sys.stderr)
    return 2
