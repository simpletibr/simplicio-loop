"""Bounded semantic pager with deterministic LRU, leases and polite prefetch."""

from __future__ import annotations
import asyncio
import hashlib
import time
from collections import OrderedDict


class PagerError(RuntimeError):
    pass


class SemanticPager:
    def __init__(self, max_bytes, slot_bytes):
        self.max_bytes = max_bytes
        self.slot_bytes = slot_bytes
        self.pages = {}
        self.lru = OrderedDict()
        self.leases = {}
        self.flights = {}
        self.metrics = {"faults": 0, "evictions": 0, "resident_bytes": 0}

    async def page(
        self, slot, pid, expected_digest, loader, lease=False, prefetch=False
    ):
        key = (slot, pid)
        if key in self.pages:
            self.lru.move_to_end(key)
            return self.pages[key]
        if key in self.flights:
            return await self.flights[key]

        async def load():
            data = await loader()
            if hashlib.sha256(data).hexdigest() != expected_digest:
                raise PagerError("page_digest_invalid")
            if len(data) > self.slot_bytes or len(data) > self.max_bytes:
                raise PagerError("page_budget_exceeded")
            self._evict(len(data), slot)
            self.pages[key] = data
            self.lru[key] = None
            self.metrics["faults"] += 1
            self.metrics["resident_bytes"] += len(data)
            if lease:
                self.leases[key] = time.monotonic() + 60
            return data

        t = asyncio.create_task(load())
        self.flights[key] = t
        try:
            return await t
        finally:
            self.flights.pop(key, None)

    def _evict(self, needed, slot):
        while self.metrics["resident_bytes"] + needed > self.max_bytes:
            victim = next(
                (k for k in self.lru if self.leases.get(k, 0) <= time.monotonic()), None
            )
            if victim is None:
                raise PagerError("resident_budget_leased")
            self.lru.pop(victim)
            self.metrics["resident_bytes"] -= len(self.pages.pop(victim))
            self.metrics["evictions"] += 1

    async def prefetch(self, slot, candidates, loader):
        results = []
        for pid, digest in candidates:
            if self.flights:
                break
            try:
                results.append(
                    await self.page(
                        slot, pid, digest, lambda p=pid: loader(p), prefetch=True
                    )
                )
            except PagerError:
                break
        return results
