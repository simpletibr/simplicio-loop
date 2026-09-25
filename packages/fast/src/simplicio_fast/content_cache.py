"""Content-addressed cache with single-flight and selective dependency invalidation."""

from __future__ import annotations
import asyncio
import hashlib
import json
from collections import Counter


class CacheError(RuntimeError):
    pass


def key(source, generation, query, config, tool, kind):
    return hashlib.sha256(
        json.dumps(
            [source, generation, query, config, tool, kind], separators=(",", ":")
        ).encode()
    ).hexdigest()


class ContentCache:
    def __init__(self):
        self.values = {}
        self.deps = {}
        self.flights = {}
        self.metrics = Counter()

    async def get(self, k, compute, deps=()):
        if k in self.values:
            value, digest = self.values[k]
            if hashlib.sha256(value).hexdigest() != digest:
                raise CacheError("cache_corrupt")
            self.metrics["hit"] += 1
            return value
        if k in self.flights:
            self.metrics["coalesced"] += 1
            return await self.flights[k]

        async def run():
            value = await compute()
            self.values[k] = (value, hashlib.sha256(value).hexdigest())
            self.deps[k] = set(deps)
            self.metrics["miss"] += 1
            return value

        task = asyncio.create_task(run())
        self.flights[k] = task
        try:
            return await task
        finally:
            self.flights.pop(k, None)

    def invalidate(self, changed):
        doomed = {k for k, v in self.deps.items() if v.intersection(changed)}
        for k in doomed:
            self.values.pop(k, None)
            self.deps.pop(k, None)
        self.metrics["stale"] += len(doomed)
        return sorted(doomed)

    def receipt(self):
        return {
            "schema": "simplicio.fast-cache-receipt/v1",
            **self.metrics,
            "requests": sum(self.metrics.values()),
        }
