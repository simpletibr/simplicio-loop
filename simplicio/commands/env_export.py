"""``simplicio-py env-export`` — print shell-safe exports from a dotenv file.

Extracted from `cli.py`'s `main()` body (issue #103); behavior unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys

CLI_PROG = "simplicio-py"


def run(a: argparse.Namespace) -> int:
    from ..runtime_env import parse_env_file, shell_export_lines

    try:
        values = parse_env_file(a.env_file)
    except OSError as exc:
        print(f"{CLI_PROG} env-export: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"{CLI_PROG} env-export: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(values, sort_keys=True))
    else:
        print("\n".join(shell_export_lines(values)))
    return 0
