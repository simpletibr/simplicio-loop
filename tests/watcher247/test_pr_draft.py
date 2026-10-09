"""SIMPLICIO_247_PR_DRAFT=1 opens the watcher PR as a draft; anything else leaves the default."""
from __future__ import annotations

import pytest

from simplicio_loop.watcher247 import config

from .fakes import FakeRun, baseline, issue, read_json, run_tick
from .test_squads_tick import REPO, _view

BASE = ["gh", "pr", "create", "--repo", "simpletibr/simplicio-a", "--base", "main", "--head"]


def _create_argv(env, monkeypatch, value):
    fake = env(FakeRun({"simplicio-a": [issue(7, "Add x")]}))
    if value is None:
        monkeypatch.delenv("SIMPLICIO_247_PR_DRAFT", raising=False)
    else:
        monkeypatch.setenv("SIMPLICIO_247_PR_DRAFT", value)
    baseline()
    run_tick()
    [argv] = fake.ran("gh", "pr", "create")
    return argv


def test_exact_one_appends_draft_to_an_otherwise_unchanged_argv(env, monkeypatch):
    argv = _create_argv(env, monkeypatch, "1")
    assert argv[:8] == BASE and argv[-1] == "--draft" and argv.count("--draft") == 1
    assert argv[argv.index("--body") + 1] != "--draft"


@pytest.mark.parametrize("value", [None, "", "0", "10", " 1", "1 ", "true", "yes"])
def test_anything_but_exact_one_keeps_the_ready_pr(env, monkeypatch, value):
    assert "--draft" not in _create_argv(env, monkeypatch, value)


def test_draft_with_auto_merge_runs_no_train_and_no_merge(env, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_CONCURRENCY", "2")
    monkeypatch.setenv("SIMPLICIO_247_PR_DRAFT", "1")
    monkeypatch.setenv("SIMPLICIO_247_AUTO_MERGE", "1")
    clone = config.WORK / REPO
    (clone / ".git").mkdir(parents=True)
    (clone / "pytest.ini").write_text("[pytest]\n")
    rows = [issue(n, f"Task {n}", body=f"Ajustar `src/m{n}/app.py` para o fluxo do watcher seguir o contrato descrito abaixo.")
            for n in (1, 2)]
    fake = env(FakeRun({REPO: rows}, verify_pass=True, distinct_prs=True, pr_views={100 + n: _view(n) for n in (1, 2)}))
    baseline()
    run_tick()
    squads = read_json(config.STATUS)["squads"][REPO]
    assert squads["merge"] == "draft"
    assert fake.ran("gh", "pr", "merge") == [] and fake.tests_run == 0 and fake.ran("git", "merge") == []
