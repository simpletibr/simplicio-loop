"""Async counterpart to ``_build_file_inventory``'s walk-and-read-and-parse
loop (ADR-009, issue #235 plan steps 4-5, partial).

``.specs/architecture/ADR-009-async-mapping-pipeline.md`` proposes an
``AsyncMappingPipeline`` design; this module implements exactly one slice of
it -- ``build_file_inventory_async``, an async replacement for
``simplicio_mapper.mapper.parse._build_file_inventory``'s per-file blocking
read, wired to the already-merged bounded-concurrency primitive in
``simplicio_mapper.mapper.async_io`` (issue #235 plan steps 3-4, PR #257).

**What changes vs. the sync path**: only the per-file disk *read*. The
directory walk (``_collect_text_files`` -> ``_walk`` -> ``os.scandir`` +
``SKIP_DIRS``/``_should_skip_dir``/``_is_internal_worktree_dir`` filtering)
is reused verbatim from ``simplicio_mapper.mapper.parse`` -- not
reimplemented -- because it is metadata-only I/O (``scandir``/``stat``), not
the "High priority" blocking-read hotspot the ADR's profiling identified.
Per-file parsing (``_language_for``, ``_sha256``, ``_parse_imports``,
``_parse_symbols``), role/importance tagging (``_roles_for``,
``_importance_for``), and the Brown-Hilbert address assignment
(``_build_brown_hilbert_map``) are the exact same functions ``parse.py``
uses -- also reused, not reimplemented, and CPU-bound parsing stays
sequential per ADR-009's explicit scoping (only I/O-bound reads get
concurrency in this step).

**Cache parity**: ``FileProcessingCache`` is consulted with the exact same
key (``rel``, ``size_bytes``, ``mtime_ns``) and semantics as
``parse._cached_parse_file``, including its subtle behavior of still
resolving file *content* (not re-parsing) on a cache hit when a shared
``contents`` dict is supplied by the caller (e.g. ``build_artifacts`` for
downstream precedent extraction). A true "skip the read" only happens when
either there is a cache hit **and** no ``contents`` dict was requested, same
as the sync path.

**Still NOT wired into any default entry point.** ``build_artifacts``,
``index``, ``scan``, and every CLI command are untouched -- this is an
opt-in, parallel code path proven correct and benchmarked in isolation, per
ADR-009 "Plano de adoção" step 6 (composing this into
``build_artifacts_async`` is separate, not-yet-implemented future work).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from ..cache import FileProcessingCache
from ..models import ProjectFile
from . import async_io
from .parse import (
    _build_brown_hilbert_map,
    _collect_text_files,
    _importance_for,
    _iso,
    _language_for,
    _normalize_rel,
    _parse_imports,
    _parse_symbols,
    _roles_for,
    _sha256,
)

__all__ = ["build_file_inventory_async", "build_file_inventory_async_sync"]


def _parse_from_text(rel: str, text: str) -> dict:
    """Same per-file parse computation as ``parse._cached_parse_file``'s
    cache-miss branch, extracted so both the cache-hit and cache-miss paths
    below can share the exact same fields/order without re-deriving them.
    """
    language = _language_for(rel, text)
    return {
        "language": language,
        "file_hash": _sha256(text),
        "imports": _parse_imports(text, language),
        "exports": _parse_symbols(text),
        "text_preview": text[:3000],
    }


async def build_file_inventory_async(
    cwd: str,
    pkg: dict,
    status_map: dict,
    cache: FileProcessingCache | None = None,
    contents: dict[str, str] | None = None,
    skipped_large_files: list[str] | None = None,
    max_concurrency: int | None = None,
) -> list[ProjectFile]:
    """Async equivalent of ``simplicio_mapper.mapper.parse._build_file_inventory``.

    Produces a **provably identical** ``list[ProjectFile]`` (same entries,
    same fields, same final sort order) for the same inputs -- this is a
    pure I/O-concurrency optimization of an existing synchronous function,
    not a behavior change. See module docstring for exactly what is reused
    vs. replaced.

    Args:
        cwd: project root, matching ``_build_file_inventory``'s ``cwd``.
        pkg: parsed ``package.json``-shaped dict, forwarded to ``_roles_for``.
        status_map: ``{rel_path: git_status}``, matching the sync path.
        cache: optional ``FileProcessingCache``, consulted/populated with
            identical keys and semantics as the sync path.
        contents: optional shared ``{rel_path: text}`` dict populated as a
            side effect, matching ``_content_for``'s write-back contract
            (used by callers that also need raw text for a later pass, e.g.
            precedent extraction).
        skipped_large_files: optional list appended with paths skipped for
            exceeding the size threshold, matching ``_collect_text_files``.
        max_concurrency: forwarded to
            ``async_io.read_files_concurrently``; ``None`` uses that
            module's bounded default (never unbounded).

    Returns:
        The same ``list[ProjectFile]``, in the same order, that
        ``_build_file_inventory(cwd, pkg, status_map, cache, contents,
        skipped_large_files)`` would return.
    """
    abs_paths = _collect_text_files(cwd, skipped=skipped_large_files)

    # Pass 1 (sync, metadata-only): stat every file and consult the cache,
    # exactly like `_cached_parse_file` does before touching file content.
    # This determines which files actually need a disk read.
    stats: dict[str, tuple[str, os.stat_result]] = {}
    cache_hits: dict[str, dict] = {}
    read_needed: list[tuple[str, str]] = []  # (abs_path, rel), in walk order

    for abs_path in abs_paths:
        rel = _normalize_rel(os.path.relpath(abs_path, cwd))
        try:
            stat = os.stat(abs_path)
        except OSError:
            continue
        stats[rel] = (abs_path, stat)

        cached = cache.get_processed_file(rel, stat.st_size, stat.st_mtime_ns) if cache else None
        if cached is not None:
            cache_hits[rel] = cached
            # Matches `_cached_parse_file`'s cache-hit branch: content is
            # still resolved (not re-parsed) when a shared `contents` dict
            # was requested and doesn't have this file yet.
            if contents is not None and rel not in contents:
                read_needed.append((abs_path, rel))
        else:
            read_needed.append((abs_path, rel))

    # Pass 2 (async, bounded concurrency): read only the files that actually
    # need it -- true cache hits with no `contents` requirement never touch
    # disk here, same as the sync path.
    read_abs_paths = [abs_path for abs_path, _rel in read_needed]
    read_results = await async_io.read_files_concurrently(
        read_abs_paths, max_concurrency=max_concurrency
    )
    text_by_rel: dict[str, str] = {}
    for (_abs_path, rel), result in zip(read_needed, read_results, strict=True):
        # `_read_safe` (the sync path's read helper) swallows OSError as
        # "", never raising -- mirror that exactly so a permission error or
        # a file deleted mid-scan degrades identically on both paths rather
        # than surfacing async_io's richer per-file error information here.
        text_by_rel[rel] = result.content if result.ok else ""

    # Pass 3 (sync, CPU-bound -- intentionally sequential per ADR-009):
    # assemble each ProjectFile from either the cache hit or a fresh parse
    # of the just-read content, then apply cache writes for misses.
    inventory: list[ProjectFile] = []
    for abs_path in abs_paths:
        rel = _normalize_rel(os.path.relpath(abs_path, cwd))
        entry_stat = stats.get(rel)
        if entry_stat is None:
            continue  # stat() failed for this file; sync path also skips it
        _abs_path, stat = entry_stat

        if rel in cache_hits:
            parsed = cache_hits[rel]
            if contents is not None and rel not in contents:
                contents[rel] = text_by_rel.get(rel, "")
        else:
            text = text_by_rel.get(rel, "")
            if contents is not None and rel not in contents:
                contents[rel] = text
            parsed = _parse_from_text(rel, text)
            if cache is not None:
                cache.set_processed_file(rel, stat.st_size, stat.st_mtime_ns, parsed)

        roles = _roles_for(rel, pkg)
        imports = list(parsed.get("imports") or [])
        exports = list(parsed.get("exports") or [])
        git_status = status_map.get(rel, "clean")
        entry = ProjectFile(
            path=rel,
            language=str(parsed.get("language") or _language_for(rel)),
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
        inventory.append(entry)

    inventory = sorted(inventory, key=lambda e: e.path)

    # Assign Brown-Hilbert addresses and agent IDs after sorting, exactly as
    # the sync path does.
    bh_map = _build_brown_hilbert_map(inventory)
    for entry in inventory:
        addr, agent = bh_map.get(entry.path, ("", ""))
        entry.bh_address = addr
        entry.agent_id = agent

    return inventory


def build_file_inventory_async_sync(
    cwd: str,
    pkg: dict,
    status_map: dict,
    cache: FileProcessingCache | None = None,
    contents: dict[str, str] | None = None,
    skipped_large_files: list[str] | None = None,
    max_concurrency: int | None = None,
) -> list[ProjectFile]:
    """Synchronous convenience wrapper around :func:`build_file_inventory_async`
    for callers not already inside an event loop, matching
    ``async_io.read_files_concurrently_sync``'s pattern. Uses ``asyncio.run``
    -- never call this from inside an already-running event loop (it will
    raise ``RuntimeError``); ``await build_file_inventory_async(...)``
    directly in that case instead.
    """
    return asyncio.run(
        build_file_inventory_async(
            cwd,
            pkg,
            status_map,
            cache=cache,
            contents=contents,
            skipped_large_files=skipped_large_files,
            max_concurrency=max_concurrency,
        )
    )
