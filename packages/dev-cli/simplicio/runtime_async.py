"""runtime_async.py — structured-concurrency runtime (issue #212).

Additive async surface layered on top of the existing synchronous pipeline.
``pipeline.run``/``pipeline.run_task`` and the CLI stay the safe bridge and
are unchanged by this module; a caller that explicitly wants to run several
INDEPENDENT tasks concurrently reaches for ``pipeline.run_tasks_async`` (or
the primitives here directly). See ``docs/architecture`` ADR for the
async-runtime decision and ``bench/run_async_pipeline_bench.py`` for the
measured concurrency win.

Design notes (why this shape, not a full async rewrite of the pipeline):

* ``run_task`` is a stateful, subprocess/git-apply-heavy synchronous
  function with module-level receipt globals. Rewriting its internals as
  native ``async def`` would touch every retry/fixer/transaction branch for
  no correctness win — the blocking work (subprocess, disk IO) still has to
  happen somewhere. Instead, independent task runs are dispatched to bounded
  worker threads (``run_sync_in_thread``), which is exactly the "encapsular
  bibliotecas bloqueantes em worker threads limitadas" step from the issue
  plan.
* Concurrency is capped by a semaphore (``RuntimeContext``), not by
  spawning one thread per task, so a large task batch cannot exhaust OS
  threads/file descriptors.
* ``asyncio.gather(..., return_exceptions=True)`` is used so one failing
  task never cancels its siblings — callers get a result list and inspect
  each entry for an exception instead of losing all in-flight work.
"""

from __future__ import annotations

import asyncio
import functools
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from .utils import http_client

T = TypeVar("T")

DEFAULT_CONCURRENCY = 4


def _resolve_concurrency(explicit: int | None) -> int:
    if explicit is not None:
        return max(1, explicit)
    raw = os.environ.get("SIMPLICIO_ASYNC_CONCURRENCY", "").strip()
    if not raw:
        return DEFAULT_CONCURRENCY
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_CONCURRENCY
    return max(1, value)


@dataclass
class RuntimeContext:
    """Per-run async scope: bounded concurrency + the shared HTTP client.

    One ``RuntimeContext`` is meant to live for the duration of a single
    ``run_tasks_async``/``gather_bounded`` call; it is not a process-wide
    singleton (the shared httpx client underneath it is).
    """

    concurrency: int = DEFAULT_CONCURRENCY
    _semaphore: asyncio.Semaphore | None = field(default=None, repr=False, compare=False)

    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.concurrency)
        return self._semaphore

    async def run_bounded(self, coro_fn: Callable[[], Awaitable[T]]) -> T:
        async with self.semaphore():
            return await coro_fn()

    async def aclose(self) -> None:
        """Release the shared async HTTP client. Safe to call repeatedly."""
        await http_client.aclose()


def install_uvloop() -> bool:
    """Opt into the ``uvloop`` event-loop policy when available.

    Returns ``False`` (never raises) on Windows or when the optional
    ``simplicio-cli[performance]`` extra is not installed — uvloop is never
    a hard dependency, the standard ``asyncio`` loop is the always-available
    fallback (issue #212 AC: "Windows funciona sem uvloop").
    """
    if os.name == "nt":
        return False
    try:
        import uvloop
    except ImportError:
        return False
    uvloop.install()
    return True


async def gather_bounded(
    thunks: Sequence[Callable[[], Awaitable[T]]],
    *,
    concurrency: int | None = None,
) -> list[T | BaseException]:
    """Run independent async thunks with bounded concurrency.

    Each entry of ``thunks`` is a no-argument callable returning an
    awaitable (e.g. ``functools.partial(fn, arg)``). Failures are captured
    per-item rather than propagated (``asyncio.gather(return_exceptions=
    True)`` semantics) so one failing task does not take down the others;
    inspect each result with ``isinstance(result, BaseException)``.
    """
    ctx = RuntimeContext(concurrency=_resolve_concurrency(concurrency))
    try:
        return await asyncio.gather(
            *(ctx.run_bounded(thunk) for thunk in thunks),
            return_exceptions=True,
        )
    finally:
        await ctx.aclose()


def run_sync_in_thread(fn: Callable[..., T], *args: Any, **kwargs: Any) -> Awaitable[T]:
    """Bridge a blocking call into the event loop via a worker thread.

    Used to dispatch the existing synchronous ``pipeline.run_task`` (and
    any other subprocess/disk-bound call) without blocking the event loop,
    per issue #212 step 5 ("encapsular bibliotecas bloqueantes em worker
    threads limitadas"). The default executor already bounds the thread
    pool size; callers layer ``RuntimeContext``'s semaphore on top for an
    explicit, configurable concurrency cap independent of the executor's own
    default sizing.
    """
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))
