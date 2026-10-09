"""The contract of the 50 extension points (#1509): register(name, stage, fn) and run(stage, ctx).

A point is an async function ``(ctx) -> PointResult`` registered for one stage of the tick (intake, plan,
apply, verify, pr, done) from its own module ``points/<name>.py``. The tick makes ONE ``points.run(stage, ctx)``
call per stage, so adding a point never touches ``tick.py``.

* A point that raises becomes ``PointResult(status="error")``; the tick goes on. A point registered with
  ``blocking=True`` that errors or returns ``blocked`` stops the stage with ``PointBlocked`` instead. ``blocked`` is a
  FAILED ATTEMPT (the tick retries with the reasons and marks the issue dead only at the attempt limit);
  ``deferred`` is a transient condition (low disk, high load): it stops the stage with ``PointDeferred`` and the tick
  gives the attempt back, so the issue is picked up again later.
* ``applies(ctx) -> bool`` makes a point conditional: when False it is ``skipped``, never called. It may be a plain
  function (cheap, no I/O) or an ``async`` one, which the registry awaits (git, big file reads: never block the loop).
* Every result goes to the run's ``events.jsonl`` (``watcher.point``) and to the execution report
  (``simplicio.execution-report/v1``, one task per result). Emission is fail-open.

The registration order is the run order (a point is registered once, when its module is imported).
"""
from __future__ import annotations

import inspect
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ... import dashboard_events, execution_report
from .. import state

STAGES = ("intake", "plan", "apply", "verify", "pr", "done")
STATUSES = ("ok", "skipped", "error", "blocked", "deferred")
EVENT_KIND = "watcher.point"
_EVIDENCE_CAP = 300
_OUTCOME = {"ok": "COMPLETE", "skipped": "SKIPPED", "error": "FAIL", "blocked": "BLOCKED",
            "deferred": "SKIPPED"}


@dataclass(frozen=True)
class PointContext:
    """What the tick knows at a stage; fields not known yet are None (plan is None before the planner ran)."""

    repo: str
    issue: dict | None = None
    clone: Path | None = None
    state_dir: Path | None = None
    run_dir: Path | None = None
    task_text: str | None = None
    plan: Any = None
    turbo_json: dict | None = None
    verify: str | None = None
    pr_url: str | None = None
    role: str | None = None
    family: str | None = None
    capacity: Any = None  # the tick's squad_capacity.Probe; resource_governor reuses its sample instead of probing again
    test_command: str | None = None  # the repo's `verify` from loop.toml (the command turbo runs); `verify` above is the label


@dataclass(frozen=True)
class PointResult:
    name: str
    status: str
    evidence: dict = field(default_factory=dict)
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status {self.status!r} is not one of {STATUSES}")


@dataclass(frozen=True)
class PointInfo:
    """Registry metadata, for the docs table and the counts."""

    name: str
    stage: str
    blocking: bool
    conditional: bool
    module: str


class PointBlocked(Exception):
    """A stage was stopped: by a blocking point, or by a blocked result the caller refuses to go past."""

    def __init__(self, stage: str, name: str, reason_code: str, results: list[PointResult]) -> None:
        super().__init__(f"{stage} blocked by {name}: {reason_code}")
        self.stage = stage
        self.name = name
        self.reason_code = reason_code
        self.results = results

    def reasons(self) -> str:
        """The blocking result's reason_code and evidence as one line: the retry context and the status comment."""
        evidence = next((r.evidence for r in reversed(self.results) if r.name == self.name), {})
        text = f"{self.name}: {self.reason_code}"
        return text + (" " + json.dumps(evidence, sort_keys=True, default=str)[:_EVIDENCE_CAP] if evidence else "")


class PointDeferred(PointBlocked):
    """A stage was stopped by a transient condition: the tick skips the issue this round without a failed attempt."""


@dataclass(frozen=True)
class _Point:
    name: str
    stage: str
    fn: Callable[[PointContext], Awaitable[PointResult]]
    applies: Callable[[PointContext], bool | Awaitable[bool]] | None
    blocking: bool
    module: str


_POINTS: list[_Point] = []


def register(name: str, stage: str, fn: Callable[[PointContext], Awaitable[PointResult]], *,
             applies: Callable[[PointContext], bool | Awaitable[bool]] | None = None, blocking: bool = False) -> None:
    """Register one point. A name is registered once; the stage is one of STAGES; fn is async."""
    if stage not in STAGES:
        raise ValueError(f"stage {stage!r} is not one of {STAGES}")
    if blocking and stage == "done":
        raise ValueError("nothing is left to block at done")  # the claim is already released there
    if not inspect.iscoroutinefunction(fn):
        raise TypeError(f"point {name!r} must be an async function (ctx) -> PointResult")
    if any(point.name == name for point in _POINTS):
        raise ValueError(f"point {name!r} is already registered")
    _POINTS.append(_Point(name, stage, fn, applies, blocking, getattr(fn, "__module__", "")))


def registered(stage: str | None = None) -> list[PointInfo]:
    return [PointInfo(p.name, p.stage, p.blocking, p.applies is not None, p.module)
            for p in _POINTS if stage is None or p.stage == stage]


def _error(name: str, code: str, exc: BaseException) -> PointResult:
    return PointResult(name, "error", {"type": type(exc).__name__, "error": str(exc)[:_EVIDENCE_CAP]}, code)


async def _call(point: _Point, ctx: PointContext) -> PointResult:
    if point.applies is not None:
        try:
            applies = point.applies(ctx)
            if inspect.isawaitable(applies):
                applies = await applies
        except Exception as exc:
            return _error(point.name, "applies_exception", exc)
        if not applies:
            return PointResult(point.name, "skipped", {}, "not_applicable")
    try:
        result = await point.fn(ctx)
    except Exception as exc:
        return _error(point.name, "point_exception", exc)
    if not isinstance(result, PointResult):
        return PointResult(point.name, "error", {"returned": type(result).__name__}, "invalid_result")
    return result


async def run(stage: str, ctx: PointContext) -> list[PointResult]:
    """Run the points of `stage` in registration order. Never raises, except PointBlocked from a blocking point."""
    if stage not in STAGES:
        raise ValueError(f"stage {stage!r} is not one of {STAGES}")
    results: list[PointResult] = []
    stopped: PointBlocked | None = None
    report = _open_report(ctx)
    for point in [p for p in _POINTS if p.stage == stage]:
        started = time.monotonic()
        result = await _call(point, ctx)
        results.append(result)
        wall_ms = int((time.monotonic() - started) * 1000)
        _emit_event(stage, ctx, result)
        _add_task(report, stage, ctx, result, wall_ms)
        if point.blocking and result.status in ("error", "blocked", "deferred"):
            kind = PointDeferred if result.status == "deferred" else PointBlocked
            stopped = kind(stage, point.name, result.reason_code or result.status, results)
            break
    if results:
        _write_report(report, stage, ctx)
    if stopped is not None:
        raise stopped
    return results


def raise_if_blocked(stage: str, results: list[PointResult]) -> None:
    """Raise PointBlocked (or PointDeferred) for the first `blocked` (or `deferred`) result: how the PR refuses to go on."""
    for result in results:
        if result.status in ("blocked", "deferred"):
            kind = PointDeferred if result.status == "deferred" else PointBlocked
            raise kind(stage, result.name, result.reason_code or result.status, results)


# --- emission: events.jsonl and the execution report, both fail-open -----------------------------


def _emit_event(stage: str, ctx: PointContext, result: PointResult) -> None:
    if ctx.run_dir is None:
        return
    try:
        module = dashboard_events.load()
        if module is None:
            return
        Path(ctx.run_dir).mkdir(parents=True, exist_ok=True)
        module.emit_batch(Path(ctx.run_dir), [{
            "kind": EVENT_KIND, "source": "operator", "phase": stage, "scope": "collection",
            "severity": "error" if result.status == "error" else "info",
            "payload": {"point": result.name, "status": result.status, "reason_code": result.reason_code,
                        "evidence": result.evidence},
        }])
    except Exception as exc:
        state.log(f"point event failed {result.name}: {exc}")


def _report_path(ctx: PointContext) -> Path | None:
    if ctx.state_dir is None or ctx.run_dir is None:
        return None
    return Path(ctx.state_dir) / ".simplicio-loop" / "runtime" / "execution-reports" / f"{Path(ctx.run_dir).name}.json"


def _open_report(ctx: PointContext) -> dict | None:
    """The run's execution report (a later stage extends the earlier one), or None when it cannot be kept."""
    path = _report_path(ctx)
    if path is None:
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        report["_started_monotonic"] = time.monotonic() - (report.get("wall_ms") or 0) / 1000
        return report
    except (OSError, ValueError):
        pass
    try:
        report = execution_report.new_report(Path(ctx.state_dir), execution_profile="watcher-points")
    except Exception as exc:
        state.log(f"point report failed {ctx.repo}: {exc}")
        return None
    report["run_id"] = Path(ctx.run_dir).name
    return report


def _add_task(report: dict | None, stage: str, ctx: PointContext, result: PointResult, wall_ms: int) -> None:
    """One task per result in the run's execution report (written once by `_write_report`)."""
    if report is None:
        return
    try:
        issue = (ctx.issue or {}).get("number")
        execution_report.record_task(
            report, task_id=f"{stage}:{result.name}", title=f"point {result.name} @ {stage}",
            issue=None if issue is None else str(issue), wall_ms=wall_ms, outcome=_OUTCOME[result.status],
            operators=[f"point:{result.name}"])
        report["tasks"][-1].update({"stage": stage, "status": result.status, "reason_code": result.reason_code,
                                    "evidence": result.evidence})
    except Exception as exc:
        state.log(f"point report failed {result.name}: {exc}")


def _write_report(report: dict | None, stage: str, ctx: PointContext) -> None:
    if report is None:
        return
    try:
        report["status"] = "COMPLETE" if stage == "done" else "OPEN"
        if stage == "done":
            report["finished_at_unix"] = int(time.time())
        execution_report.write_report(Path(ctx.state_dir), report)
    except Exception as exc:
        state.log(f"point report write failed {stage}: {exc}")

