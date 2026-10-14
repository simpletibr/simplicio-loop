"""Deterministic OpenTelemetry-width ids: a re-export of the same run/task/event reuses the same ids."""

from __future__ import annotations

import hashlib


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def trace_id(run_id: str) -> str:
    """128-bit trace id (32 hex) for one run."""
    return _digest("trace", run_id)[:32]


def span_id(*parts: str) -> str:
    """64-bit span id (16 hex) derived from the parts that name the span."""
    return _digest("span", *parts)[:16]
