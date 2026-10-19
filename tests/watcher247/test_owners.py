"""The watcher serves the GitHub owners named in SIMPLICIO_247_OWNERS: no default owner, no repo-name prefix.

A repo is addressed as `owner/repo`. That full name keys the claims and the status, and it names the directories of the
base clone and of each item's worktree, so the same repo name under two owners is two repos.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import config, github, proc, state, worktrees
from simplicio_loop.watcher247.__main__ import main as watcher_main

from .fakes import FakeRun, baseline, issue, read_json, run_tick

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("value", [" Acme , jane ,acme", "acme,jane,acme"])
def test_owners_are_read_comma_separated_lower_case_and_once_each(value):
    assert config.owners({"SIMPLICIO_247_OWNERS": value}) == ("acme", "jane")


@pytest.mark.parametrize("value", [None, "", " , "])
def test_no_owner_named_is_refused_and_the_message_names_the_variable(value):
    environ = {} if value is None else {"SIMPLICIO_247_OWNERS": value}
    with pytest.raises(ValueError, match="SIMPLICIO_247_OWNERS"):
        config.owners(environ)


@pytest.mark.parametrize("value", ["acme/simplicio-loop", "-acme", "acme_co", "a b", "x" * 40])
def test_an_owner_must_be_a_github_login(value):
    with pytest.raises(ValueError, match="SIMPLICIO_247_OWNERS"):
        config.owners({"SIMPLICIO_247_OWNERS": value})


def test_the_watcher_refuses_to_start_without_owners_and_calls_no_github(env, monkeypatch, capsys):
    fake = env(FakeRun({"simplicio-a": [issue(1)]}))
    monkeypatch.delenv("SIMPLICIO_247_OWNERS")
    assert asyncio.run(watcher_main(once=True)) == 1
    assert "SIMPLICIO_247_OWNERS" in capsys.readouterr().out
    assert read_json(config.STATUS)["reason_code"] == "owners_env_invalid"
    assert fake.calls == []


def test_repos_come_from_every_owner_with_no_name_filter(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_OWNERS", "alice,bob")
    rows = {
        "alice": [{"name": "tool", "isArchived": False, "defaultBranchRef": {"name": "trunk"}},
                  {"name": "retired", "isArchived": True, "defaultBranchRef": {"name": "main"}}],
        "bob": [{"name": "simplicio-x", "isArchived": False, "defaultBranchRef": None}],
    }
    calls = []

    async def gh(argv, timeout=120, cwd=None, stdin=None, env=None):
        calls.append(list(argv))
        return proc.Result(0, json.dumps(rows[argv[3]]))

    monkeypatch.setattr(proc, "run", gh)
    found = asyncio.run(github.repos())
    assert found == [{"name": "alice/tool", "branch": "trunk"}, {"name": "bob/simplicio-x", "branch": "main"}]
    assert [argv[:4] for argv in calls] == [["gh", "repo", "list", "alice"], ["gh", "repo", "list", "bob"]]


def test_open_issues_reads_the_repo_of_its_owner(monkeypatch):
    seen = []

    async def gh(argv, timeout=120, cwd=None, stdin=None, env=None):
        seen.append(list(argv))
        return proc.Result(0, "[]")

    monkeypatch.setattr(proc, "run", gh)
    assert asyncio.run(github.open_issues("alice/simplicio-a")) == []
    assert any(part == "repos/alice/simplicio-a/issues" for part in seen[0])


def test_one_repo_name_under_two_owners_is_two_claims_and_two_worktrees(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_OWNERS", "alice,bob")
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    fake = env(FakeRun({"simplicio-a": [issue(1)]}, diff=False))
    baseline()
    run_tick()
    assert sorted(read_json(config.CLAIMS)) == ["alice/simplicio-a#1", "bob/simplicio-a#1"]
    assert sorted(str(cwd) for cwd in fake.turbo_cwds) == sorted(
        str(config.WORK / owner / "simplicio-a.wt" / "1") for owner in ("alice", "bob"))


def test_base_item_and_state_directories_are_per_owner(env):
    env(FakeRun({}))
    assert worktrees.base_path("alice/simplicio-a") == config.WORK / "alice" / "simplicio-a"
    assert worktrees.item_path("alice/simplicio-a", 7) == config.WORK / "alice" / "simplicio-a.wt" / "7"
    assert worktrees.state_home("alice/simplicio-a", 7) == config.WORK / "alice" / "simplicio-a.state" / "7"
    assert worktrees.base_path("bob/simplicio-a") != worktrees.base_path("alice/simplicio-a")
    assert state.key_of("alice/simplicio-a", 3) == "alice/simplicio-a#3"


@pytest.mark.parametrize("repo", ["simplicio-a", "alice/", "/simplicio-a", "alice/simplicio-a.wt", "alice/../x", "alice/b/c"])
def test_a_repo_is_owner_slash_name_and_never_a_path(repo):
    with pytest.raises(ValueError):
        worktrees.base_path(repo)


def test_the_maintainers_env_example_names_its_owner():
    text = (REPO / "packaging" / "systemd" / "simplicio-loop-247.env.example").read_text(encoding="utf-8")
    assert "\nSIMPLICIO_247_OWNERS=simpletibr\n" in text
