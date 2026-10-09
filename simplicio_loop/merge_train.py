"""Merge train: integrate approved PRs in batches, test once, bisect on red (#1504, part of #1502).

Pure orchestration over injected callables, so it is testable without git or gh:

* ``test_fn(prs) -> bool | Awaitable[bool]``: integrate ``prs`` (in order) on a temporary branch
  and run the smoke once. Never force-push; the temporary branch is the caller's.
* ``merge_fn(pr) -> None | Awaitable[None]``: merge one PR into main.

Green batch: merge all, in order, with no further smoke. Red batch: find the first PR whose
prefix turns the batch red (binary search, log2(n) tests), mark it failed, then test the rest ON TOP
OF the good prefix and repeat if it is red. Every test is cumulative (good so far + candidate chunk),
so the final merged set was itself tested green as one integration. Nothing is merged until isolation
finishes; then only the good PRs are merged, in order.
"""

from __future__ import annotations

import inspect
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Hashable, Sequence

DEFAULT_MAX_BATCH = 4


@dataclass
class TrainReport:
    merged: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    bisect_steps: int = 0  # test_fn calls after the initial full-batch test
    wall_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_train(approved_prs: Sequence[Hashable], order: Sequence[Hashable], max_batch: int = DEFAULT_MAX_BATCH) -> list[list]:
    """Batches of at most ``max_batch`` approved PRs, following ``order``; PRs missing from it go last."""
    if max_batch < 1:
        raise ValueError("max_batch must be >= 1")
    rank = {pr: i for i, pr in enumerate(order)}
    ordered = sorted(approved_prs, key=lambda pr: rank.get(pr, len(rank)))  # stable
    return [ordered[i : i + max_batch] for i in range(0, len(ordered), max_batch)]


async def _call(fn: Callable[..., Any], *args: Any) -> Any:
    out = fn(*args)
    return await out if inspect.isawaitable(out) else out


async def run_train(batch: Sequence[Hashable], test_fn: Callable[..., Any], merge_fn: Callable[..., Any]) -> TrainReport:
    start = time.monotonic()
    report = TrainReport()
    prs = list(batch)
    good: list = []  # invariant: always tested green as one integration (or empty)
    if prs:
        pending, known_red = prs, not await _call(test_fn, prs)
        while pending:
            if not known_red:
                good.extend(pending)
                break
            # Smallest k such that good + pending[:k] is red; good + pending[:k-1] is green (tested) or == good.
            lo, hi = 1, len(pending)
            while lo < hi:
                mid = (lo + hi) // 2
                report.bisect_steps += 1
                if await _call(test_fn, good + pending[:mid]):
                    lo = mid + 1
                else:
                    hi = mid
            good.extend(pending[: lo - 1])
            report.failed.append(pending[lo - 1])
            pending = pending[lo:]
            if pending:
                report.bisect_steps += 1
                known_red = not await _call(test_fn, good + pending)
    for pr in good:
        await _call(merge_fn, pr)
        report.merged.append(pr)
    report.wall_ms = (time.monotonic() - start) * 1000.0
    return report
