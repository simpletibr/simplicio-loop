"""Lease-based claim storage for simplicio-loop watcher247.

Concurrency model: every read-modify-write runs under an in-process
``asyncio.Lock`` (tasks of one event loop) and an OS file lock on the sidecar
``<claims>.lock`` (``fcntl.flock``; ``msvcrt.locking`` on Windows), so the
watcher and an operator CLI in different processes can share one claims.json.

Corruption: an unreadable claims.json is never treated as empty. It is moved to
``claims.json.corrupt-<ms>``, ``ClaimsCorruptError`` (reason_code
``claims_corrupt``) is raised, and saves are refused until ``resolve_corrupt()``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

FINAL_STATUSES = frozenset({"done", "done_no_diff", "dead", "preexisting"})


class ClaimsCorruptError(Exception):
    """claims.json is unreadable; the file was moved aside and saves are refused."""

    reason_code = "claims_corrupt"

    def __init__(self, message: str, corrupt_path: Optional[Path] = None) -> None:
        super().__init__(message)
        self.corrupt_path = corrupt_path


class Claim:
    """A single claim with lease ownership and heartbeat tracking."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self.data = data

    @property
    def status(self) -> str:
        return self.data.get("status", "unknown")

    @property
    def attempts(self) -> int:
        return self.data.get("attempts", 0)

    @property
    def owner_token(self) -> str:
        return self.data.get("owner_token", "")

    @property
    def lease_expires_at(self) -> Optional[float]:
        return self.data.get("lease_expires_at")

    @property
    def started_at(self) -> Optional[str]:
        return self.data.get("started_at")

    @property
    def reason_code(self) -> Optional[str]:
        return self.data.get("reason_code")

    @property
    def finished_at(self) -> Optional[str]:
        return self.data.get("finished_at")

    @property
    def next_try_at(self) -> Optional[str]:
        return self.data.get("next_try_at")

    def is_lease_expired(self, now: Optional[float] = None) -> bool:
        """Check if this claim's lease has expired."""
        current_time = time.time() if now is None else float(now)
        expires_at = self.lease_expires_at
        return expires_at is not None and expires_at <= current_time

    def has_heartbeat(self) -> bool:
        """Check if this claim has an owner_token."""
        return bool(self.owner_token)


class ClaimStore:
    """Async-friendly lease-based claim store with atomic writes."""

    def __init__(self, claims_path: str | Path) -> None:
        self.claims_path = Path(claims_path)
        self.lock_path = self.claims_path.with_name(self.claims_path.name + ".lock")
        self._lock = asyncio.Lock()
        self._max_attempts = 2
        self._corrupt_path: Optional[Path] = None

    def _corrupt_error(self) -> ClaimsCorruptError:
        return ClaimsCorruptError(
            f"claims file corrupt, moved to {self._corrupt_path}; "
            "resolve_corrupt() to continue",
            self._corrupt_path,
        )

    def resolve_corrupt(self) -> None:
        """Acknowledge a corrupt claims file (kept aside) and allow saves again."""
        self._corrupt_path = None

    def _load_claims(self) -> Dict[str, Dict[str, Any]]:
        """Load claims; corrupt content is moved aside and raised, never dropped."""
        if self._corrupt_path is not None:
            raise self._corrupt_error()
        try:
            text = self.claims_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except UnicodeDecodeError:
            text = None
        if text is not None and not text.strip():
            return {}
        data = None
        if text is not None:
            try:
                data = json.loads(text)
            except ValueError:
                data = None
        if not isinstance(data, dict):
            aside = self.claims_path.with_name(
                f"{self.claims_path.name}.corrupt-{int(time.time() * 1000)}"
            )
            os.replace(self.claims_path, aside)
            self._corrupt_path = aside
            raise self._corrupt_error()
        return data

    async def _persist(self, claims: Dict[str, Dict[str, Any]]) -> None:
        """Write claims off the event loop (the awaitable I/O point of the critical section)."""
        await asyncio.to_thread(self._save_claims, claims)

    def _flock_acquire(self) -> int:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            else:
                while True:
                    try:
                        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                        break
                    except OSError:
                        continue
        except BaseException:
            os.close(fd)
            raise
        return fd

    @staticmethod
    def _flock_release(fd: int) -> None:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            else:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)

    @contextlib.asynccontextmanager
    async def _guard(self) -> AsyncIterator[None]:
        """Serialize read-modify-write across tasks (asyncio.Lock) and processes (file lock)."""
        async with self._lock:
            fut = asyncio.ensure_future(asyncio.to_thread(self._flock_acquire))
            try:
                fd = await asyncio.shield(fut)
            except asyncio.CancelledError:
                # the thread may still win the lock; release it when it does
                fut.add_done_callback(
                    lambda f: None
                    if f.cancelled() or f.exception()
                    else self._flock_release(f.result())
                )
                raise
            try:
                yield
            finally:
                self._flock_release(fd)

    def _save_claims(self, claims: Dict[str, Dict[str, Any]]) -> None:
        """Atomically save claims using temp file + os.replace."""
        if self._corrupt_path is not None:
            raise self._corrupt_error()
        self.claims_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.claims_path.with_suffix(self.claims_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(claims, ensure_ascii=False, indent=2) + "\n")
        tmp_path.chmod(0o600)
        os.replace(tmp_path, self.claims_path)

    @staticmethod
    def _is_acquirable(claim_data: Dict[str, Any], now: float, reopen: bool) -> bool:
        """New key, expired running lease, retry that is due, or a reopened final claim."""
        if not claim_data:
            return True
        claim = Claim(claim_data)
        if claim.status in FINAL_STATUSES:
            return reopen
        if claim.status == "running":
            return claim.is_lease_expired(now)
        if claim.status == "retry":
            next_try = claim.next_try_at
            if not next_try:
                return True
            try:
                due = datetime.fromisoformat(next_try.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return False
            return due <= now
        return False

    async def acquirable(self, key: str, *, now: Optional[float] = None, reopen: bool = False) -> bool:
        """Whether `acquire` would take this key right now; read-only (no lease, no lock file, no write): the file is replaced atomically."""
        current_time = time.time() if now is None else float(now)
        return self._is_acquirable(self._load_claims().get(key, {}), current_time, reopen)

    async def acquire(
        self,
        key: str,
        owner: str,
        ttl_s: float,
        now: Optional[float] = None,
        reopen: bool = False,
    ) -> Optional[str]:
        """Acquire a lease; None unless the claim is new, expired, retry-due or reopened."""
        current_time = time.time() if now is None else float(now)
        token = uuid.uuid4().hex

        async with self._guard():
            claims = self._load_claims()
            claim_data = claims.get(key, {})

            if not self._is_acquirable(claim_data, current_time, reopen):
                return None

            claim_data = {
                k: v
                for k, v in claim_data.items()
                if k not in ("next_try_at", "finished_at", "reason_code")
            }
            updated = {
                **claim_data,
                "key": key,
                "owner": owner,
                "owner_token": token,
                "lease_expires_at": current_time + ttl_s,
                "attempts": claim_data.get("attempts", 0) + 1,
                "status": "running",
                "started_at": self._iso_now(current_time),
            }
            claims[key] = updated
            await self._persist(claims)
            return token

    async def heartbeat(
        self, key: str, owner_token: str, ttl_s: float, now: Optional[float] = None
    ) -> bool:
        """Extend the lease TTL for a claim."""
        current_time = time.time() if now is None else float(now)

        async with self._guard():
            claims = self._load_claims()
            claim_data = claims.get(key, {})

            if claim_data.get("owner_token") != owner_token:
                return False
            if claim_data.get("lease_expires_at", 0) <= current_time:
                return False

            claim_data["lease_expires_at"] = current_time + ttl_s
            claims[key] = claim_data
            await self._persist(claims)
            return True

    async def release(
        self, key: str, owner_token: str, status: str,
        now: Optional[float] = None, **extra_fields: Any
    ) -> bool:
        """Release a claim and set its final status."""
        current_time = time.time() if now is None else float(now)

        async with self._guard():
            claims = self._load_claims()
            claim_data = claims.get(key, {})

            if claim_data.get("owner_token") != owner_token:
                return False
            if claim_data.get("lease_expires_at", 0) <= current_time:
                return False

            updated = {
                **claim_data,
                "status": status,
                "finished_at": self._iso_now(current_time),
                "lease_expires_at": None,
                "owner_token": None,
            }
            updated.update(extra_fields)
            claims[key] = updated
            await self._persist(claims)
            return True

    async def reap_expired(
        self, now: Optional[float] = None, max_attempts: Optional[int] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Move expired running leases to retry or dead."""
        current_time = time.time() if now is None else float(now)
        max_att = max_attempts if max_attempts is not None else self._max_attempts
        reaped = {}

        async with self._guard():
            claims = self._load_claims()

            for key, claim_data in claims.items():
                claim = Claim(claim_data)
                if claim.status != "running" or not claim.has_heartbeat():
                    continue
                if not claim.is_lease_expired(current_time):
                    continue

                new_status = "dead" if claim.attempts >= max_att else "retry"
                next_try_at = None
                if new_status == "retry":
                    next_try_at = self._iso_now(current_time + 300)

                updated = {
                    **claim_data,
                    "status": new_status,
                    "finished_at": self._iso_now(current_time),
                    "reason_code": "lease_expired",
                    "lease_expires_at": None,
                    "owner_token": None,
                }
                if next_try_at:
                    updated["next_try_at"] = next_try_at
                claims[key] = updated
                reaped[key] = updated

            if reaped:
                await self._persist(claims)

        return reaped

    async def migrate_legacy(
        self, ttl_s: float, now: Optional[float] = None, max_attempts: Optional[int] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Migrate legacy running claims without heartbeats to expired."""
        current_time = time.time() if now is None else float(now)
        max_att = max_attempts if max_attempts is not None else self._max_attempts
        migrated = {}

        async with self._guard():
            claims = self._load_claims()

            for key, claim_data in claims.items():
                claim = Claim(claim_data)
                if claim.status != "running" or claim.has_heartbeat():
                    continue

                started_at_str = claim.started_at
                if not started_at_str:
                    continue

                try:
                    started_dt = datetime.fromisoformat(
                        started_at_str.replace("Z", "+00:00")
                    )
                    age_s = current_time - started_dt.timestamp()
                except (ValueError, AttributeError):
                    continue

                if age_s <= ttl_s:
                    continue

                new_status = "dead" if claim.attempts >= max_att else "retry"
                next_try_at = None
                if new_status == "retry":
                    next_try_at = self._iso_now(current_time + 300)

                updated = {
                    **claim_data,
                    "status": new_status,
                    "finished_at": self._iso_now(current_time),
                    "reason_code": "lease_expired",
                }
                if next_try_at:
                    updated["next_try_at"] = next_try_at
                claims[key] = updated
                migrated[key] = updated

            if migrated:
                await self._persist(claims)

        return migrated

    async def get_claim(self, key: str) -> Optional[Claim]:
        """Get a claim by key (a read: no lock file; the file is replaced atomically)."""
        data = self._load_claims().get(key)
        return Claim(data) if data else None

    async def list_claims(self) -> Dict[str, Claim]:
        """List all claims."""
        async with self._guard():
            claims = self._load_claims()
            return {key: Claim(data) for key, data in claims.items()}

    @staticmethod
    def _iso_now(timestamp: Optional[float] = None) -> str:
        """Format timestamp as ISO 8601 string (UTC)."""
        if timestamp is None:
            timestamp = time.time()
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

