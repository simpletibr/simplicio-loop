"""``simplicio-py mechanical-edit`` / ``simplicio-py edit``.

Extracted from `cli.py`'s `_run_mechanical_edit_command`/`_run_edit_command`
(issue #103); behavior unchanged. ``edit`` delegates to the native
``simplicio`` Rust binary when available, falling back to
``run_mechanical_edit`` (the pure-Python implementation) otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

from ..runtime_bridge import record_delegation
from ._shared import read_text_source

CLI_PROG = "simplicio-py"


def run_mechanical_edit(a: argparse.Namespace) -> int:
    from ..mechanical_edit import execute_plan_json

    try:
        plan_text = read_text_source(a.plan)
    except OSError as exc:
        print(f"{CLI_PROG} mechanical-edit: {exc}", file=sys.stderr)
        return 2
    result = execute_plan_json(plan_text, root=a.root, apply=a.apply)
    if a.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"{result['status']}: applied={result['applied']} noop={result['noop']}")
        if result.get("planned_diff"):
            print(result["planned_diff"])
        for error in result.get("errors", []):
            print(f"error: {error.get('code')}: {error.get('message')}", file=sys.stderr)
    return 0 if result["status"] == "ok" else 1


def _runtime_edit_binary() -> str | None:
    if os.environ.get("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT"):
        return None
    return shutil.which("simplicio")


def run_edit(a: argparse.Namespace) -> int:
    runtime = None if a.no_runtime else _runtime_edit_binary()
    if runtime:
        cmd = [runtime, "edit", "--plan", a.plan, "--repo", a.root]
        if a.json:
            cmd.append("--json")
        if not a.apply:
            cmd.append("--dry-run")
        try:
            plan_stdin = read_text_source("-") if a.plan == "-" else None
            completed = subprocess.run(cmd, input=plan_stdin, text=True)
        except OSError as exc:
            print(
                f"{CLI_PROG} edit: runtime delegation failed ({exc}); using local fallback", file=sys.stderr
            )
            record_delegation("edit", "python-fallback", root=a.root, reason=f"delegation-error: {exc}")
        else:
            record_delegation("edit", "native", root=a.root)
            return completed.returncode
    else:
        if a.no_runtime:
            reason = "user-forced-python (--no-runtime)"
        elif os.environ.get("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT"):
            reason = "user-forced-python (SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT)"
        else:
            reason = "binary-not-found"
        route = "python-forced" if reason.startswith("user-forced-python") else "python-fallback"
        record_delegation("edit", route, root=a.root, reason=reason)
    return run_mechanical_edit(a)
