"""The watcher's stages in the run turbo writes: ``intake`` first, ``pr`` after verify, ``done`` last.

One service run is one turbo run directory (``.simplicio-loop/orchestrator/runs/<run_id>/``, the kanban's card).
The watcher opens it at ``intake``, turbo continues it (orient, plan, apply, verify; ``--run-id``, ``--leave-open``)
and the watcher closes it with ``pr`` and ``done``. Payloads carry ids, numbers and statuses only: no issue text,
no secret. Fail-open: telemetry never breaks a tick.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..turbo_run import TurboRun
from . import state

_PR_NUMBER = re.compile(r"/pull/(\d+)")


def open_run(dest: Path, repo: str, number: int, *, fix: bool = False) -> str | None:
    """Start the run at ``intake`` and return its id, or None when the run could not be written."""
    try:
        run = TurboRun(dest, "host")
        run.enter("intake", repo=repo, issue=number, kind="fix" if fix else "issue")
        return run.run_id
    except Exception as exc:
        state.log(f"events: intake not written {repo}#{number}: {exc}")
        return None


def close_run(dest: Path, run_id: str | None, status: str, *, pr_url: str | None = None) -> None:
    """Write ``pr`` (when a PR was opened or updated) and close the run: ``ok``, ``failed`` or ``blocked``."""
    if run_id is None:
        return
    try:
        run = TurboRun(dest, "host", run_id)
        if pr_url and status == "ok":
            found = _PR_NUMBER.search(pr_url)
            run.enter("pr", pr_number=int(found.group(1)) if found else None)
        run.close(status)
    except Exception as exc:
        state.log(f"events: run {run_id} not closed: {exc}")
