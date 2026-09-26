"""Token-savings ledger events (issue #174, "savings por verbo").

Mirrors the shape `simplicio-dev-cli`'s `simplicio/observability.py`
(`record_savings_event`) already writes to `.simplicio-loop/ledger/savings-events.jsonl`
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
    except Exception:  # noqa: BLE001 - optional tokenizer must never block the caller
        # Ledger creation and context selection must remain available if a
        # constrained install cannot load the optional native tokenizer.
        return max(1, len(text) // 4)


def warm_estimator(*, attempts: int = 3, retry_delay_seconds: float = 1.0) -> bool:
    """Force-load the ``o200k_base`` BPE ranks once, with retries, and report success.

    ``tiktoken.get_encoding`` lazily fetches its ranks file over the network on
    first use in a process and caches it on disk (``TIKTOKEN_CACHE_DIR``, or
    ``<tempdir>/data-gym-cache`` by default) -- but that disk cache is shared,
    unguarded, machine-wide state: every process that has never loaded this
    encoding before (every fresh ``simplicio-mapper index`` subprocess this
    module's callers spawn, across an entire test suite run) independently
    races to fetch the SAME remote file the first time the cache is cold. Any
    one of those concurrent fetches that hits a transient network failure
    silently falls back to the coarser ``len(text) // 4`` heuristic inside
    ``estimate_tokens`` -- a materially different number (see
    ``docs/behavioral-scorecard.md`` / issue #199-#208's token-budget gate) --
    with no indication anything degraded. Calling this once, eagerly, before
    any budget-sensitive work starts (see
    ``scripts/evaluation_scorecard.py::main`` and
    ``tests/python/conftest.py``) populates the on-disk cache a single time so
    every later caller in this process AND every subprocess sharing the same
    default cache directory hits disk, not network, and the whole run's token
    estimates stay on the one real-tokenizer code path instead of racing.
    Returns True once the encoding loads successfully, False if every retry
    exhausted a real error (network down, no cache, tokenizer uninstallable) --
    callers decide whether that is fatal for their context.
    """
    import time

    try:
        import tiktoken
    except ImportError:
        return False
    for attempt in range(max(1, attempts)):
        try:
            tiktoken.get_encoding("o200k_base")
            return True
        except Exception:  # noqa: BLE001 - retried below; caller decides fatality
            if attempt + 1 < attempts:
                time.sleep(retry_delay_seconds)
    return False


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
    ``<root>/.simplicio-loop/ledger/savings-events.jsonl``.

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
    out = Path(root) / ".simplicio-loop" / "ledger" / "savings-events.jsonl"
    try:
        _append_jsonl(out, payload)
    except OSError:
        return None
    return out
