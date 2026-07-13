"""simplicio.context-cache/v1 — content-addressed, artifact-lazy context cache.

This module is the production lifecycle described in GitHub issue #200. It
supersedes the earlier opaque-string ``ContextCache`` with a versioned,
content-addressed design that the query path and context-pack path actually
*produce* into and *consume* from.

Two distinct cache layers are modelled explicitly (issue #200, invariant 1):

* **context-summary** — deterministic mapper outputs: selected chunks, symbol
  summaries, dependency neighbourhoods and rendered packs. The mapper owns
  these and reports their identity.
* **runtime-provider** — prompt-prefix / KV / completion reuse. The mapper
  only ever *reports* a provider reuse; it must never pretend a context hit
  is a provider hit.

Identity is content-addressed (invariant 2): a key hashes the repository
identity, the relative path set, per-file content hashes, the mapper/schema
version, the language/parser version, the query/task hash, the retrieval
policy version, the token budget and the renderer/output format. It never keys
on mtime or absolute path alone, so changing one source file invalidates only
the entries whose identity depends on that file (invariant 3).

Writes are atomic (temp file + ``os.replace``), every entry carries a checksum,
corrupt or incompatible entries are quarantined and recomputed rather than
served, and a size/age eviction bound keeps the store safe under continuous
use. A file lock serialises writers so concurrent processes cannot read a
partial blob. All of this is best-effort: any cache failure degrades to a
miss and lets the caller recompute — it never breaks the query.

Every lookup emits a structured :class:`CacheReceipt` recording
hit/miss/bypass, the key hash, the layer, the invalidation reason, the
bytes/tokens avoided, the latency avoided and whether the value was actually
*consumed* (invariant 5 / "honest evidence"). A lookup that is never consumed
is not counted as a hit.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

CONTEXT_CACHE_SCHEMA = "simplicio.context-cache/v1"
CONTEXT_CACHE_STRUCTURED_VERSION = 1

# -- Cache layers (invariant 1) ------------------------------------------------
LAYER_CONTEXT_SUMMARY = "context-summary"
LAYER_RAW_INDEX = "raw-index"
LAYER_SELECTED_CONTEXT = "selected-context"
LAYER_RENDERED_PACK = "rendered-pack"
LAYER_RUNTIME_PROVIDER = "runtime-provider"
VALID_LAYERS = (
    LAYER_CONTEXT_SUMMARY,
    LAYER_RAW_INDEX,
    LAYER_SELECTED_CONTEXT,
    LAYER_RENDERED_PACK,
    LAYER_RUNTIME_PROVIDER,
)

# Default bounds for eviction (invariant 3: bounded + safe under concurrency).
DEFAULT_MAX_ENTRIES = 2000
DEFAULT_MAX_AGE_SECONDS = 0  # 0 == disabled
DEFAULT_LOCK_TIMEOUT = 5.0

# Outcome codes emitted on every receipt.
OUTCOME_HIT = "hit"
OUTCOME_MISS = "miss"
OUTCOME_BYPASS = "bypass"
OUTCOME_INVALIDATED = "invalidated"
OUTCOME_CORRUPT = "corrupt"
OUTCOME_EVICTED = "evicted"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: str) -> str | None:
    """Return the sha256 of ``path`` or ``None`` if it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class ContextCacheKey:
    """Content-addressed identity for a cached deterministic context.

    Every field participates in the hash. Omitting a field (empty string /
    empty tuple / 0) means "not part of this request's identity" — but the
    *default* wiring always fills ``content_hashes`` so a one-byte source
    change produces a different key (invariant 3).
    """

    repo_identity: str = ""
    rel_paths: tuple[str, ...] = ()
    content_hashes: tuple[tuple[str, str], ...] = ()  # (rel_path, sha256)
    mapper_schema_version: str = ""
    parser_version: str = ""
    query_task_hash: str = ""
    retrieval_policy_version: str = ""
    token_budget: int = 0
    renderer: str = ""
    output_format: str = ""

    def canonical(self) -> dict:
        return {
            "repo_identity": self.repo_identity,
            "rel_paths": sorted(self.rel_paths),
            "content_hashes": sorted(self.content_hashes),
            "mapper_schema_version": self.mapper_schema_version,
            "parser_version": self.parser_version,
            "query_task_hash": self.query_task_hash,
            "retrieval_policy_version": self.retrieval_policy_version,
            "token_budget": int(self.token_budget),
            "renderer": self.renderer,
            "output_format": self.output_format,
        }

    def content_hash(self) -> str:
        return _sha256_text(_stable_json(self.canonical()))

    @classmethod
    def for_files(
        cls,
        root: str,
        rel_paths: Iterable[str],
        *,
        repo_identity: str = "",
        mapper_schema_version: str = "",
        parser_version: str = "",
        query_task_hash: str = "",
        retrieval_policy_version: str = "",
        token_budget: int = 0,
        renderer: str = "",
        output_format: str = "",
    ) -> ContextCacheKey:
        """Build a key by hashing the *current* content of ``rel_paths``."""
        paths = sorted(rel_paths)
        hashes = tuple((p, _sha256_file(os.path.join(root, p)) or "") for p in paths)
        return cls(
            repo_identity=repo_identity,
            rel_paths=tuple(paths),
            content_hashes=hashes,
            mapper_schema_version=mapper_schema_version,
            parser_version=parser_version,
            query_task_hash=query_task_hash,
            retrieval_policy_version=retrieval_policy_version,
            token_budget=token_budget,
            renderer=renderer,
            output_format=output_format,
        )


@dataclass
class ContextCacheEntry:
    """A persisted, checksummed cache value."""

    key_hash: str
    layer: str
    payload: Any
    checksum: str
    created_at: str = ""
    bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "key_hash": self.key_hash,
            "layer": self.layer,
            "payload": self.payload,
            "checksum": self.checksum,
            "created_at": self.created_at,
            "bytes": int(self.bytes),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ContextCacheEntry:
        return cls(
            key_hash=data.get("key_hash", ""),
            layer=data.get("layer", ""),
            payload=data.get("payload"),
            checksum=data.get("checksum", ""),
            created_at=data.get("created_at", ""),
            bytes=int(data.get("bytes", 0)),
        )

    @staticmethod
    def compute_checksum(payload: Any) -> str:
        return _sha256_text(_stable_json(payload))

    def is_valid(self) -> bool:
        return self.compute_checksum(self.payload) == self.checksum


@dataclass
class CacheReceipt:
    """Honest evidence emitted for every cache interaction (invariant 5)."""

    outcome: str  # OUTCOME_*
    key_hash: str
    layer: str
    kind: str  # "context" | "provider"
    reason: str = ""
    bytes_avoided: int = 0
    tokens_avoided: int = 0
    latency_avoided_ms: float = 0.0
    consumed: bool = False
    baseline: str = ""
    method: str = ""
    created_at: str = field(default_factory=lambda: _now_iso())

    def to_dict(self) -> dict:
        return {
            "schema": "simplicio.cache-receipt/v1",
            "outcome": self.outcome,
            "key_hash": self.key_hash,
            "layer": self.layer,
            "kind": self.kind,
            "reason": self.reason,
            "bytes_avoided": int(self.bytes_avoided),
            "tokens_avoided": int(self.tokens_avoided),
            "latency_avoided_ms": round(float(self.latency_avoided_ms), 3),
            "consumed": bool(self.consumed),
            "baseline": self.baseline,
            "method": self.method,
            "created_at": self.created_at,
        }


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


class ContextCache:
    """Content-addressed, atomic, checksummed context cache.

    Two namespaces are kept side by side in one JSON file:

    * ``entries`` — the legacy opaque-string API (``set``/``get``) retained for
      backward compatibility with existing callers/tests.
    * ``structured`` — the new content-addressed store keyed by
      ``ContextCacheKey.content_hash()``.

    All cache failures are best-effort: a load/persist error degrades to an
    empty/partial store and a query simply misses and recomputes.
    """

    def __init__(
        self,
        cache_path: str | os.PathLike,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    ) -> None:
        self.path = os.path.abspath(str(cache_path))
        self.max_entries = max(1, int(max_entries))
        self.max_age_seconds = int(max_age_seconds)
        self.lock_timeout = float(lock_timeout)
        self._entries: dict[str, Any] = {}
        self._structured: dict[str, dict] = {}  # key_hash -> entry dict
        self._quarantined: list[dict] = []
        self._receipts: list[CacheReceipt] = []
        self._last_disk_mtime_ns: int | None = None
        self._stats = {
            "lookups": 0,
            "hits": 0,
            "misses": 0,
            "bypasses": 0,
            "hits_consumed": 0,
            "bytes_avoided": 0,
            "tokens_avoided": 0,
            "latency_avoided_ms": 0.0,
            "quarantined": 0,
            "evicted": 0,
            "lock_contention": 0,
        }
        self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        self._load_from_disk(force=True)

    def _load_from_disk(self, *, force: bool = False) -> None:
        try:
            stat = os.stat(self.path)
        except OSError:
            return
        if not force and self._last_disk_mtime_ns == stat.st_mtime_ns:
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        if payload.get("schema") != CONTEXT_CACHE_SCHEMA:
            return
        self._entries = dict(payload.get("entries", {})) if isinstance(payload.get("entries"), dict) else {}
        self._structured = {}
        quarantined = (
            list(payload.get("quarantined", [])) if isinstance(payload.get("quarantined"), list) else []
        )

        structured = payload.get("structured")
        if isinstance(structured, dict) and structured.get("version") == CONTEXT_CACHE_STRUCTURED_VERSION:
            raw = structured.get("entries", {})
            if isinstance(raw, dict):
                for key_hash, entry_dict in raw.items():
                    if not isinstance(entry_dict, dict):
                        continue
                    entry = ContextCacheEntry.from_dict(entry_dict)
                    if not entry.is_valid():
                        # Corrupt entry: quarantine, never serve (invariant 3).
                        quarantined.append(self._quarantine_record(key_hash, entry, "checksum_mismatch"))
                        continue
                    self._structured[key_hash] = entry.to_dict()
        self._quarantined = quarantined[-512:]
        self._last_disk_mtime_ns = stat.st_mtime_ns

    def _lock_path(self) -> str:
        return self.path + ".lock"

    def _with_lock(self, action):
        """Run ``action`` under an exclusive file lock; degrade to in-memory
        on contention or when file locking is unavailable."""
        lock_path = self._lock_path()
        lock_fd: int | None = None
        acquired = False
        try:
            directory = os.path.dirname(lock_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            deadline = time.monotonic() + self.lock_timeout
            while True:
                try:
                    lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                    os.write(lock_fd, str(os.getpid()).encode("ascii", "ignore"))
                    acquired = True
                    break
                except FileExistsError:
                    if self._is_stale_lock(lock_path):
                        try:
                            os.unlink(lock_path)
                            continue
                        except OSError:
                            pass
                    if time.monotonic() >= deadline:
                        self._stats["lock_contention"] += 1
                        break
                    time.sleep(0.02)
            if acquired:
                self._load_from_disk(force=True)
            return action()
        finally:
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                except OSError:  # pragma: no cover
                    pass
            if acquired:
                try:
                    os.unlink(lock_path)
                except OSError:  # pragma: no cover
                    pass

    def _persist(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "schema": CONTEXT_CACHE_SCHEMA,
            "entries": self._entries,
            "structured": {
                "version": CONTEXT_CACHE_STRUCTURED_VERSION,
                "entries": self._structured,
            },
            "quarantined": self._quarantined,
        }
        tmp_fd, tmp_path = tempfile.mkstemp(dir=directory or ".", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)  # atomic swap
            self._last_disk_mtime_ns = os.stat(self.path).st_mtime_ns
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:  # pragma: no cover
                pass

    # -- legacy opaque-string API (backward compatible) ---------------------

    def get(self, key: str) -> Any | None:
        self._load_from_disk()
        return self._entries.get(key)

    def set(self, key: str, summary: Any) -> None:
        def _action() -> None:
            self._entries[key] = summary
            self._persist()

        self._with_lock(_action)

    def clear(self) -> None:
        def _action() -> None:
            self._entries = {}
            self._structured = {}
            self._quarantined = []
            self._persist()

        self._with_lock(_action)

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries) + len(self._structured)

    def keys(self, limit: int | None = None) -> list[str]:
        keys = sorted(self._entries)
        if limit is None:
            return keys
        return keys[: max(0, limit)]

    # -- content-addressed API ----------------------------------------------

    def put(
        self,
        layer: str,
        key: ContextCacheKey,
        payload: Any,
        *,
        bytes_avoided: int = 0,
        tokens_avoided: int = 0,
        latency_avoided_ms: float = 0.0,
    ) -> str:
        """Persist ``payload`` under ``layer`` + ``key`` (atomic, checksummed).

        Returns the key hash. Evicts oldest entries beyond ``max_entries``
        and entries older than ``max_age_seconds`` (when enabled).
        """
        if layer not in VALID_LAYERS:
            raise ValueError(f"unknown cache layer: {layer!r}")
        key_hash = key.content_hash()
        checksum = ContextCacheEntry.compute_checksum(payload)
        entry = ContextCacheEntry(
            key_hash=key_hash,
            layer=layer,
            payload=payload,
            checksum=checksum,
            created_at=_now_iso(),
            bytes=int(bytes_avoided) or 0,
        )

        def _action() -> None:
            self._structured[key_hash] = entry.to_dict()
            self._evict_if_needed()
            self._persist()

        self._with_lock(_action)
        return key_hash

    def get_entry(
        self,
        layer: str,
        key: ContextCacheKey,
        *,
        mark_consumed: bool = True,
        bytes_on_build: int = 0,
        tokens_on_build: int = 0,
        latency_on_build_ms: float = 0.0,
    ) -> tuple[Any | None, CacheReceipt]:
        """Return ``(payload, receipt)`` for ``layer`` + ``key``.

        On a valid hit the caller is expected to *consume* ``payload``; a hit
        that is never consumed is recorded but not counted as a consumed hit
        (acceptance criterion). On miss the caller should build the value and
        may pass ``bytes_on_build``/``tokens_on_build`` so the receipt carries
        the avoided cost of a subsequent equivalent hit.
        """
        self._stats["lookups"] += 1
        self._load_from_disk()
        key_hash = key.content_hash()

        if key_hash in self._structured:
            entry = ContextCacheEntry.from_dict(self._structured[key_hash])
            if entry.layer != layer:
                # Same key hash but a different layer — treat as a layer miss.
                receipt = self._receipt(
                    OUTCOME_MISS,
                    key_hash,
                    layer,
                    "layer_mismatch",
                    kind="context",
                )
                self._stats["misses"] += 1
                return None, receipt
            if not entry.is_valid():
                self._quarantine(key_hash, entry, "checksum_mismatch")
                receipt = self._receipt(
                    OUTCOME_CORRUPT,
                    key_hash,
                    layer,
                    "corrupt_entry_recomputed",
                    kind="context",
                )
                self._stats["misses"] += 1
                self._stats["quarantined"] += 1
                return None, receipt
            self._stats["hits"] += 1
            if mark_consumed:
                self._stats["hits_consumed"] += 1
            receipt = self._receipt(
                OUTCOME_HIT,
                key_hash,
                layer,
                "consumed" if mark_consumed else "looked_up_not_consumed",
                kind="context",
                bytes_avoided=entry.bytes,
                tokens_avoided=_estimate_tokens(_stable_json(entry.payload)),
                latency_avoided_ms=latency_on_build_ms,
                consumed=mark_consumed,
            )
            self._stats["bytes_avoided"] += receipt.bytes_avoided
            self._stats["tokens_avoided"] += receipt.tokens_avoided
            self._stats["latency_avoided_ms"] += receipt.latency_avoided_ms
            self._push_receipt(receipt)
            return entry.payload, receipt

        self._stats["misses"] += 1
        reason = "cold" if not self._structured else "no_matching_identity"
        receipt = self._receipt(OUTCOME_MISS, key_hash, layer, reason, kind="context")
        self._push_receipt(receipt)
        return None, receipt

    def explain(self, key_hash: str) -> dict:
        """Return diagnostics for ``key_hash`` without leaking payloads."""
        entry = self._structured.get(key_hash)
        quarantined = next((q for q in self._quarantined if q.get("key_hash") == key_hash), None)
        if entry is not None:
            return {
                "key_hash": key_hash,
                "present": True,
                "layer": entry.get("layer"),
                "created_at": entry.get("created_at"),
                "bytes": entry.get("bytes"),
                "checksum_valid": ContextCacheEntry.from_dict(entry).is_valid(),
            }
        if quarantined is not None:
            return {
                "key_hash": key_hash,
                "present": False,
                "quarantined": True,
                "reason": quarantined.get("reason"),
                "at": quarantined.get("at"),
            }
        return {"key_hash": key_hash, "present": False}

    def invalidate(
        self,
        *,
        layer: str | None = None,
        predicate: Callable[[str, dict], bool] | None = None,
    ) -> int:
        """Remove entries, optionally scoped by ``layer`` or ``predicate``.

        Returns the number of entries removed. Useful for targeted invalidation
        diagnostics (issue #200 step 9).
        """
        removed = 0

        def _action() -> None:
            nonlocal removed
            keep: dict[str, dict] = {}
            for key_hash, entry in self._structured.items():
                drop = False
                if layer is not None and entry.get("layer") == layer:
                    drop = True
                if not drop and predicate is not None:
                    try:
                        drop = bool(predicate(key_hash, entry))
                    except (KeyError, OSError, TypeError, ValueError):  # pragma: no cover - defensive
                        drop = False
                if drop:
                    removed += 1
                else:
                    keep[key_hash] = entry
            self._structured = keep
            if removed:
                self._persist()

        self._with_lock(_action)
        return removed

    # -- providers / receipts ------------------------------------------------

    def record_bypass(
        self,
        layer: str,
        key_hash: str,
        *,
        reason: str,
        kind: str = "provider",
        bytes_avoided: int = 0,
        tokens_avoided: int = 0,
        latency_avoided_ms: float = 0.0,
        baseline: str = "",
        method: str = "",
    ) -> CacheReceipt:
        """Record that the (native) fast path was taken instead of building
        artifacts locally. ``kind`` is ``provider`` for runtime-native reuse
        and must never be conflated with a context hit."""
        self._stats["bypasses"] += 1
        self._stats["bytes_avoided"] += int(bytes_avoided)
        self._stats["tokens_avoided"] += int(tokens_avoided)
        self._stats["latency_avoided_ms"] += float(latency_avoided_ms)
        receipt = self._receipt(
            OUTCOME_BYPASS,
            key_hash,
            layer,
            reason,
            kind=kind,
            bytes_avoided=bytes_avoided,
            tokens_avoided=tokens_avoided,
            latency_avoided_ms=latency_avoided_ms,
            baseline=baseline,
            method=method,
        )
        self._push_receipt(receipt)
        return receipt

    def _receipt(
        self,
        outcome: str,
        key_hash: str,
        layer: str,
        reason: str,
        *,
        kind: str,
        bytes_avoided: int = 0,
        tokens_avoided: int = 0,
        latency_avoided_ms: float = 0.0,
        consumed: bool = False,
        baseline: str = "",
        method: str = "",
    ) -> CacheReceipt:
        return CacheReceipt(
            outcome=outcome,
            key_hash=key_hash,
            layer=layer,
            kind=kind,
            reason=reason,
            bytes_avoided=bytes_avoided,
            tokens_avoided=tokens_avoided,
            latency_avoided_ms=latency_avoided_ms,
            consumed=consumed,
            baseline=baseline,
            method=method,
        )

    def _push_receipt(self, receipt: CacheReceipt) -> None:
        self._receipts.append(receipt)
        # Bound memory; receipts are still persisted indirectly via stats.
        if len(self._receipts) > 256:
            self._receipts = self._receipts[-256:]

    def _quarantine(self, key_hash: str, entry: ContextCacheEntry, reason: str) -> None:
        self._structured.pop(key_hash, None)
        self._quarantined.append(self._quarantine_record(key_hash, entry, reason))
        # Keep the quarantine list bounded.
        if len(self._quarantined) > 512:
            self._quarantined = self._quarantined[-512:]

    def _quarantine_record(self, key_hash: str, entry: ContextCacheEntry, reason: str) -> dict:
        return {
            "key_hash": key_hash,
            "layer": entry.layer,
            "reason": reason,
            "at": _now_iso(),
        }

    def _is_stale_lock(self, lock_path: str) -> bool:
        try:
            age = time.time() - os.path.getmtime(lock_path)
        except OSError:
            return False
        return age > max(1.0, self.lock_timeout * 2.0)

    def _evict_if_needed(self) -> None:
        if len(self._structured) <= self.max_entries:
            return
        # Evict oldest by created_at (best-effort; entries without a
        # timestamp sort first and get evicted first).
        ordered = sorted(
            self._structured.items(),
            key=lambda kv: (kv[1].get("created_at") or "", kv[0]),
        )
        excess = len(ordered) - self.max_entries
        for key_hash, _ in ordered[:excess]:
            self._structured.pop(key_hash, None)
            self._stats["evicted"] += 1
        # Age eviction (only when enabled).
        if self.max_age_seconds > 0:
            cutoff = time.time() - self.max_age_seconds
            for key_hash, entry in list(self._structured.items()):
                ts = entry.get("created_at")
                if not ts:
                    continue
                try:
                    import datetime as _dt

                    dt = _dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
                    if dt.timestamp() < cutoff:
                        self._structured.pop(key_hash, None)
                        self._stats["evicted"] += 1
                except (ValueError, OverflowError):  # pragma: no cover
                    continue

    def stats(self) -> dict:
        by_layer: dict[str, int] = {}
        for entry in self._structured.values():
            layer = entry.get("layer", "unknown")
            by_layer[layer] = by_layer.get(layer, 0) + 1
        return {
            **self._stats,
            "entries": len(self._structured),
            "legacy_entries": len(self._entries),
            "quarantined": len(self._quarantined),
            "by_layer": by_layer,
            "latency_avoided_ms": round(self._stats["latency_avoided_ms"], 3),
        }

    def receipts(self, limit: int | None = None) -> list[dict]:
        out = [r.to_dict() for r in self._receipts]
        if limit is None:
            return out
        return out[: max(0, limit)]

    def has(self, layer: str, key: ContextCacheKey) -> bool:
        self._load_from_disk()
        entry = self._structured.get(key.content_hash())
        return entry is not None and entry.get("layer") == layer


__all__ = [
    "CONTEXT_CACHE_SCHEMA",
    "CONTEXT_CACHE_STRUCTURED_VERSION",
    "LAYER_CONTEXT_SUMMARY",
    "LAYER_RAW_INDEX",
    "LAYER_SELECTED_CONTEXT",
    "LAYER_RENDERED_PACK",
    "LAYER_RUNTIME_PROVIDER",
    "VALID_LAYERS",
    "OUTCOME_HIT",
    "OUTCOME_MISS",
    "OUTCOME_BYPASS",
    "OUTCOME_INVALIDATED",
    "OUTCOME_CORRUPT",
    "OUTCOME_EVICTED",
    "ContextCacheKey",
    "ContextCacheEntry",
    "CacheReceipt",
    "ContextCache",
]
