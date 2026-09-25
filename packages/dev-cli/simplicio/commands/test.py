"""``simplicio-py test`` — dispatch to the ``test`` subcommand group.

Extracted from `cli.py`'s `_run_test_command` (issue #103); behavior
unchanged. The actual ``test run`` implementation lives in
`simplicio/commands/test_run.py`.
"""

from __future__ import annotations

import argparse
import sys

CLI_PROG = "simplicio-py"


def run(a: argparse.Namespace) -> int:
    from .test_run import run as test_run_run

    if a.test_cmd == "run":
        extra_args = a.extra_args
        if extra_args and extra_args[0] == "--":
            extra_args = extra_args[1:]
        # `--cmd` is parsed into `test_program` to avoid colliding with the
        # top-level subparser's `dest="cmd"`; translate to the attribute
        # name `commands/test_run.py` expects.
        a.cmd = a.test_program
        return test_run_run(a, extra_args)
    print(f"{CLI_PROG} test: unsupported command", file=sys.stderr)
    return 2
