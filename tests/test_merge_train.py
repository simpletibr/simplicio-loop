"""Merge train: batch plan + bisecting run (#1504)."""

import asyncio
import math

import pytest

from simplicio_loop.merge_train import plan_train, run_train


class Fakes:
    def __init__(self, bad=(), async_test=False):
        self.bad = set(bad)
        self.tested = []
        self.merged = []
        self.async_test = async_test

    def test(self, prs):
        self.tested.append(list(prs))
        ok = not (set(prs) & self.bad)
        if self.async_test:
            async def _r():
                return ok
            return _r()
        return ok

    async def merge(self, pr):
        self.merged.append(pr)


def run(batch, fakes):
    return asyncio.run(run_train(batch, fakes.test, fakes.merge))


def test_plan_train_respects_order_and_batch_size():
    assert plan_train([5, 3, 9, 1, 7], order=[1, 3, 5, 7, 9], max_batch=2) == [[1, 3], [5, 7], [9]]


def test_plan_train_default_batch_is_4_and_skips_unapproved():
    assert plan_train([3, 1, 2, 4, 5], order=[1, 2, 3, 4, 5, 6]) == [[1, 2, 3, 4], [5]]


def test_plan_train_unordered_prs_go_last_in_given_order():
    assert plan_train([9, 2, 8], order=[2], max_batch=4) == [[2, 9, 8]]


def test_plan_train_empty_and_invalid():
    assert plan_train([], order=[1]) == []
    with pytest.raises(ValueError):
        plan_train([1], order=[1], max_batch=0)


def test_all_green_tests_once_and_merges_in_order():
    f = Fakes()
    r = run([1, 2, 3, 4], f)
    assert f.tested == [[1, 2, 3, 4]]
    assert f.merged == [1, 2, 3, 4]
    assert r.merged == [1, 2, 3, 4] and r.failed == [] and r.bisect_steps == 0
    assert r.wall_ms >= 0


def test_async_test_fn_supported():
    f = Fakes(async_test=True)
    assert run([1, 2], f).merged == [1, 2]


@pytest.mark.parametrize("culprit", [1, 2, 3, 4, 5, 6, 7, 8])
def test_one_culprit_isolated_in_log2_steps(culprit):
    batch = list(range(1, 9))
    f = Fakes(bad=[culprit])
    r = run(batch, f)
    assert r.failed == [culprit]
    assert r.merged == [p for p in batch if p != culprit]
    assert f.merged == r.merged
    search = math.ceil(math.log2(len(batch)))
    # log2(n) steps to find the culprit, +1 to verify the untested suffix.
    assert r.bisect_steps <= search + 1
    if culprit == len(batch):
        assert r.bisect_steps == search


def test_two_culprits():
    f = Fakes(bad=[2, 7])
    r = run(list(range(1, 9)), f)
    assert r.failed == [2, 7]
    assert r.merged == [1, 3, 4, 5, 6, 8]
    assert f.merged == r.merged


def test_all_red_merges_nothing():
    f = Fakes(bad=[1, 2, 3])
    r = run([1, 2, 3], f)
    assert r.merged == [] and f.merged == [] and r.failed == [1, 2, 3]


def test_single_pr_red_not_merged():
    f = Fakes(bad=[1])
    r = run([1], f)
    assert r.failed == [1] and f.merged == [] and r.bisect_steps == 0


def test_no_merge_happens_before_isolation_finishes():
    events = []
    bad = {3}

    def test(prs):
        events.append(("test", tuple(prs)))
        return not (set(prs) & bad)

    async def merge(pr):
        events.append(("merge", pr))

    asyncio.run(run_train([1, 2, 3, 4], test, merge))
    first_merge = next(i for i, e in enumerate(events) if e[0] == "merge")
    assert all(e[0] == "test" for e in events[:first_merge])
    assert [e[1] for e in events if e[0] == "merge"] == [1, 2, 4]


def _run_predicate(batch, red):
    """red(frozenset) -> True when that integrated set fails. Returns (report, tested, merged_calls)."""
    tested, merged = [], []

    def test(prs):
        tested.append((tuple(prs), not red(frozenset(prs))))
        return not red(frozenset(prs))

    async def merge(pr):
        merged.append(pr)

    return asyncio.run(run_train(batch, test, merge)), tested, merged


def test_merged_set_was_tested_green_as_a_whole_with_pair_interaction():
    # 3 fails alone; {1, 5} fail together; every other set is green.
    def red(s):
        return 3 in s or {1, 5} <= s

    r, tested, merged = _run_predicate([1, 2, 3, 4, 5], red)
    assert not red(frozenset(merged))
    assert r.failed == [3, 5] and r.merged == [1, 2, 4] == merged
    assert (tuple(merged), True) in tested


def test_two_prs_green_alone_red_together_merge_only_a_tested_set():
    def red(s):
        return {2, 4} <= s

    r, tested, merged = _run_predicate([1, 2, 3, 4], red)
    assert not red(frozenset(merged))
    assert r.merged == merged == [1, 2, 3] and r.failed == [4]
    assert (tuple(merged), True) in tested


def test_suffix_is_tested_on_top_of_the_good_prefix():
    r, tested, _ = _run_predicate([1, 2, 3, 4], lambda s: 2 in s)
    assert r.merged == [1, 3, 4]
    assert all(t[0][: len(t[0])] == tuple(sorted(t[0])) for t in tested)
    assert ((1, 3, 4), True) in tested


def test_empty_batch():
    r = run([], Fakes())
    assert r.merged == [] and r.failed == [] and r.bisect_steps == 0


def test_report_as_dict():
    d = run([1], Fakes()).as_dict()
    assert set(d) == {"merged", "failed", "bisect_steps", "wall_ms"}
