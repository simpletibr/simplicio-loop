"""simplicio_cache — content-addressed, exact-match RESPONSE cache (stdlib only).

The GPU-free analog of an LLM KV cache for token economy: a repeated IDENTICAL
deterministic request returns the cached upstream response verbatim and skips the
LLM call entirely (~100% token saving on a hit).

Correctness is paramount: only *deterministic* requests (temperature == 0, no
streaming) are ever cached, and the cache key is a sha256 over a CANONICAL view of
the determinism-relevant fields, so it never serves a wrong/stale answer.

Everything is fail-open: any internal error is swallowed and treated as a cache
miss — the proxy must keep working even if the cache breaks.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from hashlib import sha256
from pathlib import Path

# determinism-relevant request params (everything else is ignored for the key)
_PARAM_KEYS = ("temperature", "top_p", "max_tokens", "tools", "response_format")

# defaults for the eviction bound
_MAX_ENTRIES = 500
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB


def _cache_root() -> Path:
    """Resolve the cache dir: <SIMPLICIO_HOME>/cache, else ~/.simplicio-loop/cache."""
    home = os.environ.get("SIMPLICIO_HOME")
    base = Path(home) if home else Path.home() / ".simplicio-loop"
    return base / "cache"


class ResponseCache:
    def __init__(self, directory=None, max_entries=_MAX_ENTRIES, max_bytes=_MAX_BYTES):
        self.dir = Path(directory) if directory else _cache_root()
        self.max_entries = int(max_entries)
        self.max_bytes = int(max_bytes)
        self._lock = threading.Lock()
        self._stats_path = self.dir / "_stats.json"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    # ---- keying -----------------------------------------------------------

    def key(self, model, body):
        """sha256 hex of a canonical view of the determinism-relevant fields.

        Includes: model, messages (+ system if present), and the params in
        _PARAM_KEYS. Ignores volatile/irrelevant fields (stream, user, n==1,
        any *_id, metadata, etc.). Fail-open: on any error, returns a key that
        will simply never collide with a real entry (so caller treats as miss).
        """
        try:
            body = body or {}
            canonical = {
                "model": model if model is not None else body.get("model"),
                "messages": body.get("messages"),
            }
            if body.get("system") is not None:
                canonical["system"] = body.get("system")
            # n only matters if it is explicitly > 1 (n==1 is the default)
            n = body.get("n")
            if n is not None and int(n) != 1:
                canonical["n"] = n
            for k in _PARAM_KEYS:
                if k in body and body[k] is not None:
                    canonical[k] = body[k]
            blob = json.dumps(
                canonical, sort_keys=True, separators=(",", ":"), default=str
            )
            return sha256(blob.encode("utf-8")).hexdigest()
        except Exception:
            # unique-ish non-colliding token so this never matches a stored entry
            return "uncacheable-" + sha256(repr((model, id(body))).encode()).hexdigest()

    def cacheable(self, body):
        """True only for deterministic, non-streaming requests."""
        try:
            body = body or {}
            if body.get("stream"):
                return False
            return float(body.get("temperature", 0) or 0) == 0.0
        except Exception:
            return False

    # ---- disk layout ------------------------------------------------------

    def _path(self, key):
        # shard by first 2 hex chars to keep directories small
        return self.dir / key[:2] / (key + ".json")

    # ---- read / write -----------------------------------------------------

    def get(self, key):
        """Return (status, headers, body_bytes) or None. Touches mtime (LRU)."""
        try:
            path = self._path(key)
            if not path.exists():
                self._bump("misses")
                return None
            with path.open("r", encoding="utf-8") as fh:
                rec = json.load(fh)
            status = int(rec["status"])
            headers = rec.get("headers") or {}
            body = bytes.fromhex(rec["body_hex"])
            # LRU touch: refresh mtime so this entry is "recently used"
            try:
                os.utime(path, None)
            except Exception:
                pass
            self._bump("hits")
            return status, headers, body
        except Exception:
            # corrupt entry / any error → behave as a miss
            self._bump("misses")
            return None

    def put(self, key, status, headers, body):
        """Atomically store a response. No-op for errors (status >= 400)."""
        try:
            if int(status) >= 400:
                return
            shard = self._path(key).parent
            shard.mkdir(parents=True, exist_ok=True)
            rec = {
                "status": int(status),
                "headers": dict(headers or {}),
                "body_hex": (body or b"").hex(),
                "ts": time.time(),
            }
            data = json.dumps(rec, separators=(",", ":")).encode("utf-8")
            with self._lock:
                tmp = shard / (key + ".tmp." + str(os.getpid()))
                with tmp.open("wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self._path(key))
                self._evict()
        except Exception:
            # never raise into the caller
            try:
                if "tmp" in dir() and tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    # ---- eviction (LRU by mtime, bounded by count AND bytes) --------------

    def _iter_entries(self):
        for shard in self.dir.iterdir():
            if not shard.is_dir():
                continue
            for f in shard.iterdir():
                if f.suffix == ".json":
                    try:
                        st = f.stat()
                        yield f, st.st_mtime, st.st_size
                    except Exception:
                        continue

    def _evict(self):
        try:
            entries = list(self._iter_entries())
            total = sum(sz for _, _, sz in entries)
            if len(entries) <= self.max_entries and total <= self.max_bytes:
                return
            # oldest mtime first → evict least-recently-used
            entries.sort(key=lambda e: e[1])
            count = len(entries)
            for f, _, sz in entries:
                if count <= self.max_entries and total <= self.max_bytes:
                    break
                try:
                    f.unlink()
                    count -= 1
                    total -= sz
                except Exception:
                    continue
        except Exception:
            pass

    # ---- stats ------------------------------------------------------------

    def _read_stats(self):
        try:
            with self._stats_path.open("r", encoding="utf-8") as fh:
                d = json.load(fh)
            return {"hits": int(d.get("hits", 0)), "misses": int(d.get("misses", 0))}
        except Exception:
            return {"hits": 0, "misses": 0}

    def _bump(self, field):
        try:
            with self._lock:
                d = self._read_stats()
                d[field] = d.get(field, 0) + 1
                tmp = self._stats_path.with_suffix(".tmp")
                with tmp.open("w", encoding="utf-8") as fh:
                    json.dump(d, fh, separators=(",", ":"))
                os.replace(tmp, self._stats_path)
        except Exception:
            pass

    def stats(self):
        entries = 0
        total = 0
        try:
            for _, _, sz in self._iter_entries():
                entries += 1
                total += sz
        except Exception:
            pass
        s = self._read_stats()
        return {
            "entries": entries,
            "bytes": total,
            "hits": s["hits"],
            "misses": s["misses"],
        }

    def clear(self):
        """Wipe every cache entry and the stats file."""
        try:
            import shutil

            if self.dir.exists():
                shutil.rmtree(self.dir)
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def _main(argv):
    cache = ResponseCache()
    cmd = argv[1] if len(argv) > 1 else "stats"
    if cmd == "stats":
        print(json.dumps(cache.stats(), indent=2))
        return 0
    if cmd == "clear":
        cache.clear()
        print("cleared " + str(cache.dir))
        return 0
    print("usage: simplicio_cache.py [stats|clear]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
