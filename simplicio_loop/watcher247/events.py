"""The watcher's stages in the run turbo writes: ``intake`` first, ``pr`` after verify, ``done`` last.

One service run is one turbo run directory (``.simplicio-loop/orchestrator/runs/<run_id>/``, the kanban's card).
The watcher opens it at ``intake``, turbo continues it (orient, plan, apply, verify; ``--run-id``, ``--leave-open``)
and the watcher closes it with ``pr`` and ``done``. While it is open, every renewal of the issue's lease is a
``lease_heartbeat`` event (``lease_beat``). Payloads carry ids, numbers and statuses only: no issue text, no secret.
Fail-open: telemetry never breaks a tick.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from .. import dashboard_events
from ..turbo_run import TurboRun
from . import state

_PR_NUMBER = re.compile(r"/pull/(\d+)")
_OPEN: dict[str, Path] = {}  # lease key -> run directory of the run open for it: where its heartbeat goes
_LOCK = threading.Lock()  # a beat is written or the run closes first, never a beat after ``run_finished``


def open_run(dest: Path, repo: str, number: int, *, fix: bool = False) -> str | None:
    """Start the run at ``intake`` and return its id, or None when the run could not be written."""
    try:
        run = TurboRun(dest, "host")
        run.enter("intake", repo=repo, issue=number, kind="fix" if fix else "issue")
        with _LOCK:
            _OPEN[state.key_of(repo, number)] = run.run_dir
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
        with _LOCK:
            for key in [key for key, run_dir in _OPEN.items() if run_dir.name == run_id]:
                del _OPEN[key]
            if pr_url and status == "ok":
                found = _PR_NUMBER.search(pr_url)
                run.enter("pr", pr_number=int(found.group(1)) if found else None)
            run.close(status)
    except Exception as exc:
        state.log(f"events: run {run_id} not closed: {exc}")


def lease_beat(key: str, status: str, *, beats: int, ttl_s: int | float) -> None:
    """Append ``lease_heartbeat`` (``renewed`` or ``lost``) to the run open for the lease ``key``; no open run, no event."""
    try:
        with _LOCK:
            run_dir = _OPEN.get(key)
            module = dashboard_events.load() if run_dir is not None else None
            if module is not None:
                module.emit_batch(run_dir, [{
                    "source": "runner", "kind": "lease_heartbeat", "severity": "info" if status == "renewed" else "warning",
                    "payload": {"lease_key": key, "status": status, "beats": beats, "ttl_s": ttl_s}}])
    except Exception as exc:
        state.log(f"events: lease beat not written {key}: {exc}")
