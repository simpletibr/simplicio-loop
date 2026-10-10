"""The REAL squad_review.evaluate on a clone with a local origin: fetch, head check, gate, independent marker (Parte de #1649).

The autouse fake of tests/conftest.py is off for this module (marker); only gh, the sandbox and the gate's inputs are faked.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.review_gate import identity, isolation
from simplicio_loop.review_gate import gate as review_gate
from simplicio_loop.watcher247 import config, proc, sandbox, squad_review
from simplicio_loop.watcher247.squad_review import ReviewError
from tests.review_gate import scenario

pytestmark = pytest.mark.real_squad_review
_REAL_MAKE_JAIL = isolation.make_jail

WORKER = identity.Agent("worker-1", "worker", "haiku-5.5", "local")
MARKER = ("Revisão feita.\n\nREVISÃO INDEPENDENTE: APROVADA\nrevisor: rev-9\npapel: independent-reviewer\n"
          "modelo: opus-5.5\nhost: other-host\nhead: {head}\n")


class FakeGh:
    """Stands in for `squad_review._gh`: answers `pr view` and `issue view` and records the argv."""

    def __init__(self, comments=(), pr_body="PR body", issue_body="Issue body", with_comments=True):
        self.comments, self.pr_body, self.issue_body, self.with_comments, self.calls = list(comments), pr_body, issue_body, with_comments, []

    async def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:2] == ["pr", "view"]:
            return {"body": self.pr_body, **({"comments": self.comments} if self.with_comments else {})}
        if argv[:2] == ["issue", "view"]:
            return {"body": self.issue_body}
        raise AssertionError(f"unexpected gh call {argv}")


def _git(where: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=where, check=True, capture_output=True, text=True).stdout.strip()


class World:
    def __init__(self, tmp_path: Path, name: str):
        (tmp_path / "src").mkdir()
        src, self.base, self.head = scenario.make_repo(tmp_path / "src", name)
        self.origin = tmp_path / "origin.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(src), str(self.origin)], check=True)
        (tmp_path / "work").mkdir()
        self.dest = tmp_path / "work" / "myrepo"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.dest)], check=True)
        self.state = tmp_path / "state"
        self.state.mkdir()


@pytest.fixture
def world(tmp_path, monkeypatch):
    made = World(tmp_path, "notest")  # a head the gate rejects without running a test: fast
    monkeypatch.setattr(config, "WORK", tmp_path / "work")
    monkeypatch.setattr(config, "ORG", "org")
    monkeypatch.setattr(config, "ROOT", made.state)
    monkeypatch.setattr(isolation, "make_jail", scenario.unsandboxed_jail)  # the jail has its own tests; the host may have no bwrap
    return made


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(squad_review, "_gh", fake)
    return fake


def _evaluate(head, lock=None, author=WORKER, number=11, issue=7):
    return asyncio.run(squad_review.evaluate("myrepo", number, issue, head, author, lock or asyncio.Lock()))


# --- evaluate ---------------------------------------------------------------------------------------------------------

def test_evaluate_fetches_the_branch_runs_the_gate_and_returns_the_report_of_that_head(world, gh):
    report, independent = _evaluate(world.head)
    assert independent is None
    assert (report.pr, report.issue, report.head) == (11, 7, world.head)
    assert [c.name for c in report.checks] == ["redgreen", "mutation", "usage", "coverage", "docs", "identity"]
    assert not report.approved  # no test for the change
    saved = world.dest / ".simplicio-loop" / "review-gate" / f"pr-11-{world.head[:7]}.json"
    assert json.loads(saved.read_text(encoding="utf-8"))["head"] == world.head
    assert gh.calls == [["pr", "view", "11", "--repo", "org/myrepo", "--json", "body,comments"],
                        ["issue", "view", "7", "--repo", "org/myrepo", "--json", "body"]]


def test_without_bwrap_evaluate_returns_a_report_rejected_with_sandbox_unavailable_never_an_unsandboxed_run(world, gh, monkeypatch):
    monkeypatch.setattr(isolation, "make_jail", _REAL_MAKE_JAIL)
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: None)
    monkeypatch.setenv(sandbox.OPT_OUT, "1")
    report, _ = _evaluate(world.head)
    assert not report.approved and [c.name for c in report.checks] == ["sandbox"]
    assert report.checks[0].reasons[0].startswith("sandbox_unavailable: ")


def test_evaluate_gives_the_gate_the_bodies_the_merge_base_the_author_and_the_state_dir_for_its_jail(world, monkeypatch):
    gh = FakeGh(comments=[{"body": MARKER.format(head=world.head), "authorAssociation": "OWNER"}], pr_body="Parte de #7", issue_body="- [ ] algo")
    monkeypatch.setattr(squad_review, "_gh", gh)
    seen, held = {}, []
    lock = asyncio.Lock()

    def fake_gate(inp):
        seen["inp"] = inp
        held.append(lock.locked())
        return "report"

    monkeypatch.setattr(review_gate, "run_gate", fake_gate)
    out = _evaluate(world.head, lock)
    inp, rev = seen["inp"], identity.Agent("rev-9", "independent-reviewer", "opus-5.5", "other-host")
    assert out == ("report", rev)
    assert (inp.repo, inp.pr, inp.issue, inp.base, inp.head) == (world.dest, 11, 7, world.base, world.head)
    assert (inp.issue_body, inp.pr_body, inp.author, inp.independent) == ("- [ ] algo", "Parte de #7", WORKER, rev)
    assert held == [True] and not lock.locked()  # worktrees are added and removed under the lock, which is released after
    assert inp.wrap_for is None and inp.state_dir == world.state  # the gate's own jail; the state dir of the watcher stays read-only in it


def test_evaluate_refuses_a_head_that_is_not_the_tip_of_the_branch(world, gh):
    with pytest.raises(ReviewError) as caught:
        _evaluate(world.base)  # a stale head: the branch has moved on
    assert str(caught.value) == f"branch loop/issue-7 is at {world.head[:7]}, not at the reviewed head {world.base[:7]}"


def test_evaluate_accepts_only_the_full_40_character_sha_of_the_tip(world, gh):
    assert _evaluate(world.head)[0].head == world.head
    for short in (world.head[:7], world.head[:12], world.head[:39], world.head.upper()):
        with pytest.raises(ReviewError, match="full 40-character"):
            _evaluate(short)


def test_a_clone_without_the_remote_tracking_ref_of_the_pr_branch_is_reviewed_all_the_same(world, gh):
    """Found in the wild: `git rev-parse origin/loop/issue-N` failed with 'ambiguous argument' in a base clone that never fetched the branch."""
    _git(world.dest, "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/main")
    _git(world.dest, "update-ref", "-d", "refs/remotes/origin/loop/issue-7")
    _git(world.dest, "update-ref", "-d", "refs/remotes/origin/main")
    gone = subprocess.run(["git", "rev-parse", "--verify", "-q", "origin/loop/issue-7"], cwd=world.dest, capture_output=True)
    assert gone.returncode != 0  # the clone really lacks the ref
    report, _ = _evaluate(world.head)
    assert report.head == world.head
    assert _git(world.dest, "rev-parse", "refs/remotes/origin/loop/issue-7") == world.head  # fetched explicitly into the ref the gate reads


def test_a_single_branch_clone_whose_refspec_never_lists_the_pr_branch_is_reviewed_too(world, gh):
    _git(world.dest, "config", "--unset-all", "remote.origin.fetch")
    _git(world.dest, "update-ref", "-d", "refs/remotes/origin/loop/issue-7")
    assert _evaluate(world.head)[0].head == world.head


def test_a_branch_that_does_not_exist_on_origin_is_a_review_error_with_the_cause_never_an_ambiguous_revision(world, gh):
    with pytest.raises(ReviewError) as caught:
        asyncio.run(squad_review.evaluate("myrepo", 11, 99, world.head, WORKER, asyncio.Lock()))  # no loop/issue-99 on origin
    assert str(caught.value).startswith("git fetch --depth 200 failed: ") and "ambiguous" not in str(caught.value)


def test_a_failing_gh_raises_review_error_with_the_cause(world, monkeypatch):
    real = proc.run

    async def fake(argv, **kw):
        if argv[0] == "gh":
            return proc.Result(1, "", "HTTP 401: Bad credentials\n")
        return await real(argv, **kw)

    monkeypatch.setattr(proc, "run", fake)
    with pytest.raises(ReviewError, match=r"^gh pr view 11 failed: HTTP 401: Bad credentials$"):
        _evaluate(world.head)


def test_a_failing_issue_view_names_the_issue_call(world, monkeypatch):
    async def fake(argv, **kw):
        if argv[:3] == ["gh", "pr", "view"]:
            return proc.Result(0, json.dumps({"body": "x", "comments": []}))
        return proc.Result(1, "issue is gone", "")

    monkeypatch.setattr(proc, "run", fake)
    with pytest.raises(ReviewError, match=r"^gh issue view 7 failed: issue is gone$"):
        _evaluate(world.head)


def test_a_git_failure_raises_review_error_with_the_command_and_the_cause(world, gh):
    subprocess.run(["git", "remote", "set-url", "origin", str(world.origin) + ".gone"], cwd=world.dest, check=True)
    with pytest.raises(ReviewError) as caught:
        _evaluate(world.head)
    assert str(caught.value).startswith("git fetch --depth 200 failed: ") and "gone" in str(caught.value)


def test_the_lock_is_released_when_the_review_fails(world, gh):
    lock = asyncio.Lock()
    with pytest.raises(ReviewError):
        _evaluate(world.base, lock)
    assert not lock.locked()


def test_a_comment_with_the_independent_marker_for_this_head_fills_independent(world, monkeypatch):
    comments = [{"body": "só um comentário"}, {"body": MARKER.format(head=world.head)}]
    monkeypatch.setattr(squad_review, "_gh", FakeGh(comments=comments))
    report, independent = _evaluate(world.head)
    assert independent == identity.Agent("rev-9", "independent-reviewer", "opus-5.5", "other-host")
    assert next(c for c in report.checks if c.name == "identity").measured["independent"] == "rev-9"


def test_a_marker_with_a_seven_character_sha_does_not_fill_independent(world, monkeypatch):
    assert len(world.head) == 40
    monkeypatch.setattr(squad_review, "_gh", FakeGh(comments=[{"body": MARKER.format(head=world.head[:7])}]))
    assert _evaluate(world.head)[1] is None  # an approval for a prefix is not an approval for the commit


def test_a_marker_for_another_head_or_no_comments_leaves_independent_empty(world, monkeypatch):
    monkeypatch.setattr(squad_review, "_gh", FakeGh(comments=[{"body": MARKER.format(head="abcdef0")}]))
    assert _evaluate(world.head)[1] is None
    monkeypatch.setattr(squad_review, "_gh", FakeGh())
    assert _evaluate(world.head)[1] is None


def test_a_gh_answer_without_comments_or_with_null_bodies_is_not_a_crash(world, monkeypatch):
    seen = {}
    monkeypatch.setattr(squad_review, "_gh", FakeGh(pr_body=None, issue_body=None, with_comments=False))
    monkeypatch.setattr(review_gate, "run_gate", lambda inp: seen.setdefault("inp", inp) and "report")
    assert _evaluate(world.head) == ("report", None)
    assert (seen["inp"].issue_body, seen["inp"].pr_body) == ("", "")


def test_evaluate_runs_exactly_these_git_commands_in_the_clone_with_a_timeout(world, gh, monkeypatch):
    real, seen = proc.run, []

    async def spy(argv, **kw):
        seen.append((list(argv), kw))
        return await real(argv, **kw)

    monkeypatch.setattr(proc, "run", spy)
    monkeypatch.setattr(review_gate, "run_gate", lambda inp: "report")
    _evaluate(world.head)
    argvs = [a for a, _ in seen]
    assert ["git", "fetch", "--depth", "200", "origin", "+refs/heads/main:refs/remotes/origin/main",
            "+refs/heads/loop/issue-7:refs/remotes/origin/loop/issue-7"] in argvs
    assert ["git", "rev-parse", "--verify", "refs/remotes/origin/loop/issue-7^{commit}"] in argvs
    assert argvs[-1] == ["git", "merge-base", "refs/remotes/origin/main", world.head]
    assert all(a[:2] != ["git", "push"] for a in argvs) and all(kw == {"cwd": world.dest, "timeout": 180} for _, kw in seen)


def test_the_gate_runs_in_a_thread_so_the_event_loop_keeps_turning(world, gh, monkeypatch):
    import time
    monkeypatch.setattr(review_gate, "run_gate", lambda inp: time.sleep(0.4) or "report")
    ticks = []

    async def main():
        async def ticker():
            while True:
                ticks.append(1)
                await asyncio.sleep(0.02)

        task = asyncio.create_task(ticker())
        out = await squad_review.evaluate("myrepo", 11, 7, world.head, WORKER, asyncio.Lock())
        task.cancel()
        return out

    assert asyncio.run(main()) == ("report", None)
    assert len(ticks) >= 5  # a gate run on the loop thread would leave one tick


# --- _gh and _git -----------------------------------------------------------------------------------------------------

def test_gh_parses_the_json_and_runs_gh_with_a_timeout(monkeypatch):
    seen = []

    async def fake(argv, **kw):
        seen.append((argv, kw))
        return proc.Result(0, '{"body": "ok"}')

    monkeypatch.setattr(proc, "run", fake)
    assert asyncio.run(squad_review._gh(["pr", "view", "3"])) == {"body": "ok"}
    assert seen == [(["gh", "pr", "view", "3"], {"timeout": 60})]


def test_gh_failure_uses_stderr_then_stdout_and_keeps_the_last_200_chars(monkeypatch):
    results = iter([proc.Result(1, "from stdout", ""), proc.Result(2, "ignored", "from stderr"), proc.Result(1, "", "x" * 300 + "END")])

    async def fake(argv, **kw):
        return next(results)

    monkeypatch.setattr(proc, "run", fake)
    run = lambda: asyncio.run(squad_review._gh(["issue", "view", "3", "--repo", "a/b"]))  # noqa: E731
    with pytest.raises(ReviewError) as first:
        run()
    assert str(first.value) == "gh issue view 3 failed: from stdout"
    with pytest.raises(ReviewError) as second:
        run()
    assert str(second.value) == "gh issue view 3 failed: from stderr"
    with pytest.raises(ReviewError) as third:
        run()
    assert str(third.value) == "gh issue view 3 failed: " + "x" * 197 + "END"


def test_gh_with_an_answer_that_is_not_json_is_a_review_error(monkeypatch):
    async def fake(argv, **kw):
        return proc.Result(0, "<html>rate limited</html>")

    monkeypatch.setattr(proc, "run", fake)
    with pytest.raises(ReviewError, match=r"^gh pr view 3 returned invalid json$"):
        asyncio.run(squad_review._gh(["pr", "view", "3"]))


def test_git_failure_uses_stderr_then_stdout_and_keeps_the_last_200_chars(monkeypatch, tmp_path):
    results = iter([proc.Result(1, "from stdout", ""), proc.Result(128, "ignored", "from stderr\n"), proc.Result(1, "", "y" * 300 + "END")])

    async def fake(argv, **kw):
        return next(results)

    monkeypatch.setattr(proc, "run", fake)
    messages = []
    for _ in range(3):
        with pytest.raises(ReviewError) as caught:
            asyncio.run(squad_review._git(tmp_path, "fetch", "--depth", "9", "origin"))
        messages.append(str(caught.value))
    assert messages == ["git fetch --depth 9 failed: from stdout", "git fetch --depth 9 failed: from stderr",
                        "git fetch --depth 9 failed: " + "y" * 197 + "END"]


def test_git_returns_the_stripped_output_in_the_given_dir_and_names_the_failure(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    assert asyncio.run(squad_review._git(tmp_path, "rev-parse", "--is-inside-work-tree")) == "true"
    assert asyncio.run(squad_review._git(tmp_path, "rev-parse", "--show-toplevel")) == str(tmp_path.resolve())
    with pytest.raises(ReviewError) as caught:
        asyncio.run(squad_review._git(tmp_path, "rev-parse", "--verify", "refs/heads/nope", "extra"))
    assert str(caught.value).startswith("git rev-parse --verify refs/heads/nope failed: ")
