"""simplicio.context-cache/v1 — file-backed summary cache keyed by hash.

The mapper context pack is the source of compact context; the context
cache lets downstream LLM planners reuse summaries for unchanged files
without re-summarizing them. Entries are keyed by a content hash
(`snapshot_hash` of a file, the `range_hash` of a slice, or the
`pack_hash` of a whole context pack) so a change underneath naturally
invalidates the cached summary.

The cache is intentionally small and JSON-backed: it is persisted under
`.simplicio/context-cache.json` by default and is safe to ship across
machines.
"""

from __future__ import annotations

import json
import os
from typing import Any

CONTEXT_CACHE_SCHEMA = "simplicio.context-cache/v1"


class ContextCache:
    """Hash-keyed cache for LLM summaries.

    `key` is any opaque string the caller chose (typically a content hash
    derived by the mapper). `summary` is any JSON-serialisable payload.
    Reads return `None` on miss; writes are persisted immediately so
    multiple processes pick up the latest value on their next load.
    """

    def __init__(self, cache_path: str | os.PathLike) -> None:
        self.path = str(cache_path)
        self._entries: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return {}
        if not isinstance(payload, dict):
            return {}
        if payload.get("schema") != CONTEXT_CACHE_SCHEMA:
            return {}
        entries = payload.get("entries", {})
        return dict(entries) if isinstance(entries, dict) else {}

    def get(self, key: str) -> Any | None:
        return self._entries.get(key)

    def set(self, key: str, summary: Any) -> None:
        self._entries[key] = summary
        self._persist()

    def clear(self) -> None:
        self._entries = {}
        self._persist()

    def __contains__(self, key: str) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def _persist(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "schema": CONTEXT_CACHE_SCHEMA,
            "entries": self._entries,
        }
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
            handle.write("\n")


__all__ = ["CONTEXT_CACHE_SCHEMA", "ContextCache"]
