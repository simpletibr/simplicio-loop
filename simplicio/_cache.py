"""Content-addressed completion cache for provider outputs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _cache_root() -> Path:
    override = os.environ.get("SIMPLICIO_CACHE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".simplicio" / "cache"


def make_key(provider_id: str, model: str, prompt: str, **kwargs: Any) -> str:
    payload = {
        "v": 1,
        "provider_id": provider_id,
        "model": model,
        "prompt": prompt,
        "kwargs": kwargs,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class CacheEntry:
    completion: str
    provider_id: str = ""
    model: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "completion": self.completion,
            "provider_id": self.provider_id,
            "model": self.model,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CacheEntry:
        return cls(
            completion=str(payload.get("completion", "")),
            provider_id=str(payload.get("provider_id", "")),
            model=str(payload.get("model", "")),
            created_at=float(payload.get("created_at") or time.time()),
            metadata=dict(payload.get("metadata") or {}),
        )


class CompletionCache:
    def __init__(
        self,
        root: Path | None = None,
        *,
        ttl_days: float | None = None,
        max_mb: float | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else _cache_root()
        self.ttl_days = ttl_days if ttl_days is not None else _env_float("SIMPLICIO_CACHE_TTL_DAYS", 30)
        self.max_mb = max_mb if max_mb is not None else _env_float("SIMPLICIO_CACHE_MAX_MB", 500)
        self.hits = 0
        self.misses = 0
        self.puts = 0

    @property
    def enabled(self) -> bool:
        return _env_flag("SIMPLICIO_CACHE", True)

    @property
    def bust(self) -> bool:
        return _env_flag("SIMPLICIO_BUST_CACHE", False)

    def path_for(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> CacheEntry | None:
        if not self.enabled or self.bust:
            self.misses += 1
            return None
        path = self.path_for(key)
        try:
            if not path.exists():
                self.misses += 1
                return None
            if self._is_expired(path):
                self._safe_unlink(path)
                self.misses += 1
                return None
        except OSError:
            self.misses += 1
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                entry = CacheEntry.from_dict(json.load(handle))
                self.hits += 1
                return entry
        except (OSError, ValueError, TypeError):
            self._safe_unlink(path)
            self.misses += 1
            return None

    def put(self, key: str, entry: CacheEntry) -> None:
        if not self.enabled:
            return
        path = self.path_for(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{path.stem}.",
                suffix=".tmp",
                dir=str(path.parent),
            )
        except OSError:
            return
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(entry.to_dict(), handle, sort_keys=True)
            try:
                os.replace(tmp_name, path)
            except OSError:
                return
        finally:
            if os.path.exists(tmp_name):
                self._safe_unlink(Path(tmp_name))
        self.puts += 1
        evict_every = max(1, _env_int("SIMPLICIO_CACHE_EVICT_EVERY", 16))
        if self.puts == 1 or self.puts % evict_every == 0:
            self._evict_if_needed()

    def clear(self) -> int:
        n = self.stats()["entries"]
        if self.root.exists():
            shutil.rmtree(self.root)
        return int(n)

    def stats(self) -> dict[str, Any]:
        files = list(self._files())
        total_bytes = sum(path.stat().st_size for path in files if path.exists())
        now = time.time()
        oldest = None
        if files:
            oldest = max(0.0, now - min(path.stat().st_mtime for path in files))
        return {
            "enabled": self.enabled,
            "bust": self.bust,
            "root": str(self.root),
            "entries": len(files),
            "hits": self.hits,
            "misses": self.misses,
            "puts": self.puts,
            "hit_rate": round(self.hits / (self.hits + self.misses), 4) if self.hits + self.misses else 0.0,
            "bytes": total_bytes,
            "mb": round(total_bytes / (1024 * 1024), 3),
            "oldest_age_s": round(oldest, 3) if oldest is not None else None,
            "ttl_days": self.ttl_days,
            "max_mb": self.max_mb,
        }

    def _files(self) -> list[Path]:
        try:
            if not self.root.exists():
                return []
            return [
                path
                for path in self.root.rglob("*.json")
                if path.is_file() and _is_completion_cache_file(self.root, path)
            ]
        except OSError:
            return []

    def _is_expired(self, path: Path) -> bool:
        if self.ttl_days <= 0:
            return False
        max_age = self.ttl_days * 86400
        return (time.time() - path.stat().st_mtime) > max_age

    def _evict_if_needed(self) -> None:
        max_bytes = int(max(0.0, self.max_mb) * 1024 * 1024)
        if max_bytes <= 0:
            return
        files = self._files()
        total = sum(path.stat().st_size for path in files if path.exists())
        if total <= max_bytes:
            return
        for path in sorted(files, key=lambda p: p.stat().st_mtime):
            size = path.stat().st_size
            self._safe_unlink(path)
            total -= size
            if total <= max_bytes:
                break

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink()
        except OSError:
            return


_cache: CompletionCache | None = None


def cache() -> CompletionCache:
    global _cache
    if _cache is None:
        _cache = CompletionCache()
    return _cache


def _is_completion_cache_file(root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return len(rel.parts) == 2 and len(path.stem) == 64 and rel.parts[0] == path.stem[:2]


def reset_for_tests() -> None:
    global _cache
    _cache = None


__all__ = [
    "CacheEntry",
    "CompletionCache",
    "cache",
    "make_key",
    "reset_for_tests",
]
