"""`simplicio-loop squads run` (#1829): execute a planned wave with fakes only (no model call, no network).

Git is real: each test builds a throwaway repository with a bare `origin`, so worktrees, commits and `git push`
run for real. The worker launcher, the tests, the PR host (gh) and the post-merge verify are injected fakes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import cli_impl, merge_lockfree, squads, squads_run as sr

ISSUES2 = [
    {"number": 1, "title": "api change", "body": "edit the api", "area": "api", "paths": ["api/a.py"]},
    {"number": 2, "title": "web change", "body": "edit the web", "area": "web", "paths": ["web/b.py"]},
]
ISSUES3 = ISSUES2 + [
    {"number": 3, "title": "docs", "body": "write the docs", "area": "docs", "paths": ["docs/c.py"]},
]
ISSUES3[0] = {**ISSUES3[0], "depends_on": [3]}  # api waits for docs: merge order becomes 2, 3, 1


def _plan(issues):
    return json.loads(json.dumps(squads.plan_squads(issues).to_dict()))


def _git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "repo"
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    _git(work, "config", "user.email", "tester@example.invalid")
    _git(work, "config", "user.name", "tester")
    for folder in ("api", "web", "docs"):
        (work / folder).mkdir()
    (work / "api" / "a.py").write_text("A = 0\n", encoding="utf-8")
    (work / "web" / "b.py").write_text("B = 0\n", encoding="utf-8")
    (work / "docs" / "c.py").write_text("C = 0\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "-q", "-u", "origin", "main")
    return work


class FakeHosting:
    """`push` is a real `git push` to the local origin. PRs, approvals and merges live in memory (no gh)."""

    def __init__(self, repo, approve_all=False):
        self.repo = repo
        self.approve_all = approve_all
        self.pushed = []
        self.prs = {}
        self.merged = []
        self._next = 100

    def push(self, worktree, branch):
        done = subprocess.run(["git", "push", "-u", "origin", branch], cwd=str(worktree), capture_output=True, text=True)
        if done.returncode:
            raise sr.RunError("push refused: " + done.stderr.strip())
        self.pushed.append(branch)

    def open_pr(self, branch, title, body):
        self._next += 1
        self.prs[self._next] = {"branch": branch, "head": _git(self.repo, "rev-parse", branch)}
        return self._next

    def gate(self, pr, approvers):
        info = self.prs[pr]
        comments = []
        if self.approve_all:  # an approval by "wesley" on this exact head, as a review comment would carry it
            comments.append({"id": pr, "author": {"login": "wesley"}, "authorAssociation": "NONE",
                             "createdAt": "2026-10-16T10:00:00Z",
                             "body": "REVISÃO AUTOMÁTICA: APROVADA (nível 0)\n\n"
                                     f"<!-- simplicio-loop:squad-approval:{info['head']} -->"})
        view = {"commits": [{"oid": info["head"], "messageHeadline": "squad"}], "comments": comments, "files": []}
        return squads.squad_gate(view, approvers)

    def merge(self, pr, head):
        self.merged.append(pr)
        return f"{pr:040x}"


def _writer(*paths, text="# worked\n"):
    def launch(request):
        for rel in paths:
            target = request.worktree / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return sr.WorkerOutcome("done")
    return launch


def _table(**by_squad):
    """Launcher that dispatches on the squad id and records every request."""
    calls = []

    def launch(request):
        calls.append(request)
        return by_squad[request.squad](request)

    launch.calls = calls
    return launch


def _deps(launcher, hosting, tester=None, verify=None):
    return sr.Deps(launcher=launcher, tester=tester or (lambda path: (True, "3 passed")), hosting=hosting,
                   verify=verify or (lambda sha: (True, "")))


def _run(plan, repo, tmp_path, deps, **kwargs):
    kwargs.setdefault("execute", True)
    return sr.run_plan(plan, repo=repo, run_dir=tmp_path / "run", deps=deps, **kwargs)


def _branch(plan, squad):
    return f"squads/{sr.plan_id(plan)}/{squad}"


# ---------------------------------------------------------------------------------------------- (a) dry run


def test_dry_run_prints_the_preview_and_spawns_nothing(repo, tmp_path):
    launcher = _table()  # any call would raise KeyError
    hosting = FakeHosting(repo)
    shown = []
    result = sr.run_plan(_plan(ISSUES2), repo=repo, run_dir=tmp_path / "run", deps=_deps(launcher, hosting),
                         on_preview=shown.append)

    assert result["status"] == "DRY_RUN"
    assert launcher.calls == [] and hosting.pushed == [] and hosting.merged == []
    assert not (tmp_path / "run").exists()
    assert _git(repo, "branch", "--list", "squads/*") == ""
    text = sr.format_preview(shown[0])
    assert "sq-api" in text and "api/a.py" in text and "merge order" in text.lower()
    assert "claude -p --model" in text and "worktree add -b" in text


# ---------------------------------------------------------------------------------------------- (b) ownership


def test_a_worker_editing_outside_its_ownership_is_stopped_and_not_merged(repo, tmp_path):
    launcher = _table(**{
        "sq-api": _writer("api/a.py", "web/new.py"),  # web/new.py is untracked and belongs to nobody here
        "sq-web": _writer("web/b.py"),
    })
    hosting = FakeHosting(repo, approve_all=True)
    result = _run(_plan(ISSUES2), repo, tmp_path, _deps(launcher, hosting), approvers=["wesley"])

    api = result["squads"]["sq-api"]
    assert api["status"] == "blocked" and api["reason_kind"] == "ownership"
    assert api["offending"] == ["web/new.py"]
    assert "web/new.py" in result["reason"] and "sq-api" in result["next"]
    assert result["squads"]["sq-web"]["status"] == "merged"
    assert _branch(_plan(ISSUES2), "sq-api") not in hosting.pushed  # the stopped squad is never pushed
    assert hosting.merged == [result["squads"]["sq-web"]["pr"]]
    assert result["status"] == "BLOCKED"


def test_a_change_to_a_shared_file_stops_the_squad_even_inside_its_glob(repo, tmp_path):
    plan = _plan(ISSUES2)
    api = next(s for s in plan["squads"] if s["id"] == "sq-api")
    api["owned_paths"] = ["api/*", "pyproject.toml"]  # a shared file must never be owned by a worker
    launcher = _table(**{"sq-api": _writer("pyproject.toml"), "sq-web": _writer("web/b.py")})
    result = _run(plan, repo, tmp_path, _deps(launcher, FakeHosting(repo)), approvers=())
    assert result["squads"]["sq-api"]["reason_kind"] == "ownership"
    assert result["squads"]["sq-api"]["offending"] == ["pyproject.toml"]


# ---------------------------------------------------------------------------------------------- (c) continuation


def test_budget_exhausted_gets_a_handoff_note_and_continuations_then_blocks(repo, tmp_path):
    def budget(request):
        if request.attempt == 1:
            (request.worktree / "api" / "a.py").write_text("A = 1\n", encoding="utf-8")
        return sr.WorkerOutcome(sr.STATUS_BUDGET, detail="context budget")

    launcher = _table(**{"sq-api": budget, "sq-web": _writer("web/b.py")})
    result = _run(_plan(ISSUES2), repo, tmp_path, _deps(launcher, FakeHosting(repo)), max_continuations=3, approvers=())

    calls = [c for c in launcher.calls if c.squad == "sq-api"]
    assert [c.attempt for c in calls] == [1, 2, 3, 4]  # the first run plus the 3 continuations, then BLOCKED
    api = result["squads"]["sq-api"]
    assert api["status"] == "blocked" and api["reason_kind"] == "budget" and api["continuations"] == 3
    assert "sq-api" in result["next"]
    note = (Path(api["worktree"]) / ".simplicio" / "handoff.md").read_text(encoding="utf-8")
    assert "## Files touched" in note and "- api/a.py" in note and "## Done and remaining" in note
    assert "## Handoff from the previous attempt" not in calls[0].prompt
    assert "## Handoff from the previous attempt" in calls[1].prompt
    assert "Continue from the remaining items only" in calls[1].prompt


def test_budget_then_done_continues_once_and_the_squad_is_ready(repo, tmp_path):
    def once(request):
        if request.attempt == 1:
            (request.worktree / "api" / "a.py").write_text("A = 1\n", encoding="utf-8")
            return sr.WorkerOutcome(sr.STATUS_BUDGET)
        return sr.WorkerOutcome(sr.STATUS_DONE)

    launcher = _table(**{"sq-api": once, "sq-web": _writer("web/b.py")})
    result = _run(_plan(ISSUES2), repo, tmp_path, _deps(launcher, FakeHosting(repo)), approvers=())
    api = result["squads"]["sq-api"]
    assert api["status"] == "ready" and api["continuations"] == 1 and api["launches"] == 2


# ---------------------------------------------------------------------------------------------- (d) merge order


def test_merges_follow_the_planned_merge_order_not_the_launch_order(repo, tmp_path):
    plan = _plan(ISSUES3)
    order = [step["squad"] for step in plan["merge_order"]]
    assert order == ["sq-web", "sq-docs", "sq-api"]  # docs before api: api depends on issue 3
    launcher = _table(**{"sq-api": _writer("api/a.py"), "sq-web": _writer("web/b.py"), "sq-docs": _writer("docs/c.py")})
    hosting = FakeHosting(repo, approve_all=True)
    result = _run(plan, repo, tmp_path, _deps(launcher, hosting), approvers=["wesley"])

    assert result["status"] == "DONE"
    assert result["merged"] == order
    assert [hosting.prs[pr]["branch"] for pr in hosting.merged] == [_branch(plan, sid) for sid in order]


# ---------------------------------------------------------------------------------------------- (e) approval gate


def test_execute_without_an_approver_stops_before_any_push_or_merge(repo, tmp_path):
    launcher = _table(**{"sq-api": _writer("api/a.py"), "sq-web": _writer("web/b.py")})
    hosting = FakeHosting(repo, approve_all=True)
    result = _run(_plan(ISSUES2), repo, tmp_path, _deps(launcher, hosting), approvers=())

    assert result["status"] == "BLOCKED"
    assert result["squads"]["sq-api"]["status"] == "ready" and result["squads"]["sq-web"]["status"] == "ready"
    assert hosting.pushed == [] and hosting.prs == {} and hosting.merged == []
    assert "--approver" in result["next"]


def test_an_unapproved_pr_is_opened_but_not_merged(repo, tmp_path):
    launcher = _table(**{"sq-api": _writer("api/a.py"), "sq-web": _writer("web/b.py")})
    hosting = FakeHosting(repo, approve_all=False)
    result = _run(_plan(ISSUES2), repo, tmp_path, _deps(launcher, hosting), approvers=["wesley"])

    assert result["status"] == "BLOCKED" and result["merged"] == []
    assert hosting.merged == []
    assert result["squads"]["sq-api"]["reason_kind"] == "gate"
    assert f"PR #{result['squads']['sq-api']['pr']}" in result["next"]


# ---------------------------------------------------------------------------------------------- (f) no force


FORCE_FLAGS = {"--force", "--force-with-lease", "--force-if-includes", "-f", "--mirror"}


def test_no_git_call_uses_a_force_flag(repo, tmp_path, monkeypatch):
    seen = []
    real_run = subprocess.run

    def recording(argv, *args, **kwargs):
        seen.append(list(argv))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(sr.subprocess, "run", recording)
    launcher = _table(**{"sq-api": _writer("api/a.py"), "sq-web": _writer("web/b.py")})
    result = _run(_plan(ISSUES2), repo, tmp_path, _deps(launcher, FakeHosting(repo, approve_all=True)), approvers=["wesley"])

    assert result["status"] == "DONE"
    git_calls = [argv for argv in seen if argv and argv[0] == "git"]
    assert any("push" in argv for argv in git_calls)  # the real push ran, and it is not forced
    for argv in git_calls:
        assert not FORCE_FLAGS.intersection(argv), argv
    assert "--force" not in Path(sr.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------- system + modes


def test_two_disjoint_squads_run_end_to_end_and_both_merge_in_order(repo, tmp_path):
    plan = _plan(ISSUES2)
    launcher = _table(**{"sq-api": _writer("api/a.py"), "sq-web": _writer("web/b.py")})
    hosting = FakeHosting(repo, approve_all=True)
    result = _run(plan, repo, tmp_path, _deps(launcher, hosting), approvers=["wesley"])

    assert result["status"] == "DONE" and result["merged"] == ["sq-api", "sq-web"]
    for sid in ("sq-api", "sq-web"):
        assert _git(repo, "ls-remote", "origin", f"refs/heads/{_branch(plan, sid)}") != ""
        assert result["squads"][sid]["merge"]
    assert _git(repo, "log", "-1", "--format=%s", _branch(plan, "sq-api")).startswith("squad sq-api:")


@pytest.mark.parametrize("mode", [merge_lockfree.MODE_BATCH, merge_lockfree.MODE_LOCKFREE])
def test_a_red_main_after_a_merge_stops_the_run_in_both_modes(repo, tmp_path, mode):
    launcher = _table(**{"sq-api": _writer("api/a.py"), "sq-web": _writer("web/b.py")})
    hosting = FakeHosting(repo, approve_all=True)
    red = lambda sha: (False, "FAILED tests/test_x.py::test_y")
    result = _run(_plan(ISSUES2), repo, tmp_path, _deps(launcher, hosting, verify=red), approvers=["wesley"], mode=mode)

    assert result["status"] == "BLOCKED"
    assert result["squads"]["sq-api"]["status"] == "merged"
    assert result["squads"]["sq-web"]["status"] == "ready"  # no further merge after a red main
    assert hosting.merged == [result["squads"]["sq-api"]["pr"]]


def test_failing_tests_block_the_squad_before_any_push(repo, tmp_path):
    launcher = _table(**{"sq-api": _writer("api/a.py"), "sq-web": _writer("web/b.py")})
    hosting = FakeHosting(repo, approve_all=True)
    tester = lambda path: (path.name != "sq-api", "FAILED tests/test_api.py::test_a")
    result = _run(_plan(ISSUES2), repo, tmp_path, _deps(launcher, hosting, tester=tester), approvers=["wesley"])

    api = result["squads"]["sq-api"]
    assert api["status"] == "blocked" and api["reason_kind"] == "tests"
    assert _branch(_plan(ISSUES2), "sq-api") not in hosting.pushed
    assert result["squads"]["sq-web"]["status"] == "merged"


def test_default_launcher_maps_exit_codes_to_typed_outcomes(tmp_path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    budget = sr.command_launcher(f"{sys.executable} -c 'import sys; sys.exit(75)'")
    failed = sr.command_launcher(f"{sys.executable} -c 'import sys; sys.exit(3)'")
    done = sr.command_launcher(f"{sys.executable} -c 'import sys; open(\"got.txt\", \"w\").write(sys.stdin.read())'")
    request = sr.LaunchRequest("sq-x", worktree, "m", "e", ("x.py",), "PROMPT-TEXT", 1)
    assert budget(request).status == sr.STATUS_BUDGET
    assert failed(request).status == sr.STATUS_FAILED
    assert done(request).status == sr.STATUS_DONE
    assert (worktree / "got.txt").read_text(encoding="utf-8") == "PROMPT-TEXT"  # the prompt goes through stdin


def test_worker_outcome_rejects_an_unknown_status():
    with pytest.raises(ValueError):
        sr.WorkerOutcome("maybe")


# ---------------------------------------------------------------------------------------------- CLI


def test_cli_dry_run_prints_json_and_a_blocked_plan_prints_next(repo, tmp_path, capsys):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(_plan(ISSUES2)), encoding="utf-8")
    code = cli_impl.main(["squads", "run", "--plan", str(plan_file), "--repo", str(repo),
                          "--run-dir", str(tmp_path / "run"), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["status"] == "DRY_RUN"
    assert [s["squad"] for s in out["preview"]["squads"]] == ["sq-api", "sq-web"]

    code = cli_impl.main(["squads", "run", "--plan", "{not json"])
    err = capsys.readouterr().err
    assert code == 2
    assert any(line.startswith("next: ") for line in err.splitlines())


@pytest.mark.parametrize("mode", [merge_lockfree.MODE_BATCH, merge_lockfree.MODE_LOCKFREE])
def test_a_squad_waits_when_the_squad_it_depends_on_does_not_merge(repo, tmp_path, mode):
    plan = _plan(ISSUES3)  # sq-api depends on sq-docs
    launcher = _table(**{
        "sq-api": _writer("api/a.py"),
        "sq-web": _writer("web/b.py"),
        "sq-docs": _writer("docs/c.py", "web/b.py"),  # sq-docs is stopped by its ownership check
    })
    hosting = FakeHosting(repo, approve_all=True)
    result = _run(plan, repo, tmp_path, _deps(launcher, hosting), approvers=["wesley"], mode=mode)

    assert result["squads"]["sq-docs"]["reason_kind"] == "ownership"
    assert result["squads"]["sq-api"]["status"] != "merged"
    assert "sq-docs" in result["squads"]["sq-api"]["reason"]
    assert result["squads"]["sq-web"]["status"] == "merged"
    assert result["status"] == "BLOCKED"
