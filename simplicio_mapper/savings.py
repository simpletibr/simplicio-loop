"""Token-savings ledger events (issue #174, "savings por verbo").

Mirrors the shape `simplicio-dev-cli`'s `simplicio/observability.py`
(`record_savings_event`) already writes to `.simplicio/ledger/savings-events.jsonl`
-- read as a format reference only, no code imported from that repo. Every
native-delegation decision in `simplicio_mapper.query` that actually took the
native (Rust runtime) fast path instead of the local Python computation
records one event here, so the token savings from delegating a verb are a
real, inspectable ledger instead of an unverifiable claim.

Emits ``simplicio.savings-event/v1``, the same schema id documented in
CLAUDE.md's "Token savings report" standing rule and
`docs/SAVINGS_EVENT_SPEC.md` upstream in ``simplicio-runtime``. Fields:

  - ``schema`` -- ``"simplicio.savings-event/v1"``.
  - ``ts`` -- UTC ISO-8601 timestamp.
  - ``source`` -- ``"native-delegation:<verb>"`` (e.g. ``"native-delegation:impact"``).
  - ``estimator`` -- the token-count method used (never presented unlabeled).
  - ``proof_kind`` -- ``"measured"`` only for real provider-reported token
    counts; ``"estimated"`` (with the estimator declared) otherwise. This
    module only ever produces ``"estimated"`` figures -- no real LLM call is
    made to measure token spend here -- and always states that explicitly.
  - ``tokens`` -- ``{baseline, actual, saved, pct_saved}``.
  - ``note`` -- optional human-readable baseline methodology.
  - ``extra`` -- optional structured extra fields (kept small).

Fails open: a write error never raises into the caller's query path (same
contract as the dev-cli reference implementation), and honors the same
``SIMPLICIO_DISABLE_RUN_LOG`` kill-switch used across the ecosystem's other
JSONL producers so a single opt-out disables every ledger writer at once.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

SAVINGS_EVENT_SCHEMA = "simplicio.savings-event/v1"

#: Local BPE estimate. Provider usage remains the only ``measured`` source;
#: this label makes the locally computed metric explicit in every receipt.
ESTIMATOR_LABEL = "tiktoken:o200k_base"

_DISABLE_ENV = "SIMPLICIO_DISABLE_RUN_LOG"


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    try:
        import tiktoken

        return len(tiktoken.get_encoding("o200k_base").encode(text, disallowed_special=()))
    except Exception:
        # Ledger creation and context selection must remain available if a
        # constrained install cannot load the optional native tokenizer.
        return max(1, len(text) // 4)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def record_savings_event(
    root: str,
    *,
    source: str,
    baseline_tokens: int,
    actual_tokens: int,
    proof_kind: str = "estimated",
    note: str = "",
    extra: dict[str, Any] | None = None,
) -> Path | None:
    """Append one ``simplicio.savings-event/v1`` record to
    ``<root>/.simplicio/ledger/savings-events.jsonl``.

    Returns the path written to, or ``None`` if the ledger is disabled
    (``SIMPLICIO_DISABLE_RUN_LOG``) or the write failed (fails open --
    never raises into the caller's query path).
    """
    if os.environ.get(_DISABLE_ENV):
        return None
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
