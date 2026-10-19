"""Lock-free merge mode through the watcher's squad flow (#1820): the six PRs of test_squads_tick.py, over the watcher's fakes.

The shared FakeRun does not know the impacted-tests script, the merge commit, or a revert PR, so LockfreeRun answers those and
records them. Everything else (review, gate, merge pin, git steps) is the shared fake's.
"""
from __future__ import annotations

import pytest

from simplicio_loop.watcher247 import config, proc

from .fakes import FakeRun, baseline, issue, read_json, run_tick

REPO = "simplicio-a"
FULL = "simpletibr/simplicio-a"
NUMBERS = range(1, 7)
AUTO = "SIMPLICIO_247_AUTO_MERGE"
MODE = "SIMPLICIO_247_MERGE_MODE"


class LockfreeRun(FakeRun):
    """The watcher's fake, plus the calls lock-free mode makes. `pytest_green`: one verdict per post-merge run, in order."""

    def __init__(self, *args, pytest_green=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.pytest_green = list(pytest_green)
        self.impacted = []

    async def __call__(self, argv, timeout=120, cwd=None, stdin=None, env=None):
        argv = list(argv)
        if argv[:2] == ["python3", "scripts/impact_tests.py"]:
            self.calls.append(argv)
            self.impacted.append(argv)
            return proc.Result(0, "tests/test_m.py\n")
        if argv[:3] == ["python3", "-m", "pytest"]:
            self.calls.append(argv)
            self.tests_run += 1
            green = self.pytest_green.pop(0) if self.pytest_green else True
            return proc.Result(0 if green else 1, "" if green else "FAILED tests/test_m.py::test_feature - boom\n")
        if argv[:2] == ["git", "rev-parse"]:
            self.calls.append(argv)
            return proc.Result(0, "5" * 40 + "\n")
        if argv[:2] == ["gh", "api"] and any("/pulls/" in a for a in argv) and "--jq" in argv:
            self.calls.append(argv)  # the merge commit of a merged PR
            number = int(next(a for a in argv if "/pulls/" in a).rpartition("/")[2])
            return proc.Result(0, f"{number:040x}\n")
        if argv[:3] == ["gh", "api", "-X"] and "POST" in argv and any(a.endswith(("/pulls", "/issues")) for a in argv):
            self.calls.append(argv)  # a revert PR or a fix task; the lifecycle comments (issues/N/comments) go to the shared fake
            route = "pull/900" if any(a.endswith("/pulls") for a in argv) else "issues/901"
            return proc.Result(0, f"https://github.com/simpletibr/simplicio-a/{route}\n")
        return await super().__call__(argv, timeout=timeout, cwd=cwd, stdin=stdin, env=env)

    def posts(self, route):
        return [c for c in self.calls if c[:3] == ["gh", "api", "-X"] and "POST" in c and any(a.endswith(route) for a in c)]

    def pushes(self):
        return [c for c in self.calls if c[:2] == ["git", "push"]]


def _view(number, *, approved_after_commit=True, author="squad-bot"):
    commit, approval = "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"
    reviewed = oid(number) if approved_after_commit else "f" * 40
    return {
        "files": [{"path": f"src/m{number}/app.py"}], "headRefOid": oid(number),
        "commits": [{"oid": oid(number), "committedDate": commit, "messageHeadline": "loop: x"}],
        "comments": [{"id": number, "createdAt": approval, "author": {"login": author}, "authorAssociation": "MEMBER",
                      "body": f"REVISÃO AUTOMÁTICA: APROVADA (nível 1)\n\n<!-- simplicio-loop:squad-approval:{reviewed} -->"}],
    }


def oid(number):
    return f"{number:040x}"


@pytest.fixture
def six(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "6")
    monkeypatch.delenv(AUTO, raising=False)
    monkeypatch.delenv(MODE, raising=False)
    (config.WORK / FULL / ".git").mkdir(parents=True)

    def make(**kwargs):
        rows = [issue(n, f"Task {n}", body=f"Ajustar `src/m{n}/app.py` para o fluxo do watcher seguir o contrato descrito abaixo.")
                for n in NUMBERS]
        fake = env(LockfreeRun({REPO: rows}, distinct_prs=True, pr_views={100 + n: _view(n) for n in NUMBERS}, **kwargs))
        baseline()
        return fake
    return make


def _squads():
    return read_json(config.STATUS)["squads"][FULL]


def test_the_default_mode_is_batch_and_the_status_says_so(six, monkeypatch):
    monkeypatch.setenv(AUTO, "1")
    fake = six()
    run_tick()
    assert _squads()["merge_mode"] == "batch"
    assert fake.merges == [101, 102, 103, 104, 105, 106]
    assert fake.tests_run == 2 and fake.impacted == []  # one cumulative test per batch of four, as before


def test_lockfree_merges_each_approved_pr_then_checks_main_one_at_a_time(six, monkeypatch):
    monkeypatch.setenv(AUTO, "1")
    monkeypatch.setenv(MODE, "lockfree")
    fake = six()
    fake.pr_views[103] = _view(3, approved_after_commit=False)  # the gate says no: this PR stays
    run_tick()
    assert _squads()["merge_mode"] == "lockfree"
    assert fake.merges == [101, 102, 104, 105, 106]
    assert len(fake.impacted) == 5 and fake.tests_run == 5  # one impacted run on main per merge, never one batch test
    assert _squads()["gate_blocked"] == [103]
    assert _squads()["lockfree"]["red"] is None and _squads()["lockfree"]["actions"] == []


def test_lockfree_with_every_approval_from_an_outsider_merges_nothing(six, monkeypatch):
    """The approval gate is the same in both modes: no authorized approval, no merge, no post-merge run."""
    monkeypatch.setenv(AUTO, "1")
    monkeypatch.setenv(MODE, "lockfree")
    fake = six()
    fake.pr_views = {pr: _view(pr - 100, author="outsider") for pr in fake.pr_views}
    run_tick()
    assert fake.merges == [] and fake.impacted == [] and fake.tests_run == 0
    assert _squads()["gate_blocked"] == [101, 102, 103, 104, 105, 106]


def test_lockfree_red_after_a_merge_opens_one_revert_pr_stops_the_tick_and_merges_no_revert(six, monkeypatch):
    monkeypatch.setenv(AUTO, "1")
    monkeypatch.setenv(MODE, "lockfree")
    fake = six(pytest_green=[True, False])  # 101's post-merge run is green, 102's is red
    run_tick()
    assert fake.merges == [101, 102]  # nothing after the red one merges in this tick
    assert len(fake.posts("/pulls")) == 1  # exactly one revert PR
    assert fake.posts("/issues") == []
    assert all(c[3] in ("101", "102") for c in fake.calls if c[:3] == ["gh", "pr", "merge"])  # the revert is never merged
    pushes = fake.pushes()
    assert pushes and not any(a in ("-f", "--force", "--force-with-lease") or a.startswith(("--force", "+"))
                              for c in pushes for a in c)
    lockfree = _squads()["lockfree"]
    assert lockfree["red"]["pr"] == 102
    assert [a["kind"] for a in lockfree["actions"]] == ["open_revert_pr"]
    assert {"104", "105", "106"} <= set(lockfree["refused"]) and "red" in lockfree["refused"]["104"]
