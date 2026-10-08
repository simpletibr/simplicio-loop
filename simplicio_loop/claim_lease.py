"""Lease-based claim storage for simplicio-loop watcher247."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


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
        self._lock = asyncio.Lock()
        self._max_attempts = 2

    def _load_claims(self) -> Dict[str, Dict[str, Any]]:
        """Load claims from JSON file."""
        if not self.claims_path.exists():
            return {}
        try:
            return json.loads(self.claims_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_claims(self, claims: Dict[str, Dict[str, Any]]) -> None:
        """Atomically save claims using temp file + os.replace."""
        self.claims_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.claims_path.with_suffix(self.claims_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(claims, ensure_ascii=False, indent=2) + "\n")
        tmp_path.chmod(0o600)
        os.replace(tmp_path, self.claims_path)

    async def acquire(
        self, key: str, owner: str, ttl_s: float, now: Optional[float] = None
    ) -> Optional[str]:
        """Acquire or reclaim a lease for a claim."""
        current_time = time.time() if now is None else float(now)
        token = uuid.uuid4().hex

        async with self._lock:
            claims = self._load_claims()
            claim_data = claims.get(key, {})
            claim = Claim(claim_data)

            if claim.has_heartbeat() and not claim.is_lease_expired(current_time):
                return None

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
            self._save_claims(claims)
            return token

    async def heartbeat(
        self, key: str, owner_token: str, ttl_s: float, now: Optional[float] = None
    ) -> bool:
        """Extend the lease TTL for a claim."""
        current_time = time.time() if now is None else float(now)

        async with self._lock:
            claims = self._load_claims()
            claim_data = claims.get(key, {})

            if claim_data.get("owner_token") != owner_token:
                return False
            if claim_data.get("lease_expires_at", 0) <= current_time:
                return False

            claim_data["lease_expires_at"] = current_time + ttl_s
            claims[key] = claim_data
            self._save_claims(claims)
            return True

    async def release(
        self, key: str, owner_token: str, status: str,
        now: Optional[float] = None, **extra_fields: Any
    ) -> bool:
        """Release a claim and set its final status."""
        current_time = time.time() if now is None else float(now)

        async with self._lock:
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
            self._save_claims(claims)
            return True

    async def reap_expired(
        self, now: Optional[float] = None, max_attempts: Optional[int] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Move expired running leases to retry or dead."""
        current_time = time.time() if now is None else float(now)
        max_att = max_attempts if max_attempts is not None else self._max_attempts
        reaped = {}

        async with self._lock:
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
                self._save_claims(claims)

        return reaped

    async def migrate_legacy(
        self, ttl_s: float, now: Optional[float] = None, max_attempts: Optional[int] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Migrate legacy running claims without heartbeats to expired."""
        current_time = time.time() if now is None else float(now)
        max_att = max_attempts if max_attempts is not None else self._max_attempts
        migrated = {}

        async with self._lock:
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
                self._save_claims(claims)

        return migrated

    async def get_claim(self, key: str) -> Optional[Claim]:
        """Get a claim by key."""
        async with self._lock:
            claims = self._load_claims()
            data = claims.get(key)
            return Claim(data) if data else None

    async def list_claims(self) -> Dict[str, Claim]:
        """List all claims."""
        async with self._lock:
            claims = self._load_claims()
            return {key: Claim(data) for key, data in claims.items()}

    @staticmethod
    def _iso_now(timestamp: Optional[float] = None) -> str:
        """Format timestamp as ISO 8601 string (UTC)."""
        if timestamp is None:
            timestamp = time.time()
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

