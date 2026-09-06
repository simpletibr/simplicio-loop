"""Async replacement for the file-inventory walk-and-parse stage of
``build_artifacts`` (issue #235, plan steps 4-6; design in
``.specs/architecture/ADR-009-async-mapping-pipeline.md``).

This module intentionally does not touch the CPU-bound, already-fast
symbol-index/call-graph/write stages (ADR-009's own profiling found the
real bottleneck there is the quadratic ``_candidate_import_targets``
fallback scan in ``graph.py``, a separate, non-concurrency fix) -- only the
walk-and-read-and-parse loop that previously ran as a single blocking
``for`` loop (``simplicio_mapper.mapper.parse._build_file_inventory``) is
made concurrent here, bounded by a single semaphore, with blocking I/O
moved off the event loop via ``asyncio.to_thread``.

``build_artifacts_async`` composes the async inventory step with the rest
of the (still synchronous) pipeline -- symbol index, call graph,
architecture inventory, single-writer JSON emission stays exactly as it is
today, per ADR-009's "single writer, preserved" requirement.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any

from ..cache import FileProcessingCache
from ..models import ProjectFile
from .graph import (
    _build_architecture_inventory,
    _build_call_graph,
    _build_symbol_index,
    _collect_architecture_signals,
)
from .memory_budget import MemoryBudget, MemoryBudgetExceeded
from .parse import (
    ARTIFACT_SCHEMA,
    ARTIFACT_VERSION,
    LLM_DIRECTIVES,
    PRECEDENT_SCHEMA,
    _build_brown_hilbert_map,
    _build_precedent_items,
    _cached_parse_file,
    _collect_entities,
    _collect_text_files,
    _detect_changed_files,
    _git_status_map,
    _group_modules,
    _importance_for,
    _iso,
    _load_previous_map,
    _normalize_rel,
    _now_iso,
    _parse_json_safe,
    _roles_for,
)

#: Default per-file timeout, in seconds -- generous enough that a normal
#: source file (even a large one under the existing 250KB skip threshold)
#: never trips it under ordinary disk I/O, while still bounding a hung
#: read (e.g. a stalled network filesystem) so it cannot stall the whole
#: run. Tunable via ``SIMPLICIO_MAPPER_FILE_TIMEOUT_S`` for tests and for
#: unusually slow environments.
_DEFAULT_FILE_TIMEOUT_S = 30.0

_MAX_CONCURRENT_ENV = "SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES"
_FILE_TIMEOUT_ENV = "SIMPLICIO_MAPPER_FILE_TIMEOUT_S"
_BATCH_SIZE_ENV = "SIMPLICIO_MAPPER_ASYNC_BATCH_SIZE"
_BATCH_FACTOR_ENV = "SIMPLICIO_MAPPER_ASYNC_BATCH_FACTOR"
_MEMORY_HARD_LIMIT_ENV = "SIMPLICIO_MAPPER_MEMORY_HARD_LIMIT_BYTES"


def _max_concurrent_files() -> int:
    """Bounded-concurrency cap for in-flight file read+parse tasks.

    Default ``min(64, os.cpu_count() * 4)`` (ADR-009), tunable via
    ``SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES`` for benchmarking/tests. Any
    non-positive or non-integer override is ignored in favor of the
    default rather than silently producing an unbounded/zero semaphore.
    """
    override = os.environ.get(_MAX_CONCURRENT_ENV)
    if override:
        try:
            value = int(override)
        except ValueError:
            value = 0
        if value > 0:
            return value
    cpu_count = os.cpu_count() or 4
    return min(64, cpu_count * 4)


def _per_file_timeout_s() -> float:
    override = os.environ.get(_FILE_TIMEOUT_ENV)
    if override:
        try:
            value = float(override)
        except ValueError:
            value = 0.0
        if value > 0:
            return value
    return _DEFAULT_FILE_TIMEOUT_S


def _async_batch_size() -> int:
    override = os.environ.get(_BATCH_SIZE_ENV)
    if override:
        try:
            value = int(override)
        except ValueError:
            value = 0
        if value > 0:
            return min(value, 1024)
    return 16


def _async_batch_factor() -> int:
    override = os.environ.get(_BATCH_FACTOR_ENV)
    if override:
        try:
            value = int(override)
        except ValueError:
            value = 0
        if value > 0:
            return min(value, 32)
    return 4


def _memory_budget_from_env() -> MemoryBudget | None:
    raw = os.environ.get(_MEMORY_HARD_LIMIT_ENV, "").strip()
    if not raw:
        return None
    try:
        hard = int(raw)
    except ValueError:
        return None
    if hard <= 0:
        return None
    return MemoryBudget(soft_limit_bytes=max(1, int(hard * 0.8)), hard_limit_bytes=hard)


def _install_uvloop_if_available() -> bool:
    """Install ``uvloop``'s event-loop policy when available.

    Linux/macOS only (``sys.platform != "win32"``), lazy import, never a
    hard dependency: any import failure (not installed, or -- as upstream
    documents -- unsupported platform) leaves the stdlib ``asyncio`` event
    loop in place, exactly as today. Returns ``True`` when uvloop's policy
    was installed, ``False`` otherwise, so callers/tests can assert on the
    outcome without inspecting global interpreter state directly.
    """
    if sys.platform == "win32":
        return False
    try:
        import uvloop
    except ImportError:
        return False
    try:
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except AttributeError:  # pragma: no cover - defensive, older uvloop API
        uvloop.install()
    return True


async def _process_one_file(
    cwd: str,
    pkg: dict,
    status_map: dict,
    cache: FileProcessingCache | None,
    contents: dict[str, str] | None,
    timeout_s: float,
    abs_path: str,
    timed_out: list[str],
    quarantined: list[dict[str, str]],
) -> ProjectFile | None:
    """Read+parse a single file under the bounded semaphore.

    Mirrors ``parse._build_file_inventory``'s per-file body exactly (same
    ``ProjectFile`` construction, same field derivation order) so the
    async and sync paths produce structurally identical output. On a
    per-file timeout, fails soft: the file is recorded in ``timed_out``
    (surfaced by the caller as a ``degraded`` entry, matching the existing
    large-file-skip pattern) and dropped from the inventory rather than
    aborting the whole run.

    Task quarantine (issue #279 step 13): a genuine parse/read failure that
    is *not* a timeout -- e.g. a corrupted file, a mid-read permission
    error, a decode failure the file-level ``_read_safe`` guard did not
    anticipate -- previously propagated straight out of this task, through
    ``asyncio.gather`` in ``build_file_inventory_async``, and crashed the
    *entire* run (every other file's already-computed result discarded)
    for a single bad file. That single file is now quarantined instead:
    recorded in ``quarantined`` with its path and the error, dropped from
    the inventory, and the run continues for every other file -- the same
    fail-soft shape the timeout path already had, extended to cover
    non-timeout exceptions too. ``asyncio.CancelledError`` (a
    ``BaseException``, not ``Exception``) is deliberately not caught here
    and continues to propagate so external cancellation (see
    ``CancellationTest``) is unaffected by this change.

    ``contents`` is a single dict shared across every in-flight file task;
    each task only ever writes its own ``rel`` key (paths are unique per
    file in ``_collect_text_files``'s output), so concurrent writes never
    target the same key. CPython's GIL makes each individual
    ``dict.__setitem__``/``__contains__`` atomic, and since nothing reads
    the dict as a whole (only per-key access) until every task has been
    awaited, this is safe without a separate lock.
    """
    rel = _normalize_rel(os.path.relpath(abs_path, cwd))
    try:
        try:
            stat = await asyncio.to_thread(os.stat, abs_path)
        except OSError:
            return None

        def _parse_and_release_thread_local_connection() -> dict:
            # `FileProcessingCache`/diskcache opens one SQLite connection
            # per *thread* the first time it is touched (`threading.local`
            # under the hood) and only ever closes it if `close()` is
            # called from that exact same thread -- it has no `__del__`
            # finalizer. Worker threads here come from asyncio's shared,
            # reused default executor, so leaving that per-thread
            # connection open would leak a file handle for the lifetime of
            # the whole process (observable on Windows as a "file still in
            # use" error the moment a caller tries to remove the
            # `.simplicio/cache` directory right after this run). Closing
            # it explicitly, from the same worker thread, right after this
            # one file's cache access, keeps every SQLite handle
            # short-lived regardless of thread-pool reuse or GC timing.
            result = _cached_parse_file(cwd, abs_path, rel, stat, cache, contents)
            if cache is not None:
                cache.close()
            return result

        try:
            parsed = await asyncio.wait_for(
                asyncio.to_thread(_parse_and_release_thread_local_connection),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            # Known asyncio.to_thread limitation (documented in ADR-009):
            # cancelling the wait_for() cancels *our* await, not the
            # underlying OS thread, which may keep running until its
            # current blocking syscall returns. We do not block the
            # pipeline waiting for it either way -- fail soft and move on.
            timed_out.append(rel)
            return None
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: quarantine, never crash the whole run for one bad file (issue #279 step 13)
            quarantined.append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})
            return None
    except BaseException:
        raise
    roles = _roles_for(rel, pkg)
    imports = list(parsed.get("imports") or [])
    exports = list(parsed.get("exports") or [])
    git_status = status_map.get(rel, "clean")
    entry = ProjectFile(
        path=rel,
        language=str(parsed.get("language") or ""),
        size_bytes=stat.st_size,
        last_modified=_iso(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)),
        file_hash=str(parsed.get("file_hash") or ""),
        git_status=git_status,
        roles=roles,
        imports=imports,
        exports=exports,
        text_preview=str(parsed.get("text_preview") or ""),
    )
    entry.importance = _importance_for(entry.roles, entry.imports, entry.exports, entry.git_status)
    return entry


async def build_file_inventory_async(
    cwd: str,
    pkg: dict,
    status_map: dict,
    cache: FileProcessingCache | None = None,
    contents: dict[str, str] | None = None,
    skipped_large_files: list[str] | None = None,
    *,
    max_concurrent: int | None = None,
    timeout_s: float | None = None,
    degraded: dict[str, Any] | None = None,
    memory_budget: MemoryBudget | None = None,
) -> list[ProjectFile]:
    """Async replacement for ``parse._build_file_inventory``'s walk-and-parse
    loop (ADR-009 plan steps 4-5).

    Structurally equivalent to the sync version: same ``ProjectFile`` list
    contents, same final sort order (by ``path``), same Brown-Hilbert
    address assignment pass after sorting. Work is fed through a bounded
    queue of batches to a fixed worker set, so task creation is O(workers),
    never O(files).

    ``degraded`` (when provided) receives two independent fail-soft
    diagnostics, mirroring the existing ``skipped_large_files`` pattern:
    ``degraded["timed_out_files"]`` (a per-file timeout, see
    ``_DEFAULT_FILE_TIMEOUT_S``) and ``degraded["quarantined_files"]`` (a
    list of ``{"path", "error"}`` entries for files whose read/parse raised
    an exception other than a timeout -- issue #279 step 13's "task
    quarantine"). Either category drops the affected file from the
    returned inventory but never aborts the run for the other files.
    """
    workers = max_concurrent or _max_concurrent_files()
    batch_size = _async_batch_size()
    queue_capacity = max(1, workers * _async_batch_factor())
    work_queue: asyncio.Queue[list[str] | None] = asyncio.Queue(maxsize=queue_capacity)
    timeout = timeout_s if timeout_s is not None else _per_file_timeout_s()
    timed_out: list[str] = []
    quarantined: list[dict[str, str]] = []
    queue_depth_peak = 0
    backpressure_events = 0

    abs_paths = await asyncio.to_thread(_collect_text_files, cwd, skipped_large_files)
    reserved_by_path: dict[str, int] = {}
    if memory_budget is not None:
        eligible_paths: list[str] = []
        for abs_path in abs_paths:
            try:
                size_bytes = os.path.getsize(abs_path)
                memory_budget.reserve(size_bytes)
            except (OSError, MemoryBudgetExceeded) as exc:
                if degraded is not None:
                    degraded.setdefault("memory_budget_exceeded", []).append({
                        "path": _normalize_rel(os.path.relpath(abs_path, cwd)),
                        "error": str(exc),
                    })
                continue
            reserved_by_path[abs_path] = size_bytes
            eligible_paths.append(abs_path)
        abs_paths = eligible_paths

    results: list[ProjectFile] = []
    async def _worker() -> None:
        while True:
            batch = await work_queue.get()
            try:
                if batch is None:
                    return
                for abs_path in batch:
                    try:
                        entry = await _process_one_file(
                            cwd, pkg, status_map, cache, contents, timeout,
                            abs_path, timed_out, quarantined,
                        )
                    finally:
                        reserved = reserved_by_path.get(abs_path, 0)
                        if memory_budget is not None and reserved and contents is None:
                            memory_budget.release(reserved)
                    if entry is not None:
                        results.append(entry)
            finally:
                work_queue.task_done()

    tasks = [asyncio.create_task(_worker()) for _ in range(workers)]
    try:
        for offset in range(0, len(abs_paths), batch_size):
            if work_queue.full():
                backpressure_events += 1
            await work_queue.put(abs_paths[offset : offset + batch_size])
            queue_depth_peak = max(queue_depth_peak, work_queue.qsize())
        for _ in tasks:
            await work_queue.put(None)
        await work_queue.join()
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    inventory = sorted(results, key=lambda entry: entry.path)

    bh_map = _build_brown_hilbert_map(inventory)
    for entry in inventory:
        addr, agent = bh_map.get(entry.path, ("", ""))
        entry.bh_address = addr
        entry.agent_id = agent

    if degraded is not None and timed_out:
        degraded["timed_out_files"] = sorted(timed_out)
    if degraded is not None and quarantined:
        degraded["quarantined_files"] = sorted(quarantined, key=lambda entry: entry["path"])
    if degraded is not None:
        degraded["async_pipeline"] = {
            "workers": workers,
            "batch_size": batch_size,
            "queue_capacity": queue_capacity,
            "tasks_created": len(tasks),
            "batches_submitted": (len(abs_paths) + batch_size - 1) // batch_size,
            "max_live_tasks": len(tasks),
            "queue_depth_peak": queue_depth_peak,
            "backpressure_events": backpressure_events,
        }

    return inventory

async def build_artifacts_async(
    cwd: str,
    meta: dict | None = None,
    incremental: bool = False,
    output_dir: str = ".simplicio",
) -> dict:
    """Full async pipeline entry point (ADR-009 plan step 6).

    Native ``async def``, never nests its own ``asyncio.run()`` -- callers
    already inside an event loop can ``await`` this directly. Composes the
    async file-inventory stage (bounded concurrency, ``to_thread`` I/O)
    with the rest of the pipeline (symbol index, call graph, architecture
    inventory), which stays synchronous/CPU-bound exactly as it is in
    ``emit.build_artifacts`` today -- the single JSON writer is untouched
    (writes happen in ``emit.write_mapping_artifacts``, sequentially,
    after this coroutine returns).
    """
    # Local import: `.emit` imports `build_artifacts_async` from this
    # module (for the sync adapter) only inside its own function body, so
    # this top-level module never imports `.emit` at import time -- this
    # deferred import here mirrors that to keep the dependency direction
    # a call-time-only cycle, not a module-load-time one.
    from .canonical_artifacts import attach_canonical_metadata
    from .emit import _build_agent_tree

    meta = meta or {}
    abs_cwd = os.path.abspath(cwd or os.getcwd())
    abs_out = os.path.abspath(os.path.join(abs_cwd, output_dir))
    pkg = await asyncio.to_thread(_parse_json_safe, os.path.join(abs_cwd, "package.json"))
    contents: dict[str, str] = {}
    memory_budget = _memory_budget_from_env()
    skipped_large_files: list[str] = []
    degraded: dict[str, Any] = {
        "git_timeout": False,
        "git_status_unavailable": False,
        "skipped_large_files": [],
        "large_file_limit_bytes": 250000,
    }
    status_map = await asyncio.to_thread(_git_status_map, abs_cwd, degraded)
    previous_map = await asyncio.to_thread(_load_previous_map, abs_out)
    cache_dir = os.path.join(abs_out, "cache")

    file_cache = FileProcessingCache(cache_dir)
    try:
        files = await build_file_inventory_async(
            abs_cwd,
            pkg,
            status_map,
            file_cache,
            contents=contents,
            skipped_large_files=skipped_large_files,
            degraded=degraded,
            memory_budget=memory_budget,
        )
    finally:
        # Deliberately synchronous, not `to_thread`-wrapped: `close()` is
        # cheap and closing the SQLite-backed diskcache handle from the
        # same thread that created it (this coroutine's own thread) avoids
        # cross-thread file-handle release timing quirks observed on
        # Windows when the close was moved to a worker thread.
        file_cache.close()

    degraded["skipped_large_files"] = sorted(skipped_large_files)
    pipeline_metrics = degraded.pop("async_pipeline", None)
    file_entries = [file.to_dict() for file in files]
    corpus = "\n".join(file.text_preview for file in files[:80])
    changed_files = _detect_changed_files(files, previous_map, status_map, incremental)
    stack = meta.get("stack") or pkg.get("type") or "unknown"
    product_name = meta.get("product_name") or pkg.get("name") or os.path.basename(abs_cwd)
    architecture_signals = _collect_architecture_signals(pkg, corpus, stack)
    generated_at = _now_iso()

    if os.path.exists(os.path.join(abs_cwd, "pnpm-lock.yaml")):
        package_manager = "pnpm"
    elif os.path.exists(os.path.join(abs_cwd, "yarn.lock")):
        package_manager = "yarn"
    else:
        package_manager = "npm"

    web_signal = "react" in architecture_signals or "nextjs" in architecture_signals
    if meta.get("project_mode") == "monorepo":
        system_type = "monorepo"
    else:
        system_type = "web" if web_signal else "library-or-service"

    project_map = {
        "schema": ARTIFACT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "update_mode": "incremental" if incremental else "full",
        "product": {
            "name": product_name,
            "stack": stack,
            "project_mode": meta.get("project_mode", "root"),
        },
        "files": file_entries,
        "entry_points": [f.path for f in files if "entrypoint" in f.roles],
        "test_files": [f.path for f in files if "test" in f.roles],
        "config_files": [f.path for f in files if "config" in f.roles],
        "modules": _group_modules(files),
        "entities": _collect_entities(files),
        "architecture": {
            "signals": architecture_signals,
            "system_type": system_type,
        },
        "dependencies": {
            "package_manager": package_manager,
            "manifest": "package.json" if pkg.get("name") else None,
            "runtime": sorted((pkg.get("dependencies") or {}).keys()),
            "dev": sorted((pkg.get("devDependencies") or {}).keys()),
        },
        "recent_changes": [
            {"path": file, "status": status_map.get(file, "modified")} for file in changed_files
        ],
        "changed_files": changed_files,
        "integration": {
            "dev_cli_mapper": "read .simplicio/project-map.json, then use .simplicio/precedent-index.json for task-specific examples",
            "contract": "SIMPLICIO_INTEGRATION.md",
            "llm_directives": LLM_DIRECTIVES,
        },
        "degraded": degraded,
    }

    precedent_index = {
        "schema": PRECEDENT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "source_project_map": ".simplicio/project-map.json",
        "items": _build_precedent_items(abs_cwd, files, contents=contents),
    }

    symbol_index = _build_symbol_index(abs_cwd, files, generated_at, contents=contents)
    call_graph = _build_call_graph(abs_cwd, files, symbol_index, generated_at, contents=contents)
    architecture_inventory = _build_architecture_inventory(
        abs_cwd,
        project_map,
        files,
        symbol_index,
        call_graph,
        generated_at,
    )

    bh_map = _build_brown_hilbert_map(files)
    agent_tree = _build_agent_tree(files, bh_map)

    project_map["agent_tree"] = agent_tree
    contents.clear()
    if memory_budget is not None and memory_budget.current_bytes:
        memory_budget.release(memory_budget.current_bytes)
        pipeline_metrics = dict(pipeline_metrics or {})
        pipeline_metrics["memory_budget"] = memory_budget.receipt()

    artifacts = {
        "project_map": project_map,
        "precedent_index": precedent_index,
        "architecture_inventory": architecture_inventory,
        "symbol_index": symbol_index,
        "call_graph": call_graph,
        "async_pipeline_metrics": pipeline_metrics,
    }
    public_artifacts = {
        key: artifacts[key]
        for key in ("project_map", "precedent_index", "architecture_inventory", "symbol_index", "call_graph")
    }
    attach_canonical_metadata(abs_cwd, public_artifacts, degraded=degraded)
    return artifacts
