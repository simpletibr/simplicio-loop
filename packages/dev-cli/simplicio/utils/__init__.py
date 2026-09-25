"""Utility modules: HTTP client (httpx connection pooling), serialization
(orjson), and on-disk + in-memory caching (diskcache + lru_cache).

Issue #14 (Performance Phase 1): give the project a shared, reusable HTTP
client so repeated calls reuse connections, a faster JSON path so
serialization stops being the hot loop, and a cache so deterministic work
(template loading, mapper artifacts, embeddings keys) does not re-run.
"""
