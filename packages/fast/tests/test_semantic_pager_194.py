import asyncio
import hashlib
from simplicio_fast.semantic_pager import PagerError, SemanticPager


def test_budget_lru_and_lease():
    async def r():
        p = SemanticPager(4, 4)

        def d(x: bytes) -> str:
            return hashlib.sha256(x).hexdigest()

        await p.page(
            "s", "a", d(b"aa"), lambda: asyncio.sleep(0, result=b"aa"), lease=True
        )
        await p.page("s", "b", d(b"bb"), lambda: asyncio.sleep(0, result=b"bb"))
        try:
            await p.page("s", "c", d(b"cccc"), lambda: asyncio.sleep(0, result=b"cccc"))
            assert False
        except PagerError:
            pass

    asyncio.run(r())


def test_digest_and_singleflight():
    async def r():
        p = SemanticPager(20, 20)
        calls = 0

        async def load():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.001)
            return b"x"

        d = hashlib.sha256(b"x").hexdigest()
        await asyncio.gather(*(p.page("s", "x", d, load) for _ in range(20)))
        assert calls == 1
        try:
            await p.page("s", "bad", "0" * 64, load)
            assert False
        except PagerError:
            pass

    asyncio.run(r())
