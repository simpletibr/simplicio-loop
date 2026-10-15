"""Lock-free merge mode (#1820): the decision, the post-merge check and the revert PR.

Everything runs over fakes. FakeRun stands in for watcher247.proc.run (the one subprocess boundary) and records every argv,
so no git, gh or network is touched.
"""

import asyncio
from pathlib import Path

from simplicio_loop import merge_lockfree as lf

REPO = "simpletibr/simplicio-loop"
HEAD = "a" * 40
PULLS = f"repos/{REPO}/pulls"
ISSUES = f"repos/{REPO}/issues"


class FakeRun:
    def __init__(self, answers=()):
        self.calls = []
        self.answers = list(answers)  # (substring, Result): the first substring found in the joined argv wins

    async def __call__(self, argv, *, timeout=120, cwd=None, env=None, stdin=None):
        self.calls.append(list(argv))
        line = " ".join(argv)
        for needle, result in self.answers:
            if needle in line:
                return result
        return lf.Result(0, "", "")

    def pr_merges(self):
        return [c for c in self.calls if c[:3] == ["gh", "pr", "merge"]]

    def posts(self, route):
        return [c for c in self.calls if c[:3] == ["gh", "api", "-X"] and "POST" in c and f"repos/{REPO}/{route}" in c]

    def pushes(self):
        return [c for c in self.calls if c[:2] == ["git", "push"]]


def pr(number, files=("a.py",), approved=True, tests_green=True, reason="", squad="squad-1"):
    return lf.PRState(pr=number, issue=number, head=HEAD, files=frozenset(files), approved=approved,
                      gate_reason=reason, tests_green=tests_green, squad=squad)


def forge_for(run, tmp_path: Path):
    return lf.Forge(REPO, tmp_path, run)


# (d) lockfree never merges without the approval gate

def test_lockfree_refuses_a_pr_without_an_authorized_approval():
    d = lf.decide_merge(pr(5, approved=False, reason="unauthorized_approval"), {})
    assert d.action == "refuse"
    assert "unauthorized_approval" in d.reason


def test_lockfree_refuses_a_pr_whose_targeted_tests_are_not_green():
    d = lf.decide_merge(pr(5, tests_green=False), {})
    assert d.action == "refuse" and "tests" in d.reason


def test_lockfree_merges_an_approved_green_pr_with_nothing_unverified():
    assert lf.decide_merge(pr(5), {}).action == "merge"


def test_lockfree_without_approval_merges_nothing_in_a_whole_pass(tmp_path):
    run = FakeRun()
    forge = forge_for(run, tmp_path)
    report = asyncio.run(lf.merge_pass([pr(5, approved=False, reason="gate"), pr(6, approved=False, reason="gate")],
                                       merge=forge.merge, check=None, on_red=None))
    assert report.merged == [] and set(report.refused) == {5, 6}
    assert run.pr_merges() == []


# (a) two PRs on the same file: the second waits (or is refused) with a reason, never silently overwritten

def test_a_second_pr_on_a_file_still_unverified_waits_with_a_reason():
    d = lf.decide_merge(pr(6, files=("a.py",)), {5: frozenset({"a.py"})})
    assert d.action == "wait" and "#5" in d.reason


def test_a_pr_on_other_files_merges_while_another_merge_is_unverified():
    assert lf.decide_merge(pr(6, files=("b.py",)), {5: frozenset({"a.py"})}).action == "merge"


def test_two_prs_on_one_file_the_second_waits_and_its_merge_is_never_called():
    merged = []

    async def merge(number, head):
        merged.append(number)
        return f"sha{number}"

    async def check(number, sha):  # the post-merge run did not finish: the merge is unverified, not red
        return lf.PostMerge("pending", reason="timeout")

    async def on_red(red):  # pragma: no cover - must not run: nothing is red
        raise AssertionError("no red expected")

    report = asyncio.run(lf.merge_pass([pr(5, files=("a.py",)), pr(6, files=("a.py",))], merge=merge, check=check, on_red=on_red))
    assert merged == [5]
    assert list(report.pending) == [5]
    assert report.waited.keys() == {6} and "#5" in report.waited[6]
    assert report.refused == {}


def test_a_green_post_merge_check_releases_the_file_for_the_next_pr():
    merged = []

    async def merge(number, head):
        merged.append(number)
        return f"sha{number}"

    async def check(number, sha):
        return lf.PostMerge("green", tests=("tests/test_a.py",))

    report = asyncio.run(lf.merge_pass([pr(5, files=("a.py",)), pr(6, files=("a.py",))], merge=merge, check=check,
                                       on_red=lambda red: None))
    assert merged == [5, 6] and report.waited == {}


# (b) post-merge red: exactly one revert PR, nothing merged or force-pushed, and no further lock-free merge this tick

def test_post_merge_red_opens_exactly_one_revert_pr_and_never_merges_or_forces(tmp_path):
    run = FakeRun([
        (f"{PULLS}/5 --jq .merge_commit_sha", lf.Result(0, "c0ffee1\n")),
        (f"-X POST {PULLS}", lf.Result(0, "https://github.com/simpletibr/simplicio-loop/pull/77\n")),
    ])
    forge = forge_for(run, tmp_path)

    async def check(number, sha):
        return lf.PostMerge("red", failing=("tests/test_feat.py::test_a",))

    async def on_red(red):
        return await lf.on_red(red, policy=lf.RED_POLICY, forge=forge)

    report = asyncio.run(lf.merge_pass([pr(5), pr(6, files=("b.py",))], merge=forge.merge, check=check, on_red=on_red))

    assert report.merged == [5]
    assert [a.kind for a in report.actions] == ["open_revert_pr"]
    assert report.actions[0].url.endswith("/pull/77")
    assert len(run.posts("pulls")) == 1  # exactly one revert PR
    assert [c[3] for c in run.pr_merges()] == ["5"]  # the only merge is the original PR, never the revert
    assert not any(a in ("-f", "--force", "--force-with-lease", "--force-if-includes") or a.startswith(("--force", "+"))
                   for c in run.pushes() for a in c)  # the revert branch is pushed, never forced
    assert any(c[:2] == ["git", "revert"] for c in run.calls)
    assert 6 in report.refused and "red" in report.refused[6]


def test_revert_conflict_falls_back_to_one_fix_task_and_still_never_merges(tmp_path):
    run = FakeRun([
        ("git revert --no-edit", lf.Result(1, "", "CONFLICT")),
        (f"-X POST {ISSUES}", lf.Result(0, "https://github.com/simpletibr/simplicio-loop/issues/88\n")),
    ])
    forge = forge_for(run, tmp_path)
    red = lf.Red(pr=5, issue=5, squad="squad-1", merge_sha="c0ffee1", failing=("tests/test_feat.py::test_a",))
    action = asyncio.run(lf.on_red(red, policy="revert", forge=forge))
    assert action.kind == "open_fix_task" and action.url.endswith("/issues/88")
    assert any("squad-1" in a for a in run.posts("issues")[0])  # the fix task names the owning squad
    assert run.posts("pulls") == [] and run.pr_merges() == []
    assert any(c[:3] == ["git", "revert", "--abort"] for c in run.calls)


def test_policy_fix_opens_a_fix_task_for_the_owning_squad_and_no_revert(tmp_path):
    run = FakeRun([(f"-X POST {ISSUES}", lf.Result(0, "https://github.com/simpletibr/simplicio-loop/issues/89\n"))])
    forge = forge_for(run, tmp_path)
    red = lf.Red(pr=5, issue=5, squad="squad-2", merge_sha="c0ffee1", failing=("tests/test_feat.py::test_a",))
    action = asyncio.run(lf.on_red(red, policy="fix", forge=forge))
    assert action.kind == "open_fix_task"
    assert not any(c[:2] == ["git", "revert"] for c in run.calls)
    assert run.posts("pulls") == [] and run.pr_merges() == []


def test_the_revert_pr_is_a_pr_for_a_human_or_the_coordinator_to_merge(tmp_path):
    run = FakeRun([(f"-X POST {PULLS}", lf.Result(0, "https://github.com/simpletibr/simplicio-loop/pull/77\n"))])
    forge = forge_for(run, tmp_path)
    url = asyncio.run(forge.open_revert(5, "c0ffee1", "Revert #5", "body"))
    assert url.endswith("/pull/77")
    assert run.pr_merges() == []  # opening the revert never merges it


# post-merge check: impacted tests on main

def test_post_merge_check_runs_the_impacted_tests_and_names_the_failing_ones():
    async def impacted(sha):
        return ["tests/test_a.py"]

    async def run_tests(tests, sha):
        assert tests == ["tests/test_a.py"]
        return False, ["tests/test_a.py::test_x"]

    result = asyncio.run(lf.post_merge_check("c0ffee1", impacted=impacted, run_tests=run_tests))
    assert result.status == "red"
    assert result.failing == ("tests/test_a.py::test_x",)
    assert result.tests == ("tests/test_a.py",)


def test_post_merge_check_with_no_impacted_test_runs_the_full_verify():
    seen = []

    async def impacted(sha):
        return None  # no impacted-tests tool, or an empty selection

    async def run_tests(tests, sha):
        seen.append(tests)
        return True, []

    result = asyncio.run(lf.post_merge_check("c0ffee1", impacted=impacted, run_tests=run_tests))
    assert result.status == "green" and seen == [None]


def test_post_merge_check_that_cannot_run_is_pending_not_red():
    async def impacted(sha):
        raise TimeoutError("no answer")

    async def run_tests(tests, sha):  # pragma: no cover
        raise AssertionError("not reached")

    result = asyncio.run(lf.post_merge_check("c0ffee1", impacted=impacted, run_tests=run_tests))
    assert result.status == "pending"


def test_parse_failing_reads_pytest_short_summary_lines():
    out = "FAILED tests/test_a.py::test_x - assert 1 == 2\nFAILED tests/test_b.py::test_y\n3 failed\n"
    assert lf.parse_failing(out) == ("tests/test_a.py::test_x", "tests/test_b.py::test_y")


# (c) the default is batch; lockfree is only the exact value

def test_the_default_mode_is_batch_and_only_the_exact_value_turns_lockfree_on():
    assert lf.mode_from_env({}) == "batch"
    assert lf.mode_from_env({lf.MODE_ENV: "batch"}) == "batch"
    assert lf.mode_from_env({lf.MODE_ENV: "lockfree"}) == "lockfree"
    for junk in ("LOCKFREE", "lock-free", "1", " lockfree"):
        assert lf.mode_from_env({lf.MODE_ENV: junk}) == "batch"
