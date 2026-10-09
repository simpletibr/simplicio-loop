"""One turbo run on disk: ``.simplicio-loop/orchestrator/runs/<run_id>/``.

What the dashboard reads from it:
- ``state.json``: the run reader lists it (``simplicio_loop.dashboard.runs``) with the progress phase.
- ``events.jsonl``: the stage events (orient, plan, apply, verify, done) that the kanban reads, written
  through ``dashboard_events`` (fail-open, so telemetry never breaks a run).
- ``receipts/``: each dev-cli apply receipt, verbatim, with its sha256 digest.

The run's execution report is ``simplicio.execution-report/v1`` (ADR 0010), written by
``execution_report`` under ``.simplicio-loop/runtime/execution-reports/``. Tokens and hedges are
recorded only from what the provider returned; anything it did not return is null and UNVERIFIED.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import command_events, dashboard_events
from .dashboard.runs import RUN_ID_RE, write_state_file
from .execution_report import new_report, record_task, write_report
from .state_dir import ensure_state_dir

RUNS_DIR = (".simplicio-loop", "orchestrator", "runs")
# Stage -> the progress phase the kanban shows (``simplicio_loop.progress.PHASES``).
PROGRESS_PHASE = {"intake": "intake", "orient": "mapping", "plan": "planning", "apply": "executing", "verify": "validating", "pr": "delivering", "done": "done"}
CLOSED = ("done", "failed", "blocked")  # the run states close() leaves
OPERATORS = ("simplicio-mapper", "simplicio-dev-cli")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_run_id() -> str:
    return f"turbo-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{secrets.token_hex(3)}"


def _read_state(run_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def usage_totals(calls: Sequence[Mapping[str, Any]]) -> tuple[int | None, int | None]:
    """Prompt and completion tokens summed over the successful calls, or (None, None) unless every one reported usage."""
    billed = [call for call in calls if call.get("ok", True)]
    if not billed or not all(call.get("usage_reported") for call in billed):
        return None, None
    return (sum(int(call.get("prompt_tokens") or 0) for call in billed),
            sum(int(call.get("completion_tokens") or 0) for call in billed))


class TurboRun:
    """One run directory. A later invocation with the same ``run_id`` continues it (host mode: request, then apply)."""

    def __init__(self, root: Path, mode: str, run_id: str | None = None) -> None:
        if run_id is not None and not RUN_ID_RE.fullmatch(run_id):
            raise ValueError(f"run id {run_id!r} must match {RUN_ID_RE.pattern}")
        ensure_state_dir(root)
        self.root = root
        self.mode = mode
        self.run_id = run_id or _new_run_id()
        self.run_dir = root.joinpath(*RUNS_DIR, self.run_id)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        previous = _read_state(self.run_dir)
        self.started_at = str(previous.get("started_at") or _now())
        self.stage: str | None = previous.get("stage")
        self._started = time.time()
        self._report = new_report(root, execution_profile=f"turbo-{mode}")
        self._report["run_id"] = self.run_id

    # --- dashboard: state and stage events -------------------------------------------------

    def enter(self, stage: str, **payload: Any) -> None:
        """Move to ``stage``: the events the kanban draws, then the state the run reader lists.

        ``payload`` joins the phase_entered event (ids, numbers and statuses only: never issue text or secrets).
        """
        if stage == self.stage:
            return
        if self.stage is None:
            specs = [{"kind": "run_started", "phase": stage, "severity": "info", "payload": {"mode": self.mode}}]
        else:
            specs = [{"kind": "phase_exited", "phase": self.stage, "payload": {"to": stage}}]
        specs.append({"kind": "phase_entered", "phase": stage, "payload": {"from": self.stage, **payload}})
        self._emit(specs)
        self.stage = stage
        self._save("running", PROGRESS_PHASE.get(stage, stage))

    def await_plan(self) -> None:
        """The request is out and the run waits for the host's plan."""
        self._save("awaiting_plan", PROGRESS_PHASE["plan"])

    def _emit(self, specs: list[dict[str, Any]]) -> None:
        module = dashboard_events.load()
        if module is not None:
            module.emit_batch(self.run_dir, [{"source": "runner", **spec} for spec in specs])

    def _save(self, status: str, phase: str, finished_at: str | None = None) -> None:
        write_state_file({
            "run_id": self.run_id,
            "repo": str(self.root),
            "mode": self.mode,
            "status": status,
            "phase": phase,
            "stage": self.stage,
            "started_at": self.started_at,
            "updated_at": _now(),
            "finished_at": finished_at,
        }, self.run_dir / "state.json")

    # --- commands the run executes (the --verify check) ---------------------------------------

    @contextmanager
    def command(self, command: str) -> Iterator[command_events.Span]:
        """``command_started`` before the block and ``command_finished`` after it, however the block ends.

        The run is not a task, so the events are collection scope with source ``runner``. The block sets
        ``span.exit_code`` (or ``span.reason``, e.g. ``timeout``) before it ends.
        """
        with command_events.track(None, command, emit=self._emit_command) as span:
            yield span

    def _emit_command(self, kind: str, payload: dict[str, Any], severity: str) -> None:
        self._emit([{"kind": kind, "phase": self.stage, "severity": severity, "payload": payload}])

    # --- receipts ----------------------------------------------------------------------------

    def persist_receipts(self, commands: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        """Write every dev-cli apply receipt in ``commands`` under ``receipts/``; return its path and digest."""
        written = []
        for command in commands:
            receipt = command.get("receipt")
            if receipt is None:
                continue
            body = (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
            receipts_dir = self.run_dir / "receipts"
            receipts_dir.mkdir(exist_ok=True)
            path = receipts_dir / f"{command['label']}-apply.json"
            path.write_bytes(body)
            written.append({
                "label": str(command["label"]),
                "path": path.relative_to(self.root).as_posix(),
                "digest": hashlib.sha256(body).hexdigest(),
            })
        return written

    # --- end of run: stage done, execution report -------------------------------------------

    def finish(self, status: str, *, tasks: int, calls: Sequence[Mapping[str, Any]] | None = None,
               leave_open: bool = False) -> str:
        """Close the run and write its report. Returns the report path, run-relative to the repo.

        ``status`` is ``ok``, ``failed`` or ``blocked``. ``calls`` is None in host mode: the host model's calls are
        not made by turbo, so model calls, hedges and tokens are null there (UNVERIFIED), not zero.
        ``leave_open`` (an ``ok`` run only) leaves the run at its last stage for the caller to ``close``: the 24/7
        watcher still has the ``pr`` stage to write before ``done``.
        """
        if not (leave_open and status == "ok"):
            self.close(status)
        return self._write_report(status, tasks=tasks, calls=calls, finished=_now())

    def close(self, status: str) -> None:
        """The closing events (stage done, run_finished) and the final state. A run that is already closed is left as is."""
        if _read_state(self.run_dir).get("status") in CLOSED:
            return
        if self.stage != "done":
            self.enter("done")
        self._emit([{"kind": "run_finished", "phase": "done", "severity": "info" if status == "ok" else "error",
                     "payload": {"outcome": status}}])
        self._save({"ok": "done", "failed": "failed", "blocked": "blocked"}[status],
                   "done" if status == "ok" else "blocked", finished_at=_now())

    def _write_report(self, status: str, *, tasks: int, calls: Sequence[Mapping[str, Any]] | None,
                      finished: str) -> str:
        report = self._report
        span_ms = int((time.time() - self._started) * 1000)
        tokens_in, tokens_out = usage_totals(calls) if calls is not None else (None, None)
        record_task(
            report,
            task_id=self.run_id,
            title=f"turbo {self.mode}: {tasks} task(s)",
            wall_ms=span_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            outcome={"ok": "COMPLETE", "failed": "FAIL", "blocked": "BLOCKED"}[status],
            operators=list(OPERATORS),
        )
        task = report["tasks"][-1]
        task["turbo"] = {
            "mode": self.mode,
            "model_calls": None if calls is None else len(calls),
            "hedges_fired": None if calls is None else sum(1 for call in calls if call.get("hedged")),
            "wall_ms_scope": "run",
            "started_at": self.started_at,
            "finished_at": finished,
        }
        if tokens_in is None:
            report["unavailable_reasons"]["tokens_*"] = "provider returned no usage for every call (UNVERIFIED)"
        report["status"] = {"ok": "COMPLETE", "failed": "FAILED", "blocked": "BLOCKED"}[status]
        report["finished_at_unix"] = int(time.time())
        path = write_report(self.root, report)
        return path.relative_to(self.root).as_posix()

