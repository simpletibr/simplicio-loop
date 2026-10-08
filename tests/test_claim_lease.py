"""Tests for claim_lease module - core functionality."""

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from simplicio_loop.claim_lease import Claim, ClaimStore


def temp_claims_file():
    """Create a temporary claims file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        return Path(f.name)


def test_acquire_new_claim():
    """Test acquiring a new claim."""
    async def run():
        temp_file = temp_claims_file()
        try:
            store = ClaimStore(temp_file)
            token = await store.acquire("repo#123", "worker1", ttl_s=60, now=1000)
            assert token is not None
            assert len(token) == 32
            claim = await store.get_claim("repo#123")
            assert claim.owner_token == token
            assert claim.status == "running"
            assert claim.attempts == 1
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())


def test_acquire_live_lease_returns_none():
    """Test that acquiring when another owner holds the lease returns None."""
    async def run():
        temp_file = temp_claims_file()
        try:
            store = ClaimStore(temp_file)
            token1 = await store.acquire("repo#123", "worker1", ttl_s=60, now=1000)
            assert token1 is not None
            token2 = await store.acquire("repo#123", "worker2", ttl_s=60, now=1000)
            assert token2 is None
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())


def test_acquire_reclaim_expired_lease():
    """Test acquiring a claim with an expired lease."""
    async def run():
        temp_file = temp_claims_file()
        try:
            store = ClaimStore(temp_file)
            token1 = await store.acquire("repo#123", "worker1", ttl_s=60, now=1000)
            token2 = await store.acquire("repo#123", "worker2", ttl_s=60, now=1061)
            assert token2 is not None
            assert token2 != token1
            claim = await store.get_claim("repo#123")
            assert claim.attempts == 2
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())


def test_heartbeat_extends_lease():
    """Test heartbeat extends the lease TTL."""
    async def run():
        temp_file = temp_claims_file()
        try:
            store = ClaimStore(temp_file)
            token = await store.acquire("repo#123", "worker1", ttl_s=60, now=1000)
            success = await store.heartbeat("repo#123", token, ttl_s=60, now=1050)
            assert success is True
            claim = await store.get_claim("repo#123")
            assert claim.lease_expires_at == 1110
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())


def test_release_finalizes_claim():
    """Test releasing a claim."""
    async def run():
        temp_file = temp_claims_file()
        try:
            store = ClaimStore(temp_file)
            token = await store.acquire("repo#123", "worker1", ttl_s=60, now=1000)
            success = await store.release("repo#123", token, "done", now=1050)
            assert success is True
            claim = await store.get_claim("repo#123")
            assert claim.status == "done"
            assert claim.owner_token is None
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())


def test_reap_expired_moves_to_retry():
    """Test that expired running leases move to retry."""
    async def run():
        temp_file = temp_claims_file()
        try:
            store = ClaimStore(temp_file)
            token = await store.acquire("repo#123", "worker1", ttl_s=60, now=1000)
            reaped = await store.reap_expired(now=1061)
            assert "repo#123" in reaped
            claim = await store.get_claim("repo#123")
            assert claim.status == "retry"
            assert claim.reason_code == "lease_expired"
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())


def test_reap_expired_moves_to_dead_at_max_attempts():
    """Test that expired leases move to dead at max attempts."""
    async def run():
        temp_file = temp_claims_file()
        try:
            store = ClaimStore(temp_file)
            token1 = await store.acquire("repo#123", "worker1", ttl_s=60, now=1000)
            await store.reap_expired(now=1061)
            token2 = await store.acquire("repo#123", "worker2", ttl_s=60, now=1070)
            reaped = await store.reap_expired(now=1131)
            assert "repo#123" in reaped
            claim = await store.get_claim("repo#123")
            assert claim.status == "dead"
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())


def test_migrate_legacy_moves_old_running():
    """Test that legacy running claims older than TTL are migrated."""
    async def run():
        temp_file = temp_claims_file()
        try:
            store = ClaimStore(temp_file)
            # Use a realistic timestamp: 1 billion seconds (2001-09-09 01:46:40 UTC)
            now_ts = 1000000000
            old_ts = now_ts - 100  # 100 seconds old
            old_dt = datetime.fromtimestamp(old_ts, tz=timezone.utc)
            claims_data = {
                "repo#123": {
                    "key": "repo#123",
                    "status": "running",
                    "attempts": 1,
                    "started_at": old_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            }
            store._save_claims(claims_data)
            # Migrate with TTL of 60 seconds, now 100 seconds after start
            migrated = await store.migrate_legacy(ttl_s=60, now=now_ts)
            assert "repo#123" in migrated
            claim = await store.get_claim("repo#123")
            assert claim.status == "retry"
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())


def test_stale_owner_cannot_act():
    """Test that a stale owner cannot heartbeat or release."""
    async def run():
        temp_file = temp_claims_file()
        try:
            store = ClaimStore(temp_file)
            token = await store.acquire("repo#123", "worker1", ttl_s=60, now=1000)
            success = await store.heartbeat("repo#123", "wrong_token", ttl_s=60, now=1050)
            assert success is False
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())


def test_claim_properties():
    """Test Claim property getters."""
    data = {
        "key": "repo#123",
        "status": "running",
        "attempts": 1,
        "owner_token": "token123",
        "lease_expires_at": 1060,
    }
    claim = Claim(data)
    assert claim.status == "running"
    assert claim.attempts == 1
    assert claim.has_heartbeat() is True
    assert claim.is_lease_expired(now=1050) is False
    assert claim.is_lease_expired(now=1060) is True

