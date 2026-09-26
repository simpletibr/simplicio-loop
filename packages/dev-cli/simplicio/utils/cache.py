"""Two-tier caching: in-process `lru_cache` for hot calls, `diskcache` for
expensive deterministic work that should survive across processes.

Examples:
    @memoize_disk(namespace="mapper_artifacts", ttl=60)
    def load_project_map(root: str) -> dict: ...

    @lru_cache(maxsize=256)
    def parse_template(path: str) -> str: ...

The disk cache lives under `.simplicio-loop/cache/` next to the existing
`.simplicio-loop/embedding_cache.npz`. Each namespace gets its own subdir so
entries from different decorators never collide.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import wraps
from pathlib import Path

try:
    import diskcache as _dc

    _HAS_DISKCACHE = True
except ImportError:  # pragma: no cover - degrades gracefully
    _HAS_DISKCACHE = False


def _cache_root() -> Path:
    root = Path(os.environ.get("SIMPLICIO_CACHE_DIR", str(Path.cwd() / ".simplicio-loop" / "cache")))
    root.mkdir(parents=True, exist_ok=True)
    return root


_caches: dict[str, _dc.Cache] = {}


def get_cache(namespace: str) -> _dc.Cache | None:
    """Return the diskcache for `namespace`, creating it on first use."""
    if not _HAS_DISKCACHE:
        return None
    if namespace not in _caches:
        _caches[namespace] = _dc.Cache(str(_cache_root() / namespace))
    return _caches[namespace]


def memoize_disk(*, namespace: str, ttl: int | None = None) -> Callable:
    """Decorator: memoize deterministic function calls to disk.

    `ttl` (seconds) lets a cache expire automatically; pass `None` for
    permanent entries (still purgeable manually by deleting the namespace).
    """

    def decorate(fn: Callable) -> Callable:
        if not _HAS_DISKCACHE:
            return fn

        cache = get_cache(namespace)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__qualname__, args, tuple(sorted(kwargs.items())))
            sentinel = object()
            cached = cache.get(key, default=sentinel)
            if cached is not sentinel:
                return cached
            value = fn(*args, **kwargs)
            cache.set(key, value, expire=ttl)
            return value

        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapper

    return decorate


def clear(namespace: str) -> int:
    """Drop every entry in `namespace`. Returns the number of entries removed."""
    cache = get_cache(namespace)
    if cache is None:
        return 0
    n = len(cache)
    cache.clear()
    return n
