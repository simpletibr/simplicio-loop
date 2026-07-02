"""Lightweight opt-in run logging for benchmarks and retry loops."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .utils.serialization import dumps_str

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
            "pct_saved": round(100 * saved_tokens / baseline_tokens, 2)
            if baseline_tokens
            else 0.0,
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
