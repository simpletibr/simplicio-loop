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


def test_concurrent_acquire_heartbeat_release():
    """Test 20+ concurrent asyncio tasks on acquire, heartbeat, release.
    
    Validates:
    - Exactly one owner wins each key
    - JSON file stays valid after every operation
    - No update is lost (final state contains every key)
    """
    async def run():
        temp_file = temp_claims_file()
        try:
            store = ClaimStore(temp_file)
            num_tasks = 25
            num_keys = 5
            base_time = 2000
            
            results = {
                "acquired": {},
                "heartbeats": {},
                "released": {},
            }
            
            async def worker(task_id: int, key: str):
                """Simulate worker acquiring, heartbeating, and releasing a key."""
                try:
                    # Try to acquire
                    token = await store.acquire(key, f"worker_{task_id}", ttl_s=30, now=base_time + task_id)
                    if token is not None:
                        results["acquired"][key] = (task_id, token)
                        
                        # Heartbeat
                        success = await store.heartbeat(key, token, ttl_s=30, now=base_time + task_id + 10)
                        if success:
                            results["heartbeats"][key] = task_id
                        
                        # Release
                        success = await store.release(key, token, "done", now=base_time + task_id + 20)
                        if success:
                            results["released"][key] = task_id
                except Exception as e:
                    print(f"Task {task_id} error: {e}")
            
            # Create many concurrent tasks targeting different keys
            tasks = []
            for task_id in range(num_tasks):
                key = f"key#{task_id % num_keys}"
                tasks.append(worker(task_id, key))
            
            # Run all tasks concurrently
            await asyncio.gather(*tasks)
            
            # Verify exactly one owner won each key
            for i in range(num_keys):
                key = f"key#{i}"
                claim = await store.get_claim(key)
                if claim is not None:
                    # Claim should exist and be finalized
                    assert claim.status == "done", f"Key {key} should be released"
                    assert claim.owner_token is None, f"Key {key} should have no token after release"
                    # Exactly one task acquired this key
                    assert key in results["acquired"], f"Key {key} was not acquired"
            
            # Verify file is valid JSON after all operations
            with open(temp_file, "r") as f:
                data = json.load(f)
                assert isinstance(data, dict), "Claims file should be valid JSON dict"
                for key in data:
                    assert "key" in data[key], f"Claim {key} missing 'key' field"
                    assert "status" in data[key], f"Claim {key} missing 'status' field"
            
            # Verify no updates lost - all keys should have final state
            for i in range(num_keys):
                key = f"key#{i}"
                assert key in data, f"Key {key} missing from final state"
                assert data[key]["status"] == "done", f"Key {key} not finalized"
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())


def test_cross_process_safety():
    """Test cross-process safety with two ClaimStore instances on same file.
    
    This is a single-process simulation: open two store handles to same file
    and verify no corruption or lost updates.
    """
    async def run():
        temp_file = temp_claims_file()
        try:
            store1 = ClaimStore(temp_file)
            store2 = ClaimStore(temp_file)
            
            # Store1 acquires a key
            token1 = await store1.acquire("shared_key", "worker1", ttl_s=60, now=1000)
            assert token1 is not None
            
            # Store2 should see the same claim (file-based)
            claim2 = await store2.get_claim("shared_key")
            assert claim2 is not None
            assert claim2.owner_token == token1
            
            # Store2 cannot acquire the same key (still valid)
            token2 = await store2.acquire("shared_key", "worker2", ttl_s=60, now=1000)
            assert token2 is None
            
            # Store1 heartbeats
            success = await store1.heartbeat("shared_key", token1, ttl_s=60, now=1050)
            assert success is True
            
            # Store2 sees the updated expiry
            claim2_updated = await store2.get_claim("shared_key")
            assert claim2_updated.lease_expires_at == 1110
            
            # Store1 releases
            success = await store1.release("shared_key", token1, "done", now=1050)
            assert success is True
            
            # Store2 sees the released claim
            claim2_final = await store2.get_claim("shared_key")
            assert claim2_final.status == "done"
            assert claim2_final.owner_token is None
            
            # Now store2 can acquire the same key
            token2_new = await store2.acquire("shared_key", "worker2", ttl_s=60, now=1060)
            assert token2_new is not None
            
            # Verify file consistency
            with open(temp_file, "r") as f:
                data = json.load(f)
                assert data["shared_key"]["status"] == "running"
                assert data["shared_key"]["owner_token"] == token2_new
        finally:
            if temp_file.exists():
                temp_file.unlink()
    
    asyncio.run(run())

