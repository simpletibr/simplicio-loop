from __future__ import annotations

import hashlib
import threading
import time
import unittest

from simplicio_fast.pager import (
    PageKey,
    PagerError,
    SemanticPager,
    SingleFlightCoordinator,
    SingleFlightError,
    make_request_key,
)


class SemanticPagerTest(unittest.TestCase):
    def key(self, segment: str, generation: str = "g") -> PageKey:
        return PageKey("repo", generation, "slot", segment, "0:10")

    def test_budget_evicts_lru_and_validates_generation(self) -> None:
        pager = SemanticPager("repo", "g", max_bytes=6, max_pages=2)
        pager.get(self.key("a"), lambda: b"aaa")
        pager.get(self.key("b"), lambda: b"bbb")
        pager.get(self.key("a"))
        pager.get(self.key("c"), lambda: b"ccc")
        self.assertEqual(2, pager.stats()["resident_pages"])
        self.assertGreaterEqual(pager.stats()["evictions"], 1)
        with self.assertRaises(PagerError) as error:
            pager.get(self.key("x", "stale"), lambda: b"x")
        self.assertEqual("stale_generation", error.exception.reason_code)

    def test_single_flight_loads_one_page_for_many_readers(self) -> None:
        pager = SemanticPager("repo", "g", max_bytes=100, max_pages=4)
        key = self.key("shared")
        calls = 0
        lock = threading.Lock()

        def loader() -> bytes:
            nonlocal calls
            with lock:
                calls += 1
            time.sleep(0.03)
            return b"shared"

        results: list[bytes] = []
        threads = [
            threading.Thread(target=lambda: results.append(pager.get(key, loader)))
            for _ in range(5)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, calls)
        self.assertEqual([b"shared"] * 5, results)
        self.assertGreaterEqual(pager.stats()["waits"], 1)

    def test_lease_and_invalidation_preserve_safety(self) -> None:
        data = b"payload"
        pager = SemanticPager("repo", "g", max_bytes=20, max_pages=2)
        key = self.key("held")
        with pager.lease(
            key, lambda: data, expected_sha256=hashlib.sha256(data).hexdigest()
        ) as leased:
            self.assertEqual(data, leased)
            self.assertEqual({"removed": 0, "held": 1}, pager.invalidate([key]))
            self.assertEqual(1, pager.stats()["held_pages"])
        self.assertEqual(0, pager.stats()["resident_pages"])
        with self.assertRaises(PagerError) as error:
            pager.get(
                key, lambda: b"wrong", expected_sha256=hashlib.sha256(data).hexdigest()
            )
        self.assertEqual("page_digest_mismatch", error.exception.reason_code)

    def test_prefetch_does_not_evict_resident_pages_when_budget_is_full(self) -> None:
        pager = SemanticPager("repo", "g", max_bytes=6, max_pages=2)
        first = self.key("first")
        second = self.key("second")
        third = self.key("third")
        pager.get(first, lambda: b"aaa")
        pager.get(second, lambda: b"bbb")

        result = pager.prefetch([third], lambda key: b"ccc")

        self.assertEqual({"useful": 0, "wasted": 1}, result)
        self.assertEqual(2, pager.stats()["resident_pages"])
        self.assertEqual(6, pager.stats()["resident_bytes"])
        self.assertEqual(0, pager.stats()["evictions"])
        self.assertEqual(b"aaa", pager.get(first))
        self.assertEqual(b"bbb", pager.get(second))
        self.assertEqual(1, pager.stats()["prefetch_wasted"])

    def test_stats_expose_bounded_working_set_receipt(self) -> None:
        pager = SemanticPager("repo", "g", max_bytes=6, max_pages=2)
        pager.get(self.key("a"), lambda: b"aaa")
        working_set = pager.stats()["working_set"]
        self.assertEqual(3, working_set["resident_bytes"])
        self.assertEqual(1, working_set["resident_pages"])
        self.assertEqual(6, working_set["max_bytes"])
        self.assertEqual(2, working_set["max_pages"])
        self.assertEqual(3, working_set["bytes_available"])


class SingleFlightCoordinatorTest(unittest.TestCase):
    def key(self, request: object = None, *, generation: str = "g1"):
        return make_request_key("repo", "commit", generation, request or {"term": "x"})

    def test_canonical_key_is_stable_and_scoped(self) -> None:
        first = self.key({"b": 2, "a": 1})
        second = self.key({"a": 1, "b": 2})
        other = self.key({"a": 1, "b": 3})
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertNotEqual(first, self.key(generation="g2"))

    def test_identical_requests_execute_once(self) -> None:
        coordinator = SingleFlightCoordinator(max_flights=2, max_waiters=8)
        key = self.key()
        started = threading.Event()
        release = threading.Event()
        calls = 0
        lock = threading.Lock()
        results: list[str] = []

        def operation() -> str:
            nonlocal calls
            with lock:
                calls += 1
            started.set()
            release.wait(1)
            return "shared"

        owner = threading.Thread(
            target=lambda: results.append(coordinator.run(key, operation))
        )
        owner.start()
        self.assertTrue(started.wait(1))
        waiters = [
            threading.Thread(
                target=lambda: results.append(coordinator.run(key, operation))
            )
            for _ in range(4)
        ]
        for thread in waiters:
            thread.start()
        release.set()
        owner.join(1)
        for thread in waiters:
            thread.join(1)
        self.assertEqual(1, calls)
        self.assertEqual(["shared"] * 5, sorted(results))
        self.assertGreaterEqual(coordinator.stats()["waiters"], 1)
        self.assertEqual(0, coordinator.stats()["active_flights"])

    def test_waiter_cancel_does_not_stop_owner_and_limit_is_bounded(self) -> None:
        coordinator = SingleFlightCoordinator(max_flights=1, max_waiters=1)
        key = self.key()
        started = threading.Event()
        release = threading.Event()
        cancelled = threading.Event()
        errors: list[str] = []

        def operation() -> str:
            started.set()
            release.wait(1)
            return "done"

        owner = threading.Thread(target=lambda: coordinator.run(key, operation))
        owner.start()
        self.assertTrue(started.wait(1))
        waiter = threading.Thread(
            target=lambda: self._capture_error(
                coordinator, key, operation, cancel_event=cancelled, errors=errors
            )
        )
        waiter.start()
        time.sleep(0.03)
        with self.assertRaises(SingleFlightError) as error:
            coordinator.run(key, operation)
        self.assertEqual("waiter_limit", error.exception.reason_code)
        cancelled.set()
        waiter.join(1)
        release.set()
        owner.join(1)
        self.assertIn("waiter_cancelled", errors)
        self.assertEqual(1, coordinator.stats()["owners"])

    def test_owner_failure_reaches_waiter_and_flight_is_cleaned(self) -> None:
        coordinator = SingleFlightCoordinator(max_flights=1, max_waiters=2)
        key = self.key()
        started = threading.Event()
        errors: list[str] = []

        def operation() -> str:
            started.set()
            time.sleep(0.05)
            raise RuntimeError("boom")

        owner = threading.Thread(
            target=lambda: self._capture_error(
                coordinator, key, operation, errors=errors
            )
        )
        owner.start()
        self.assertTrue(started.wait(1))
        waiter = threading.Thread(
            target=lambda: self._capture_error(
                coordinator, key, operation, errors=errors
            )
        )
        waiter.start()
        owner.join(1)
        waiter.join(1)
        self.assertEqual(["RuntimeError", "RuntimeError"], sorted(errors))
        self.assertEqual(1, coordinator.stats()["failures"])
        self.assertEqual(0, coordinator.stats()["active_flights"])

    @staticmethod
    def _capture_error(
        coordinator, key, operation, *, errors, cancel_event=None, timeout=None
    ) -> None:
        try:
            coordinator.run(key, operation, cancel_event=cancel_event, timeout=timeout)
        except (RuntimeError, SingleFlightError) as error:
            errors.append(
                type(error).__name__
                if isinstance(error, RuntimeError)
                else error.reason_code
            )

    def test_validation_timeout_and_flight_limit(self) -> None:
        with self.assertRaises(ValueError):
            SingleFlightCoordinator(max_flights=0)
        with self.assertRaises(ValueError):
            self.key(generation="")
        with self.assertRaises(TypeError):
            SingleFlightCoordinator().run("not-a-key", lambda: None)
        with self.assertRaises(ValueError):
            SingleFlightCoordinator().run(self.key(), lambda: None, timeout=-1)

        coordinator = SingleFlightCoordinator(max_flights=1, max_waiters=2)
        started = threading.Event()
        release = threading.Event()
        owner_key = self.key()
        other_key = self.key({"other": True})

        def operation() -> str:
            started.set()
            release.wait(1)
            return "done"

        owner = threading.Thread(target=lambda: coordinator.run(owner_key, operation))
        owner.start()
        self.assertTrue(started.wait(1))
        with self.assertRaises(SingleFlightError) as flight_error:
            coordinator.run(other_key, operation)
        self.assertEqual("flight_limit", flight_error.exception.reason_code)
        timeout_errors: list[str] = []
        waiter = threading.Thread(
            target=lambda: self._capture_error(
                coordinator, owner_key, operation, timeout=0.01, errors=timeout_errors
            )
        )
        waiter.start()
        waiter.join(1)
        release.set()
        owner.join(1)
        self.assertEqual(["waiter_timeout"], timeout_errors)

    def test_pager_rejects_invalid_keys_loaders_and_leases(self) -> None:
        with self.assertRaises(ValueError):
            SemanticPager("repo", "g", max_bytes=0, max_pages=1)
        pager = SemanticPager("repo", "g", max_bytes=3, max_pages=2)
        page_key = PageKey("repo", "g", "slot", "edge", "0:1")
        with self.assertRaises(PagerError) as error:
            pager.get(PageKey("other", "g", "slot", "x", "0:1"), lambda: b"x")
        self.assertEqual("cross_repo_page", error.exception.reason_code)
        with self.assertRaises(PagerError) as error:
            pager.get(
                PageKey("repo", "g", "slot", "x", "0:1", schema="wrong"), lambda: b"x"
            )
        self.assertEqual("schema_mismatch", error.exception.reason_code)
        with self.assertRaises(PagerError) as error:
            pager.get(page_key)
        self.assertEqual("page_not_resident", error.exception.reason_code)
        with self.assertRaises(TypeError):
            pager.get(page_key, lambda: "text")
        with pager.lease(page_key, lambda: b"aaa") as leased:
            self.assertEqual(b"aaa", leased)
            with self.assertRaises(PagerError) as error:
                pager.get(page_key, expected_sha256="0" * 64)
            self.assertEqual("page_digest_mismatch", error.exception.reason_code)
            with self.assertRaises(PagerError) as error:
                pager.get(PageKey("repo", "g", "slot", "budget", "0:1"), lambda: b"bbb")
            self.assertEqual("budget_exhausted", error.exception.reason_code)
        with self.assertRaises(PagerError) as error:
            pager.release(page_key)
        self.assertEqual("lease_mismatch", error.exception.reason_code)
        self.assertEqual(
            {"removed": 0, "held": 0},
            pager.invalidate([PageKey("repo", "g", "slot", "missing", "0:1")]),
        )

    def test_prefetch_records_useful_and_wasted(self) -> None:
        pager = SemanticPager("repo", "g1", max_bytes=20, max_pages=4)
        first = PageKey("repo", "g1", "slot", "first", "0:1")
        second = PageKey("repo", "g1", "slot", "second", "0:1")
        pager.get(first, lambda: b"a")
        self.assertEqual(
            {"useful": 1, "wasted": 1},
            pager.prefetch([first, second], lambda key: b"b"),
        )
        self.assertEqual(1, pager.stats()["prefetch_useful"])
        self.assertEqual(1, pager.stats()["prefetch_wasted"])
