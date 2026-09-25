import asyncio
from simplicio_fast.content_cache import CacheError, ContentCache, key


def test_twenty_concurrent_compute_once():
    async def run():
        c = ContentCache()
        calls = 0

        async def compute():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.001)
            return b"x"

        k = key("s", 1, "q", "c", "t", "facts")
        assert (
            len(await asyncio.gather(*(c.get(k, compute, ["a"]) for _ in range(20))))
            == 20
        )
        assert calls == 1

    asyncio.run(run())


def test_delta_only_invalidates_dependents():
    c = ContentCache()

    async def run():
        async def a():
            return b"a"

        await c.get("a", a, ["x"])
        await c.get("b", a, ["y"])
        assert c.invalidate({"x"}) == ["a"] and "b" in c.values

    asyncio.run(run())


def test_config_tool_drift_misses():
    assert key("s", 1, "q", "a", "t", "facts") != key("s", 1, "q", "b", "t", "facts")


def test_corrupt_fails_closed():
    async def run():
        c = ContentCache()
        c.values["x"] = (b"x", "bad")
        try:
            await c.get("x", lambda: None)
            assert False
        except CacheError:
            pass

    asyncio.run(run())
