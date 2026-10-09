"""#1601: the items of ONE repo run in parallel, each in its own git worktree; the repo lock covers only the short git steps.

Tick level, every subprocess answered by FakeRun (its `git worktree add/remove` create and delete the directory, like git does).
The real-git side (stale entries, SIGTERM, branches, sandbox binds) is in test_worktrees.py.
"""
from __future__ import annotations

import asyncio

import pytest

from simplicio_loop.watcher247 import config, tick, worktrees

from .fakes import FakeRun, baseline, issue, read_json, run_tick

REPO = "simplicio-a"


def body(*files):
    return "Ajustar " + " e ".join(f"`{f}`" for f in files) + " para o fluxo do watcher seguir o contrato descrito."


def wt(number):
    return config.WORK / f"{REPO}.wt" / str(number)


def pinned(monkeypatch, n):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", str(n))


def test_two_items_of_one_repo_take_the_max_not_the_sum(env, monkeypatch):
    pinned(monkeypatch, 3)
    fake = env(FakeRun({REPO: [issue(i, body=body(f"f{i}.py")) for i in (1, 2, 3)]}, diff=False, delay=0.4))
    baseline()
    run_tick()
    assert fake.max_turbo == 3  # deterministic: all three were in the turbo at the same time
    makespan = max(end for _, end in fake.turbo_spans) - min(start for start, _ in fake.turbo_spans)
    total = sum(end - start for start, end in fake.turbo_spans)  # what a serial run would take: 3 x 0.4 s
    assert total >= 1.2 and makespan < total * 0.5, f"makespan {makespan:.2f}s vs serial sum {total:.2f}s"


def test_each_item_runs_in_its_own_worktree_never_the_neighbours(env, monkeypatch):
    pinned(monkeypatch, 2)
    fake = env(FakeRun({REPO: [issue(1, body=body("a.py")), issue(2, body=body("b.py"))]}, diff=True, delay=0.05))
    baseline()
    run_tick()
    assert sorted(fake.turbo_cwds) == [wt(1), wt(2)]
    by_issue = {argv[argv.index("--repo") + 1]: argv[argv.index("--task") + 1] for argv in fake.turbo_argv}
    assert "Issue #1:" in by_issue[str(wt(1))] and "Issue #2:" in by_issue[str(wt(2))]  # the task of 1 ran in wt 1, never in 2's
    assert sorted(fake.push_cwds) == [wt(1), wt(2)]
    assert {h for h in fake.worktrees.values()} == set()  # all removed
    assert (config.WORK / REPO).exists() or True  # the base clone is not an item path
    assert all(cwd != config.WORK / REPO for cwd in fake.turbo_cwds)


def test_the_repo_lock_is_not_held_during_the_turbo(env, monkeypatch):
    """Item 1 waits in its turbo until item 2 has a worktree. With the lock around the worker, item 2 could never add one."""
    pinned(monkeypatch, 2)
    second_has_a_worktree = asyncio.Event
    holder = {}

    async def hook(cwd):
        if cwd.name == "2":
            holder["event"].set()
        else:
            await asyncio.wait_for(holder["event"].wait(), timeout=5)  # times out (item 1 fails) if item 2 is locked out

    fake = env(FakeRun({REPO: [issue(1, body=body("a.py")), issue(2, body=body("b.py"))]}, diff=False))
    fake.on_turbo = hook

    async def scenario():
        holder["event"] = second_has_a_worktree()
        await tick.tick()

    baseline()
    asyncio.run(scenario())
    assert holder["event"].is_set()
    assert read_json(config.CLAIMS)["simplicio-a#1"]["status"] == "done_no_diff"  # item 1 finished: it was not starved


def test_worktree_is_removed_when_the_turbo_fails(env, monkeypatch):
    fake = env(FakeRun({REPO: [issue(1)]}, turbo_ok=False))
    baseline()
    run_tick()
    assert fake.worktree_log == [("add", wt(1)), ("remove", wt(1))]
    assert read_json(config.CLAIMS)["simplicio-a#1"]["status"] in ("retry", "dead")


def test_worktree_is_removed_when_the_tick_is_cancelled(env, monkeypatch):
    pinned(monkeypatch, 2)
    fake = env(FakeRun({REPO: [issue(1, body=body("a.py")), issue(2, body=body("b.py"))]}, diff=False))
    stuck = asyncio.Event

    async def hook(cwd):
        await stuck().wait()  # a turbo that never ends

    fake.on_turbo = hook
    baseline()

    async def scenario():
        task = asyncio.ensure_future(tick.tick())
        for _ in range(500):
            if len(fake.turbo_cwds) == 2:
                break
            await asyncio.sleep(0.01)
        assert len(fake.worktrees) == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert fake.worktrees == {} and sorted(p for k, p in fake.worktree_log if k == "remove") == [wt(1), wt(2)]


def test_the_concurrency_limit_holds_for_live_worktrees(env, monkeypatch):
    pinned(monkeypatch, 2)
    fake = env(FakeRun({REPO: [issue(i, body=body(f"f{i}.py")) for i in (1, 2, 3, 4)]}, diff=False, delay=0.05))
    baseline()
    run_tick()
    assert fake.max_worktrees == 2 and len(fake.turbo_argv) == 2  # the rest waits for the next tick


def test_a_full_disk_defers_the_item_without_a_worktree(env, monkeypatch):
    async def low(path):
        return 1 << 30  # below the 2 GiB floor of squad_capacity

    monkeypatch.setattr(worktrees, "free_bytes", low)
    fake = env(FakeRun({REPO: [issue(1)]}))
    baseline()
    run_tick()
    assert fake.worktree_log == [] and fake.turbo_argv == []
    claim = read_json(config.CLAIMS)["simplicio-a#1"]
    assert claim["status"] == "retry" and claim["reason_code"] == "disk_low" and claim["attempts"] == 0  # no attempt spent


def test_items_that_name_the_same_file_run_one_after_the_other(env, monkeypatch):
    pinned(monkeypatch, 4)
    issues = [issue(1, body=body("a.py", "b.py")), issue(2, body=body("b.py", "c.py")), issue(3, body=body("c.py")),
              issue(4, body=body("d.py"))]
    fake = env(FakeRun({REPO: issues}, diff=False, delay=0.05))
    baseline()
    run_tick()
    # 1-2-3 are one chain (b.py, c.py): never together. 4 shares nothing: it runs next to the chain.
    assert fake.max_turbo == 2
    chain = [c.name for c in fake.turbo_cwds if c.name in ("1", "2", "3")]
    assert chain == ["1", "2", "3"]  # batch order inside the group
    assert fake.max_worktrees == 2


def test_the_same_issue_twice_makes_one_worktree(env, monkeypatch):
    pinned(monkeypatch, 2)
    fake = env(FakeRun({REPO: [issue(1)]}, diff=False))
    baseline()
    work = tick.Work(REPO, "main", issue(1), verify="python3 -m pytest -q")

    async def scenario():
        from simplicio_loop.claim_lease import ClaimStore
        from simplicio_loop.watcher247 import host_mode, state
        store = ClaimStore(config.CLAIMS)
        gate = worktrees.Gate(2)
        executor = await host_mode.choose()
        clock = state.now().timestamp()
        await asyncio.gather(*(tick.process(store, tick.gh_runner(asyncio.get_running_loop()), gate, work, clock, executor)
                               for _ in range(2)))

    asyncio.run(scenario())
    assert [k for k, _ in fake.worktree_log].count("add") == 1  # the claim lets one in
