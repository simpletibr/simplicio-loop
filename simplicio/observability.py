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
