"""Central output/logging layer + lightweight opt-in run logging (issue #106).

Two concerns live in this module:

1. **Output/logging separation** (`emit_data`/`info`/`warn`/`error`,
   `configure_logging`): the single place library code (`providers.py`,
   `pipeline.py`, `mapper.py`, ...) should route through
   instead of a bare `print()`. Machine-consumable payloads (JSON results,
   the thing a caller actually asked for) go to **stdout** via `emit_data`;
   human-readable status/diagnostics go to **stderr** via `info`/`warn`/
   `error`, through a `logging.Logger` so `--quiet`/`--verbose`/
   `SIMPLICIO_LOG_LEVEL` control verbosity without touching call sites.
   Anything machine-consumable belongs on stdout and human diagnostics on
   stderr. CLI *handlers* in `cli.py`/`commands/*.py`, where stdout is the
   literal intended output of the subcommand, are the documented exception
   and may keep `print()`.
2. **Run/event logging** (`log_run`, `record_savings_event`, and — issue
   #107 — `emit_event`): opt-in JSONL producers for the token-savings ledger
   and the structured event stream a host loop (e.g. simplicio-loop's
   `loop_journal.py`) can consume.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

from .utils.serialization import dumps_str

fcntl: Any | None
try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

# --------------------------------------------------------------------------- #
# Output / logging separation (#106)
# --------------------------------------------------------------------------- #

LOGGER_NAME = "simplicio"
_logger = logging.getLogger(LOGGER_NAME)
_configured = False


def _refresh_stderr_handler_stream() -> None:
    """Keep the singleton logger bound to the current live ``sys.stderr``.

    Pytest capture and some Windows runners replace/close stderr between
    invocations. Rebinding here avoids stale/closed handles that can surface
    as ``WinError 6`` or other closed-stream logging errors.
    """
    for handler in _logger.handlers:
        if not isinstance(handler, logging.StreamHandler):
            continue
        if not getattr(handler, "_simplicio_stderr_handler", False):
            continue
        if handler.stream is sys.stderr:
            continue
        try:
            handler.setStream(sys.stderr)
        except Exception:
            handler.stream = sys.stderr


def _level_from_env() -> int:
    raw = os.environ.get("SIMPLICIO_LOG_LEVEL", "").strip().upper()
    if raw:
        level = logging.getLevelName(raw)
        if isinstance(level, int):
            return level
    return logging.INFO


def configure_logging(*, quiet: bool = False, verbose: bool = False) -> logging.Logger:
    """Configure (once) the shared ``simplicio`` logger to write to stderr.

    Precedence: explicit ``quiet``/``verbose`` args win over
    ``SIMPLICIO_LOG_LEVEL``, which wins over the ``INFO`` default.
    ``quiet`` maps to ``WARNING`` (suppress ``info``, keep ``warn``/
    ``error``); ``verbose`` maps to ``DEBUG``. Safe to call repeatedly —
    later calls just adjust the level, they never stack duplicate handlers.
    """
    global _configured
    level = _level_from_env()
    if quiet:
        level = logging.WARNING
    if verbose:
        level = logging.DEBUG

    if not _configured:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler._simplicio_stderr_handler = True
        handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(handler)
        _logger.propagate = False
        _configured = True
    else:
        _refresh_stderr_handler_stream()
    _logger.setLevel(level)
    return _logger


def get_logger() -> logging.Logger:
    """Return the shared ``simplicio`` logger, configuring it if needed."""
    if not _configured:
        configure_logging()
    else:
        _refresh_stderr_handler_stream()
    return _logger


def info(message: str, *args: Any) -> None:
    """Human-readable status line -> stderr (respects --quiet/--verbose)."""
    get_logger().info(message, *args)


def warn(message: str, *args: Any) -> None:
    """Human-readable warning -> stderr. Never suppressed by --quiet."""
    get_logger().warning(message, *args)


def error(message: str, *args: Any) -> None:
    """Human-readable error -> stderr. Never suppressed by --quiet."""
    get_logger().error(message, *args)


def emit_data(payload: Any, *, stream: Any = None) -> None:
    """Write a machine-consumable payload to stdout — the intended result.

    ``payload`` is written as-is if it is already a ``str``; otherwise it is
    JSON-serialized (via the repo's canonical ``orjson``-backed encoder).
    This is the stdout half of the output/logging split: use it for the
    actual return value of a command, never for a status/diagnostic line.
    """
    out = stream or sys.stdout
    text = payload if isinstance(payload, str) else dumps_str(payload)
    out.write(text)
    if not text.endswith("\n"):
        out.write("\n")
    out.flush()


# The single canonical token estimator for this repo (issue #88 AC4). Every
# other module that needs an approximate token count — including
# `orchestrator/cost_governor.py`, which used to run its own `chars/4`
# formula and could diverge from this one by ~30% on the same text — imports
# and calls THIS function instead of rolling its own. It is a words*4/3
# heuristic (roughly matches BPE tokenizers on English/code prose); anywhere
# it is reported, label it explicitly as "estimated" (see
# `record_savings_event` and `providers.generate`/`planner_complete`), never
# as a real provider-reported count.
ESTIMATOR_LABEL = "observability.estimate_tokens (words*4/3)"


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, len(text.split()) * 4 // 3)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except OSError:
                pass
        handle.write(dumps_str(record) + "\n")
        handle.flush()
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def log_run(root: str, event: dict[str, Any]) -> Path | None:
    if os.environ.get("SIMPLICIO_DISABLE_RUN_LOG"):
        return None
    out = Path(root) / ".simplicio" / "runs.jsonl"
    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": os.environ.get("SIMPLICIO_MODEL") or os.environ.get("MODEL") or "",
        "provider": os.environ.get("SIMPLICIO_PROVIDER", "claude"),
        "prompt_variant": os.environ.get("SIMPLICIO_PROMPT_VARIANT", "default"),
        **event,
    }
    _append_jsonl(out, payload)
    return out


SAVINGS_EVENT_SCHEMA = "simplicio.savings-event/v1"


#: Honest proof-kind labels for a `record_savings_event` figure (mirrors the
#: `proof.kind` discipline documented org-wide in simplicio-runtime's
#: `docs/SAVINGS_EVENT_SPEC.md`, applied here at the scope of this repo's
#: simpler ledger): ``"measured"`` is reserved for real provider-reported
#: usage or an aggregate over already-measured records; everything else,
#: including this module's own words*4/3 heuristic, is ``"estimated"`` and
#: must say so rather than being presented as a real number.
PROOF_KINDS = ("estimated", "measured")


def record_savings_event(
    root: str,
    *,
    source: str,
    baseline_tokens: int,
    actual_tokens: int,
    note: str = "",
    proof_kind: str = "estimated",
    extra: dict[str, Any] | None = None,
) -> Path | None:
    """Append one `simplicio.savings-event/v1` record to the shared ledger.

    Producer side of the ledger this repo has historically only hosted
    (issue #88): every module that made a measured token-saving decision
    (TOON encoding today; autoresearch template mutation, issue #90) calls
    this instead of writing ad-hoc JSONL. Written to
    `<root>/.simplicio/ledger/savings-events.jsonl`, one JSON object per
    line, honoring the same `SIMPLICIO_DISABLE_RUN_LOG` kill-switch as
    `log_run`. Fails open: a write error never raises into the caller's
    generation path.

    ``proof_kind`` (issue #111): honest label for how ``baseline_tokens``/
    ``actual_tokens`` were obtained — ``"estimated"`` (default; this is what
    every existing caller in this repo does today via `estimate_tokens`,
    recorded alongside :data:`ESTIMATOR_LABEL`) or ``"measured"`` when the
    caller has real provider-reported usage. Never claim ``"measured"``
    without an actual measurement backing it.
    """
    if os.environ.get("SIMPLICIO_DISABLE_RUN_LOG"):
        return None
    if proof_kind not in PROOF_KINDS:
        raise ValueError(f"proof_kind must be one of {PROOF_KINDS!r}, got {proof_kind!r}")
    baseline_tokens = max(0, int(baseline_tokens))
    actual_tokens = max(0, int(actual_tokens))
    saved_tokens = baseline_tokens - actual_tokens
    payload: dict[str, Any] = {
        "schema": SAVINGS_EVENT_SCHEMA,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "estimator": ESTIMATOR_LABEL,
        "proof_kind": proof_kind,
        "tokens": {
            "baseline": baseline_tokens,
            "actual": actual_tokens,
            "saved": saved_tokens,
            "pct_saved": round(100 * saved_tokens / baseline_tokens, 2) if baseline_tokens else 0.0,
        },
    }
    if note:
        payload["note"] = note
    if extra:
        payload["extra"] = extra
    out = Path(root) / ".simplicio" / "ledger" / "savings-events.jsonl"
    try:
        _append_jsonl(out, payload)
    except OSError:
        return None
    return out


# --------------------------------------------------------------------------- #
# Structured event stream for a host loop's journal (#107)
# --------------------------------------------------------------------------- #

#: Schema id for `emit_event` records. This is the CONTRACT a host loop
#: (e.g. simplicio-loop's `scripts/loop_journal.py`, an append-only JSONL
#: attempt-memory writer) reads from, not an internal implementation
#: detail — treat field names/types here as a stable public interface.
#: dev-cli does not import or depend on the loop's code; it only commits to
#: producing this shape so a loop-side reader can consume it directly.
EVENT_SCHEMA = "simplicio.dev-cli-event/v1"

#: Suggested (not exhaustive) event types. Callers may emit any short,
#: lower_snake_case `event_type` string; these are the ones this repo's own
#: producers use today, documented so a consumer can build a fixed switch
#: if it wants one, without that switch being a hard requirement.
EVENT_TYPES = (
    "task_start",
    "task_complete",
    "evidence_captured",
    "token_usage",
    "edit_applied",
    "validation_pass",
    "validation_fail",
    "handoff",
    # issue #111: one record per delegable-verb invocation (gate/nest/edit/
    # file/test-run), see `simplicio.runtime_bridge.record_delegation`.
    "native_delegation",
)

_LEVEL_FUNCS: dict[str, Any] = {"info": info, "warning": warn, "warn": warn, "error": error}


def emit_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    level: str = "info",
    root: str | None = None,
    tokens_saved: int | None = None,
) -> dict[str, Any]:
    """Emit one structured event: a human line to stderr, plus an optional
    append-only JSONL record a host loop's journal can consume.

    This is the **contract** a downstream journal reader (simplicio-loop's
    `loop_journal.py` or equivalent) should read, described here rather than
    imported from that repo — dev-cli has no dependency on simplicio-loop,
    it only commits to this shape:

    ```json
    {
      "schema": "simplicio.dev-cli-event/v1",
      "ts": "2026-07-07T00:00:00Z",
      "event": "edit_applied",
      "level": "info",
      "payload": {"...": "event-specific fields"},
      "tokens_saved": 123
    }
    ```

    - ``schema``: always :data:`EVENT_SCHEMA` — a loop-side reader can use
      this to distinguish dev-cli events from its own native journal
      records if the two streams are ever merged.
    - ``ts``: UTC, ``%Y-%m-%dT%H:%M:%SZ`` (matches `log_run`/
      `record_savings_event`).
    - ``event``: a short type string — see :data:`EVENT_TYPES` for the set
      this repo's own callers use; not a closed enum.
    - ``level``: ``"info"``, ``"warning"``, or ``"error"`` — governs which
      `simplicio.observability` stderr function renders the human line.
    - ``payload``: event-specific data, always a JSON object (``{}`` if
      omitted).
    - ``tokens_saved``: optional; a coarse heuristic estimate (see
      `estimate_tokens`), present only when the caller can compute one —
      never a substitute for the `record_savings_event` ledger, which is
      the source of truth for token-savings accounting.

    Writing is two-track, exactly like the rest of this module's
    stdout/stderr split:

     - **stderr** (always, via `info`/`warn`/`error`): a short human-readable
       line — this is diagnostic output, never suppressed except
      by the normal ``--quiet``/`SIMPLICIO_LOG_LEVEL` rules.
    - **``<root>/.simplicio/events.jsonl``** (only when *root* is given):
      the structured record above, one JSON object per line, honoring the
      same ``SIMPLICIO_DISABLE_RUN_LOG`` kill-switch as `log_run` /
      `record_savings_event`. Fails open: a write error never raises into
      the caller's path.

    Returns the record dict (useful for tests and for callers that also
    want to inspect/forward it).
    """
    payload = payload or {}
    record: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event_type,
        "level": level,
        "payload": payload,
    }
    if tokens_saved is not None:
        record["tokens_saved"] = int(tokens_saved)

    log_func = _LEVEL_FUNCS.get(level, info)
    log_func(f"[{event_type}] {dumps_str(payload)}")

    if root and not os.environ.get("SIMPLICIO_DISABLE_RUN_LOG"):
        out = Path(root) / ".simplicio" / "events.jsonl"
        try:
            max_bytes = int(os.environ.get("SIMPLICIO_EVENTS_MAX_BYTES", str(10 * 1024 * 1024)))
            try:
                if out.exists() and out.stat().st_size > max_bytes:
                    os.replace(out, out.with_suffix(".jsonl.1"))
            except OSError:
                pass
            _append_jsonl(out, record)
        except OSError:
            pass
    return record


def events_summary(root: str, *, limit: int = 5) -> dict[str, Any]:
    """Read `<root>/.simplicio/events.jsonl` and summarize it for `doctor`.

    Returns a JSON-serializable dict: ``path``, ``exists``, ``count``, and
    ``recent`` (the last *limit* records, oldest first). Tolerant of a
    missing file or a corrupt trailing line (best-effort — never raises).
    """
    out = Path(root) / ".simplicio" / "events.jsonl"
    if not out.is_file():
        return {"path": str(out), "exists": False, "count": 0, "recent": []}
    recent: deque[dict[str, Any]] = deque(maxlen=max(0, limit))
    count = 0
    with out.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            count += 1
            if limit > 0:
                recent.append(record)
    return {
        "path": str(out),
        "exists": True,
        "count": count,
        "recent": list(recent),
    }


def native_delegation_summary(root: str) -> dict[str, Any]:
    """Aggregate `native_delegation` events (issue #111) for `doctor`.

    Streams the same `<root>/.simplicio/events.jsonl` file `events_summary`
    reads, but only counts records with ``event == "native_delegation"``
    (emitted by `simplicio.runtime_bridge.record_delegation` for every
    delegable-verb invocation — ``gate``/``nest``/``edit``/``file``/
    ``test-run``), bucketed by ``payload["verb"]`` and ``payload["route"]``
    (``"native"``, ``"python-fallback"``, ``"python-forced"``).

    Returns a JSON-serializable dict: ``path``, ``exists``, ``total``
    (delegation events across every verb), ``native_pct`` (overall % routed
    to the native Rust binary), and ``verbs`` — one entry per verb with its
    own route counts and ``native_pct``. Tolerant of a missing file or a
    corrupt trailing line (best-effort — never raises).
    """
    out = Path(root) / ".simplicio" / "events.jsonl"
    if not out.is_file():
        return {"path": str(out), "exists": False, "total": 0, "native_pct": 0.0, "verbs": {}}

    per_verb: dict[str, dict[str, int]] = {}
    with out.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("event") != "native_delegation":
                continue
            payload = record.get("payload") or {}
            verb = payload.get("verb")
            route = payload.get("route")
            if not verb or not route:
                continue
            bucket = per_verb.setdefault(verb, {})
            bucket[route] = bucket.get(route, 0) + 1

    verbs_out: dict[str, Any] = {}
    total_all = 0
    native_all = 0
    for verb, counts in sorted(per_verb.items()):
        total = sum(counts.values())
        native = counts.get("native", 0)
        total_all += total
        native_all += native
        verbs_out[verb] = {
            **counts,
            "total": total,
            "native_pct": round(100 * native / total, 1) if total else 0.0,
        }

    return {
        "path": str(out),
        "exists": True,
        "total": total_all,
        "native_pct": round(100 * native_all / total_all, 1) if total_all else 0.0,
        "verbs": verbs_out,
    }
