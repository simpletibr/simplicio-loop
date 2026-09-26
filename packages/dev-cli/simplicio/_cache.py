"""Content-addressed completion cache for provider outputs."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hbp import HbpError, HbpEvidenceLedger


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
    return Path.home() / ".simplicio-loop" / "cache"


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
        return self.root / key[:2] / f"{key}.hbp"

    def _legacy_path_for(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    @staticmethod
    def _fields(entry: CacheEntry) -> dict[str, str]:
        # repr/literal_eval is used only for the bounded metadata scalar. It
        # is never executed and keeps the internal cache free of JSON.
        return {
            "completion": entry.completion,
            "created_at": repr(entry.created_at),
            "metadata": repr(entry.metadata),
            "model": entry.model,
            "provider_id": entry.provider_id,
        }

    @staticmethod
    def _entry_from_fields(fields: dict[str, str]) -> CacheEntry:
        try:
            metadata = ast.literal_eval(fields.get("metadata", "{}"))
            created_at = float(fields.get("created_at", "0"))
        except (ValueError, SyntaxError, TypeError) as exc:
            raise HbpError("invalid completion cache fields") from exc
        if not isinstance(metadata, dict):
            raise HbpError("completion cache metadata must be a mapping")
        return CacheEntry(
            completion=fields.get("completion", ""),
            provider_id=fields.get("provider_id", ""),
            model=fields.get("model", ""),
            created_at=created_at or time.time(),
            metadata=metadata,
        )

    def _read_hbp(self, path: Path) -> CacheEntry:
        rows = HbpEvidenceLedger(path.parent, file_name=path.name).verify()
        if len(rows) != 1 or rows[0].topic != "completion-cache":
            raise HbpError("completion cache must contain exactly one record")
        payload = rows[0].payload
        payload_bytes = payload.encode("utf-8")
        prefix = b"hbp-fields/v1"
        if not payload_bytes.startswith(prefix):
            raise HbpError("completion cache has an unsupported payload")
        fields: dict[str, str] = {}
        cursor = len(prefix)
        while cursor < len(payload_bytes):
            if payload_bytes[cursor : cursor + 1] != b":":
                raise HbpError("invalid completion cache field framing")
            colon = payload_bytes.find(b":", cursor + 1)
            if colon < 0:
                raise HbpError("truncated completion cache field length")
            try:
                size = int(payload_bytes[cursor + 1 : colon])
            except ValueError as exc:
                raise HbpError("invalid completion cache field length") from exc
            start = colon + 1
            end = start + size
            raw_field, cursor = payload_bytes[start:end], end
            if len(raw_field) != size:
                raise HbpError("truncated completion cache field")
            try:
                field = raw_field.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HbpError("completion cache field is not UTF-8") from exc
            separator = field.find("=")
            if separator < 1:
                raise HbpError("completion cache field is missing a key")
            key, value = field[:separator], field[separator + 1 :]
            fields[key] = value
        return self._entry_from_fields(fields)

    def _write_hbp(self, path: Path, entry: CacheEntry) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{path.stem}.", dir=str(path.parent)))
        try:
            temp_path = temp_dir / path.name
            HbpEvidenceLedger(temp_dir, file_name=path.name).record_fields(
                "completion-cache", self._fields(entry), "simplicio-dev-cli/cache"
            )
            HbpEvidenceLedger(temp_dir, file_name=path.name).verify()
            os.replace(temp_path, path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def get(self, key: str) -> CacheEntry | None:
        if not self.enabled or self.bust:
            self.misses += 1
            return None
        path = self.path_for(key)
        try:
            if not path.exists():
                legacy = self._legacy_path_for(key)
                if legacy.exists():
                    try:
                        with legacy.open("r", encoding="utf-8") as handle:
                            self._write_hbp(path, CacheEntry.from_dict(json.load(handle)))
                        legacy.unlink()
                    except (OSError, ValueError, TypeError, json.JSONDecodeError, HbpError):
                        self._safe_unlink(legacy)
                        self.misses += 1
                        return None
                else:
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
            entry = self._read_hbp(path)
            self.hits += 1
            return entry
        except (OSError, ValueError, TypeError, HbpError):
            self._safe_unlink(path)
            self.misses += 1
            return None

    def put(self, key: str, entry: CacheEntry) -> None:
        if not self.enabled:
            return
        path = self.path_for(key)
        try:
            self._write_hbp(path, entry)
        except OSError:
            return
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
                for path in self.root.rglob("*.hbp")
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
