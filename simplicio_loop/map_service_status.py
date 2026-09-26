"""Cross-module map-service session: wires registry + single-flight store + watchers
into one object with real cache hit/build/wait/invalidate counters, and a status file
that lets a separate process (the CLI) report those counters without fabricating them."""

import json
from pathlib import Path
from threading import RLock
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional

from .map_service import MapServiceRegistry, RepositoryIdentity
from .map_service_single_flight import MapHandle, SingleFlightMapStore
from .map_service_watchers import MapWatcherManager

SCHEMA = "simplicio.map-service-status/v1"
DEFAULT_RELATIVE_PATH = (".simplicio-loop/orchestrator", "map", "status.json")


class MapServiceSession:
    """One process-level owner of the registry/store/watchers triad, with counters that
    reflect what actually happened (never inferred after the fact from unrelated state)."""

    def __init__(
        self,
        registry: Optional[MapServiceRegistry] = None,
        *,
        max_watchers: int = 64,
        max_pending: int = 256,
    ) -> None:
        self.registry = registry or MapServiceRegistry()
        self.store = SingleFlightMapStore(self.registry)
        self.watchers = MapWatcherManager(
            self.registry, self, max_watchers=max_watchers, max_pending=max_pending
        )
        self._lock = RLock()
        self._cache_hits = 0
        self._builds = 0
        self._waits = 0
        self._invalidations = 0

    async def get_or_build(
        self,
        identity_key: str,
        *,
        mode: str,
        tree_hash: str,
        files: Iterable[str] = (),
        builder: Callable[[], Awaitable[Any]],
    ) -> MapHandle:
        file_tuple = tuple(sorted(str(path) for path in files))
        key = self.store._key(identity_key, mode, tree_hash, file_tuple)
        with self._lock:
            already_completed = key in self.store._completed
            already_inflight = key in self.store._inflight
        handle = await self.store.get_or_build(
            identity_key, mode=mode, tree_hash=tree_hash, files=files, builder=builder
        )
        with self._lock:
            if already_completed:
                self._cache_hits += 1
            elif already_inflight:
                self._waits += 1
            else:
                self._builds += 1
        return handle

    def invalidate(self, identity_key: str, *, reason: str = "source_changed"):
        with self._lock:
            self._invalidations += 1
        return self.store.invalidate(identity_key, reason=reason)

    def rebind(self, old_identity_key: str, new_identity: RepositoryIdentity) -> str:
        """Move the watcher and supersede the identity after a branch switch,
        rebase, or dirty-state transition — the counted, session-level path onto
        `MapWatcherManager.rebind` (which alone only moved the watcher, without
        the session ever seeing that an invalidation happened)."""
        new_key = self.watchers.rebind(old_identity_key, new_identity)
        with self._lock:
            self._invalidations += 1
        return new_key

    def gc(self):
        return self.store.gc()

    def counters(self) -> Dict[str, int]:
        with self._lock:
            return {
                "cache_hits": self._cache_hits,
                "builds": self._builds,
                "waits": self._waits,
                "invalidations": self._invalidations,
            }

    def status(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "counters": self.counters(),
            "active_builds": self.store.active_builds,
            "owners_started": self.store.owners_started,
            "watchers": self.watchers.status(),
        }

    def write_status_file(self, path: Any) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.status(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return target


def default_status_path(repo: str) -> Path:
    return Path(repo).joinpath(*DEFAULT_RELATIVE_PATH)


def load_status_file(path: Any) -> Optional[Dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError("status file does not match " + SCHEMA)
    return payload
