"""Pure cache-hit detection over simplicio-loop `orient`'s Mapper/Fast
generation ids -- no subprocess, no I/O.
"""
from __future__ import annotations

from typing import Optional


def is_cache_hit(previous_generation: Optional[str], current_generation: Optional[str]) -> bool:
    """True iff both generations are non-empty and identical.

    A missing generation on either side (an orient call that FALLBACK/BLOCKED
    before reaching Fast, or the very first call of a run) is never counted
    as a cache hit -- absence of a generation id is not evidence of reuse.
    """
    if not previous_generation or not current_generation:
        return False
    return previous_generation == current_generation


def extract_generations(orient_json: Optional[dict]) -> dict[str, Optional[str]]:
    """Pull the Mapper generation and Fast generation ids out of one
    `simplicio-loop orient --json` payload.

    Tolerates a FALLBACK/BLOCKED orient response that omits some or all of
    the nested ``fast`` block -- every lookup degrades to ``None`` rather
    than raising.
    """
    orient_json = orient_json or {}
    fast = orient_json.get("fast") or {}
    ingest = fast.get("ingest") or {}
    fast_receipt = ingest.get("fast_receipt") or {}
    mapper = fast_receipt.get("mapper") or {}
    return {
        "mapper_generation": mapper.get("generation"),
        "fast_generation": fast.get("generation"),
    }
