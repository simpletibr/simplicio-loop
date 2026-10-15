"""Seeded percentile bootstrap for the SWE-bench Verified table (#1819).

Algorithm (fixed, so a published interval can be re-derived byte for byte):

1. ``rng = random.Random(seed)``; only ``rng.random()`` is used (CPython guarantees that stream per seed).
2. One resample = ``n`` units drawn with replacement, unit ``int(rng.random() * n)`` per draw.
3. Every statistic is evaluated on the SAME resamples (a statistic may return ``None`` when it is
   undefined on a resample, e.g. cost per solved task with no solve; those resamples are dropped
   from that statistic and counted in ``undefined``, never filled with zero).
4. The interval is the percentile one: with the ``m`` defined values sorted ascending and
   ``alpha = 1 - confidence``, ``lo = v[floor(alpha/2 * m)]`` and ``hi = v[ceil((1 - alpha/2) * m) - 1]``.
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence

DEFAULT_RESAMPLES = 10_000
DEFAULT_CONFIDENCE = 0.95


def bootstrap(units: Sequence, stats: dict[str, Callable[[Sequence], float | None]], *, seed: int,
              resamples: int = DEFAULT_RESAMPLES, confidence: float = DEFAULT_CONFIDENCE) -> dict[str, dict]:
    if not units:
        raise ValueError("bootstrap needs at least one unit")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be strictly between 0 and 1")
    if resamples < 1:
        raise ValueError("resamples must be positive")
    units = list(units)
    n = len(units)
    rng = random.Random(seed)
    values: dict[str, list[float]] = {name: [] for name in stats}
    undefined: dict[str, int] = {name: 0 for name in stats}
    for _ in range(resamples):
        sample = [units[int(rng.random() * n)] for _ in range(n)]
        for name, fn in stats.items():
            v = fn(sample)
            if v is None:
                undefined[name] += 1
            else:
                values[name].append(v)
    alpha = 1.0 - confidence
    out: dict[str, dict] = {}
    for name, fn in stats.items():
        vals = sorted(values[name])
        m = len(vals)
        if m:
            lo = vals[math.floor(alpha / 2.0 * m)]
            hi = vals[min(m - 1, math.ceil((1.0 - alpha / 2.0) * m) - 1)]
        else:
            lo = hi = None
        out[name] = {"est": fn(units), "lo": lo, "hi": hi, "resamples": resamples, "undefined": undefined[name]}
    return out
