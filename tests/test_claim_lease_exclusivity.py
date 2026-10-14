"""Exclusivity, real concurrency, cross-process and corruption tests for ClaimStore (#1464)."""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from simplicio_loop.claim_lease import ClaimsCorruptError, ClaimStore

REPO_ROOT = Path(__file__).resolve().parent.parent


def inject_yield(store: ClaimStore, steps: int = 3) -> None:
    """Make the write inside the critical section yield to the event loop.

    Without a real lock around read-modify-write, tasks interleave here and
    more than one of them would win the same key.
    """
    original = store._persist

    async def slow_persist(claims):
        for _ in range(steps):
            await asyncio.sleep(0)
        await original(claims)

    store._persist = slow_persist


# --- 1. exclusivity -------------------------------------------------------


@pytest.mark.parametrize("status", ["done", "done_no_diff", "dead", "preexisting"])
def test_acquire_refuses_final_status_unless_reopen(tmp_path, status):
    async def run():
        store = ClaimStore(tmp_path / "claims.json")
        store._save_claims({"k": {"key": "k", "status": status, "attempts": 1}})
        assert await store.acquire("k", "w", ttl_s=60, now=1000) is None
        token = await store.acquire("k", "w", ttl_s=60, now=1000, reopen=True)
        assert token is not None
        assert (await store.get_claim("k")).status == "running"

    asyncio.run(run())


def test_acquire_refuses_active_running_even_with_reopen(tmp_path):
    async def run():
        store = ClaimStore(tmp_path / "claims.json")
        assert await store.acquire("k", "a", ttl_s=60, now=1000) is not None
        assert await store.acquire("k", "b", ttl_s=60, now=1030) is None
        assert await store.acquire("k", "b", ttl_s=60, now=1030, reopen=True) is None

    asyncio.run(run())


def test_acquire_retry_only_when_due(tmp_path):
    async def run():
        store = ClaimStore(tmp_path / "claims.json")
        assert await store.acquire("k", "a", ttl_s=60, now=1000) is not None
        await store.reap_expired(now=1061)  # retry, next_try_at = 1361
        claim = await store.get_claim("k")
        assert claim.status == "retry"
        assert await store.acquire("k", "b", ttl_s=60, now=1100) is None
        token = await store.acquire("k", "b", ttl_s=60, now=1362)
        assert token is not None
        claim = await store.get_claim("k")
        assert claim.status == "running" and claim.attempts == 2
        assert claim.next_try_at is None

    asyncio.run(run())


def test_acquire_refuses_legacy_running_without_lease(tmp_path):
    async def run():
        store = ClaimStore(tmp_path / "claims.json")
        store._save_claims({"k": {"key": "k", "status": "running", "attempts": 1}})
        assert await store.acquire("k", "w", ttl_s=60, now=1000) is None

    asyncio.run(run())


# --- 2. real concurrency --------------------------------------------------


def test_same_key_25_tasks_exactly_one_winner(tmp_path):
    async def run():
        path = tmp_path / "claims.json"
        store = ClaimStore(path)
        inject_yield(store)
        tokens = await asyncio.gather(
            *(store.acquire("k", f"w{i}", ttl_s=60, now=1000) for i in range(25))
        )
        winners = [t for t in tokens if t is not None]
        assert len(winners) == 1
        data = json.loads(path.read_text())
        assert data["k"]["owner_token"] == winners[0]
        assert data["k"]["attempts"] == 1

    asyncio.run(run())


def test_25_tasks_5_keys_one_winner_per_key_no_lost_keys(tmp_path):
    async def run():
        path = tmp_path / "claims.json"
        store = ClaimStore(path)
        inject_yield(store)
        keys = [f"key#{i % 5}" for i in range(25)]
        tokens = await asyncio.gather(
            *(store.acquire(k, f"w{i}", ttl_s=60, now=1000) for i, k in enumerate(keys))
        )
        wins = {}
        for k, t in zip(keys, tokens):
            if t is not None:
                wins.setdefault(k, []).append(t)
        assert sorted(wins) == [f"key#{i}" for i in range(5)]
        assert all(len(v) == 1 for v in wins.values())
        data = json.loads(path.read_text())
        assert sorted(data) == sorted(wins)
        for k, v in wins.items():
            assert data[k]["owner_token"] == v[0]

    asyncio.run(run())


def test_interleaved_acquire_heartbeat_release_distinct_keys(tmp_path):
    async def run():
        path = tmp_path / "claims.json"
        store = ClaimStore(path)
        inject_yield(store)

        async def cycle(i):
            key = f"k{i}"
            token = await store.acquire(key, f"w{i}", ttl_s=60, now=1000)
            assert token is not None
            assert await store.heartbeat(key, token, ttl_s=60, now=1010)
            assert await store.release(key, token, "done", now=1020)

        await asyncio.gather(*(cycle(i) for i in range(25)))
        data = json.loads(path.read_text())
        assert sorted(data) == sorted(f"k{i}" for i in range(25))
        assert all(v["status"] == "done" and v["owner_token"] is None for v in data.values())

    asyncio.run(run())


# --- 3. cross-process -----------------------------------------------------

ACQUIRE_SCRIPT = """
import asyncio, sys, time
from simplicio_loop.claim_lease import ClaimStore
path, key, owner, start = sys.argv[1:5]
async def main():
    while time.time() < float(start):
        await asyncio.sleep(0.0005)
    token = await ClaimStore(path).acquire(key, owner, ttl_s=3600, now=1000.0)
    print(token or 'NONE')
asyncio.run(main())
"""


def test_cross_process_flock_exactly_one_winner_per_key(tmp_path):
    async def run():
        path = tmp_path / "claims.json"
        start = time.time() + 2.0
        keys = [f"key#{i % 3}" for i in range(12)]
        procs = [
            await asyncio.create_subprocess_exec(
                sys.executable, "-c", ACQUIRE_SCRIPT, str(path), k, f"p{i}", str(start),
                cwd=str(REPO_ROOT), env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            for i, k in enumerate(keys)
        ]
        outs = await asyncio.gather(*(p.communicate() for p in procs))
        for p, (_, err) in zip(procs, outs):
            assert p.returncode == 0, err.decode()
        wins = {}
        for k, (out, _) in zip(keys, outs):
            token = out.decode().strip()
            if token != "NONE":
                wins.setdefault(k, []).append(token)
        assert sorted(wins) == ["key#0", "key#1", "key#2"]
        assert all(len(v) == 1 for v in wins.values())
        data = json.loads(path.read_text())
        assert sorted(data) == sorted(wins)
        for k, v in wins.items():
            assert data[k]["owner_token"] == v[0] and data[k]["attempts"] == 1

    asyncio.run(run())


def test_two_instances_same_file_share_state(tmp_path):
    async def run():
        a = ClaimStore(tmp_path / "claims.json")
        b = ClaimStore(tmp_path / "claims.json")
        token = await a.acquire("k", "a", ttl_s=60, now=1000)
        assert token is not None
        assert await b.acquire("k", "b", ttl_s=60, now=1000) is None
        assert await a.release("k", token, "done", now=1010)
        assert (await b.get_claim("k")).status == "done"
        assert await b.acquire("k", "b", ttl_s=60, now=1020) is None

    asyncio.run(run())


# --- 4. corruption --------------------------------------------------------


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '"str"'])
def test_corrupt_claims_moved_aside_and_refuses_to_save(tmp_path, content):
    async def run():
        path = tmp_path / "claims.json"
        path.write_text(content)
        store = ClaimStore(path)
        with pytest.raises(ClaimsCorruptError) as exc:
            await store.acquire("k", "w", ttl_s=60, now=1000)
        assert exc.value.reason_code == "claims_corrupt"
        aside = list(tmp_path.glob("claims.json.corrupt-*"))
        assert len(aside) == 1 and aside[0].read_text() == content
        assert exc.value.corrupt_path == aside[0]
        assert not path.exists()
        # still refuses: nothing is written until resolved
        with pytest.raises(ClaimsCorruptError):
            await store.acquire("k", "w", ttl_s=60, now=1000)
        with pytest.raises(ClaimsCorruptError):
            store._save_claims({})
        assert not path.exists()
        store.resolve_corrupt()
        assert await store.acquire("k", "w", ttl_s=60, now=1000) is not None
        assert aside[0].read_text() == content

    asyncio.run(run())


def test_empty_claims_file_is_not_corrupt(tmp_path):
    async def run():
        path = tmp_path / "claims.json"
        path.write_text("")
        store = ClaimStore(path)
        assert await store.acquire("k", "w", ttl_s=60, now=1000) is not None
        assert not list(tmp_path.glob("claims.json.corrupt-*"))

    asyncio.run(run())
