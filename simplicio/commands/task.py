"""``simplicio-py task`` — run a task.

Extracted from `cli.py`'s `_run_task_command` (issue #103); behavior
unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys

from ._shared import force_local_if_requested


def run(a: argparse.Namespace) -> int:
    from ..pipeline import run_task
    from ..precedent import auto_detect_stack

    force_local_if_requested(a)
    stack = auto_detect_stack(a.root, a.stack)
    if a.json or a.dry_run_task:
        result = run_task(
            a.root,
            stack,
            a.goal,
            a.target,
            a.criteria,
            a.constraints,
            dry_run_task=a.dry_run_task,
            bound_paths=a.bound_paths,
            quiet=a.json,
        )
        if a.json:
            print(json.dumps(result, sort_keys=True))
        else:
            status = "DRY-RUN" if a.dry_run_task else "DONE"
            print(f"{status}: {result['diff_summary']}")
            for warning in result["warnings"]:
                print(f"warning: {warning}", file=sys.stderr)
        return 0 if (a.dry_run_task or result["applied"]) else 1
    result = run_task(
        a.root,
        stack,
        a.goal,
        a.target,
        a.criteria,
        a.constraints,
        bound_paths=a.bound_paths,
    )
    status = "DONE" if result["applied"] else "FAILED"
    print(f"{status}: {result['diff_summary']}")
    for warning in result["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    return 0 if result["applied"] else 1
