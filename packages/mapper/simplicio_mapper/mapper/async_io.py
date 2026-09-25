"""Bounded-concurrency async file-read primitive (ADR-009, issue #235 plan
steps 3-4, partial).

ADR-009 (``.specs/architecture/ADR-009-async-mapping-pipeline.md``) proposes
a full ``AsyncMappingPipeline`` -- a ``build_file_inventory_async`` that
replaces ``_build_file_inventory``'s walk-and-parse loop end to end, plus a
``build_artifacts_async`` composing it with the (still synchronous)
symbol-index/call-graph/write stages. That full pipeline is **not**
implemented here; it remains future work (ADR-009 "Plano de adoção" steps
5-10).

This module is the smallest safe, additive slice of that design: just the
I/O-read primitive the ADR calls out as the "textbook ``asyncio.to_thread``
candidate" (``_read_safe``/``_content_for``, ADR-009 Contexto table, "High"
priority row). It is a **pure, standalone utility** -- it does not touch
``build_artifacts``, ``_build_file_inventory``, or any CLI command. Nothing
existing calls it yet; it exists to be proven correct and benchmarked in
isolation before any wiring decision is made (ADR-009 Alternativa A: avoid
landing the full rewrite as one unreviewable diff).

Design points taken directly from the ADR:

- **Bounded concurrency, never unbounded** -- a single ``asyncio.Semaphore``
  gates in-flight reads. Default cap is ``min(64, (os.cpu_count() or 1) * 4)``,
  matching the ADR's suggested default for ``AsyncMappingPipeline``'s own
  semaphore. Every task acquires the semaphore before starting its read and
  releases it in a ``finally`` (ADR AC: "Nenhuma concorrência ilimitada ou
  task orfa").
- **Blocking I/O via ``asyncio.to_thread``** -- reuses the default
  ``ThreadPoolExecutor`` rather than introducing a second concurrency
  primitive, exactly as the ADR specifies for the eventual
  ``build_file_inventory_async``.
- **Per-file failure isolation** -- a read failure for one file (permission
  error, file deleted mid-scan, decode error) never raises out of the batch;
  it is captured as a per-file error result so a future caller decides how
  to handle partial failures, matching this module's own read helper
  (:func:`read_file_result`) rather than silently swallowing errors the way
  ``mapper.parse._read_safe`` does (that helper returns ``""`` on ``OSError``
  and is intentionally left untouched -- this module does not change it).
- **Cancellation/timeout support** -- an optional overall ``timeout``
  cancels in-flight reads cleanly via ``asyncio.wait_for`` around the
  gathering task group; cancellation propagates ``asyncio.CancelledError``
  and does not leave tasks running past the call's own return, matching the
  ADR's "Timeouts, cancellation, backpressure" section.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import time

__all__ = [
    "FileReadResult",
    "DEFAULT_MAX_CONCURRENCY",
    "default_max_concurrency",
    "read_files_concurrently",
    "read_files_concurrently_sync",
]


def default_max_concurrency() -> int:
    """Default concurrency cap: ``min(64, (os.cpu_count() or 1) * 4)``.

    Matches the sizing heuristic ADR-009 proposes for the eventual
    ``AsyncMappingPipeline`` semaphore (env var
    ``SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`` is reserved by the ADR for
    that future pipeline; this standalone helper takes an explicit
    ``max_concurrency`` parameter instead of reading env vars itself, since
    it is not yet wired to any CLI surface).
    """
    return min(64, (os.cpu_count() or 1) * 4)


# Evaluated once at import time for callers that want a constant to reference
# (e.g. defaults in docstrings/tests); ``read_files_concurrently`` itself
# recomputes via ``default_max_concurrency()`` at call time so a change to
# ``os.cpu_count()`` between calls (unlikely, but possible under container
# CPU-quota changes) is respected rather than frozen at import time.
DEFAULT_MAX_CONCURRENCY = default_max_concurrency()


@dataclasses.dataclass(frozen=True)
class FileReadResult:
    """Outcome of reading a single file.

    Exactly one of ``content``/``error`` is set (``ok`` reflects which).
    Never raises: a failed read is a normal, representable result, not an
    exception -- callers decide what "partial failure" means for their use
    case (skip, retry, record in a ``degraded`` bucket, etc.), matching the
    per-file-isolation requirement this module implements.
    """

    path: str
    content: str | None
    error: str | None
    ok: bool
    duration_s: float


def _read_sync(path: str) -> str:
    """Blocking read, run inside ``asyncio.to_thread``.

    Intentionally does not swallow ``OSError`` the way
    ``mapper.parse._read_safe`` does -- this module surfaces the error to
    the caller via :class:`FileReadResult` instead, per this task's explicit
    requirement that a per-file failure be visible, not silently coerced to
    an empty string.
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


async def _read_one(
    path: str,
    semaphore: asyncio.Semaphore,
) -> FileReadResult:
    start = time.perf_counter()
    async with semaphore:
        try:
            content = await asyncio.to_thread(_read_sync, path)
            return FileReadResult(
                path=path,
                content=content,
                error=None,
                ok=True,
                duration_s=time.perf_counter() - start,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - deliberately broad: any
            # read failure (OSError, UnicodeError, etc.) becomes a per-file
            # result rather than aborting the batch.
            return FileReadResult(
                path=path,
                content=None,
                error=f"{type(exc).__name__}: {exc}",
                ok=False,
                duration_s=time.perf_counter() - start,
            )


async def read_files_concurrently(
    paths: list[str],
    *,
    max_concurrency: int | None = None,
    timeout: float | None = None,
) -> list[FileReadResult]:
    """Read ``paths`` concurrently, bounded by ``max_concurrency`` in-flight
    reads at once, returning one :class:`FileReadResult` per input path in
    the same order as ``paths``.

    Args:
        paths: file paths to read. Duplicates are read independently (no
            implicit dedup/caching -- callers that want caching should layer
            it on top, matching ``FileProcessingCache``'s single-writer
            design being explicitly out of scope for this primitive).
        max_concurrency: maximum number of reads in flight at once. Must be
            a positive integer. Defaults to
            :func:`default_max_concurrency` (``min(64, cpu_count * 4)``)
            when omitted -- never unbounded.
        timeout: optional overall wall-clock budget in seconds. When set and
            exceeded, all in-flight reads are cancelled cleanly (no orphaned
            tasks survive this call returning/raising) and
            ``asyncio.TimeoutError`` propagates to the caller. When omitted,
            no timeout is applied.

    Returns:
        A list of :class:`FileReadResult`, positionally aligned with
        ``paths``. A failed individual read never raises -- it is
        represented as ``FileReadResult(ok=False, error=...)`` in place.

    Raises:
        ValueError: if ``max_concurrency`` is not a positive integer.
        asyncio.TimeoutError: if ``timeout`` is set and the whole batch does
            not complete within it. In-flight reads are cancelled first.
    """
    if not paths:
        return []

    cap = default_max_concurrency() if max_concurrency is None else max_concurrency
    if cap <= 0:
        raise ValueError(f"max_concurrency must be a positive integer, got {cap!r}")

    semaphore = asyncio.Semaphore(cap)

    async def _gather() -> list[FileReadResult]:
        tasks = [asyncio.ensure_future(_read_one(path, semaphore)) for path in paths]
        try:
            return await asyncio.gather(*tasks)
        except BaseException:
            # Any failure path (including our own timeout cancellation
            # below) must not leave orphaned tasks running after this
            # coroutine returns/raises.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    if timeout is None:
        return await _gather()
    return await asyncio.wait_for(_gather(), timeout=timeout)


def read_files_concurrently_sync(
    paths: list[str],
    *,
    max_concurrency: int | None = None,
    timeout: float | None = None,
) -> list[FileReadResult]:
    """Synchronous convenience wrapper around :func:`read_files_concurrently`
    for callers not already inside an event loop (e.g. quick scripts,
    benchmarks, REPL use). Uses ``asyncio.run`` -- never call this from
    inside an already-running event loop (it will raise ``RuntimeError``);
    ``await read_files_concurrently(...)`` directly in that case instead,
    matching ADR-009's "no nested ``asyncio.run()``" constraint.
    """
    return asyncio.run(
        read_files_concurrently(paths, max_concurrency=max_concurrency, timeout=timeout)
    )
