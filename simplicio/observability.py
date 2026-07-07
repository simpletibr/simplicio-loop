"""Central output/logging layer + lightweight opt-in run logging (issue #106).

Two concerns live in this module:

1. **Output/logging separation** (`emit_data`/`info`/`warn`/`error`,
   `configure_logging`): the single place library code (`providers.py`,
   `pipeline.py`, `mapper.py`, `mcp_server.py`, ...) should route through
   instead of a bare `print()`. Machine-consumable payloads (JSON results,
   the thing a caller actually asked for) go to **stdout** via `emit_data`;
   human-readable status/diagnostics go to **stderr** via `info`/`warn`/
   `error`, through a `logging.Logger` so `--quiet`/`--verbose`/
   `SIMPLICIO_LOG_LEVEL` control verbosity without touching call sites.
   `simplicio.mcp_server` runs over stdio — anything written to its stdout
   that isn't a JSON-RPC frame corrupts the transport, so MCP-adjacent code
   MUST route diagnostics through `info`/`warn`/`error` (stderr), never
   `print()`. CLI *handlers* in `cli.py`/`commands/*.py`, where stdout is the
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
from pathlib import Path
from typing import Any

from .utils.serialization import dumps_str

# --------------------------------------------------------------------------- #
# Output / logging separation (#106)
# --------------------------------------------------------------------------- #

LOGGER_NAME = "simplicio"
_logger = logging.getLogger(LOGGER_NAME)
_configured = False


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
        handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(handler)
        _logger.propagate = False
        _configured = True
    _logger.setLevel(level)
    return _logger


def get_logger() -> logging.Logger:
    """Return the shared ``simplicio`` logger, configuring it if needed."""
    if not _configured:
        configure_logging()
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


def log_run(root: str, event: dict[str, Any]) -> Path | None:
    if os.environ.get("SIMPLICIO_DISABLE_RUN_LOG"):
        return None
    out = Path(root) / ".simplicio" / "runs.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": os.environ.get("SIMPLICIO_MODEL") or os.environ.get("MODEL") or "",
        "provider": os.environ.get("SIMPLICIO_PROVIDER", "claude"),
        "prompt_variant": os.environ.get("SIMPLICIO_PROMPT_VARIANT", "default"),
        **event,
    }
    with out.open("a", encoding="utf-8") as f:
        f.write(dumps_str(payload) + "\n")
    return out


SAVINGS_EVENT_SCHEMA = "simplicio.savings-event/v1"


def record_savings_event(
    root: str,
    *,
    source: str,
    baseline_tokens: int,
    actual_tokens: int,
    note: str = "",
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
    """
    if os.environ.get("SIMPLICIO_DISABLE_RUN_LOG"):
        return None
    baseline_tokens = max(0, int(baseline_tokens))
    actual_tokens = max(0, int(actual_tokens))
    saved_tokens = baseline_tokens - actual_tokens
    payload: dict[str, Any] = {
        "schema": SAVINGS_EVENT_SCHEMA,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "estimator": ESTIMATOR_LABEL,
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
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as f:
            f.write(dumps_str(payload) + "\n")
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
      line — this is diagnostic, never MCP stdout, never suppressed except
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
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("a", encoding="utf-8") as f:
                f.write(dumps_str(record) + "\n")
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
    records: list[dict[str, Any]] = []
    for line in out.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return {
        "path": str(out),
        "exists": True,
        "count": len(records),
        "recent": records[-limit:],
    }
