"""A new attempt on an issue never opens a second PR while an open PR already carries its loop/issue-<N> branch or one of its -rK names."""
from __future__ import annotations

import pytest

from .fakes import FakeRun, baseline, issue, pr_row, run_tick

REPO = "simplicio-a"


@pytest.mark.parametrize("head", ["loop/issue-7", "loop/issue-7-r2"])
def test_an_open_loop_pr_on_the_issue_stops_a_new_attempt_before_any_work(env, head):
    fake = env(FakeRun({REPO: [issue(7)]}, distinct_prs=True, prs=[pr_row(9, head)]))
    baseline()
    run_tick()
    assert fake.turbo_argv == []
    assert fake.ran("gh", "pr", "create") == []


def test_an_open_pr_of_another_issue_does_not_stop_a_new_attempt(env):
    fake = env(FakeRun({REPO: [issue(7)]}, distinct_prs=True, prs=[pr_row(9, "loop/issue-70")]))
    baseline()
    run_tick()
    assert fake.ran("gh", "pr", "create")
