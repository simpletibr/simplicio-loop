"""Tests for SIMPLICIO_247_PR_DRAFT environment variable."""
from __future__ import annotations

import pytest

from simplicio_loop.watcher247 import config, proc, tick
from .fakes import FakeRun, baseline, issue, run_tick


def test_pr_draft_env_var_set_adds_draft_flag(env, monkeypatch):
    """With SIMPLICIO_247_PR_DRAFT=1, gh pr create should have --draft."""
    fake = env(FakeRun({"simplicio-a": [issue(7, "Add x")]}))
    monkeypatch.setenv("SIMPLICIO_247_PR_DRAFT", "1")
    baseline()
    run_tick()
    
    # Find the gh pr create call
    pr_calls = fake.ran("gh", "pr", "create")
    assert len(pr_calls) > 0, "gh pr create was not called"
    
    pr_create_argv = pr_calls[0]
    assert "--draft" in pr_create_argv, f"--draft not in {pr_create_argv}"


def test_pr_draft_env_var_unset_no_draft_flag(env, monkeypatch):
    """Without SIMPLICIO_247_PR_DRAFT, gh pr create should not have --draft."""
    fake = env(FakeRun({"simplicio-a": [issue(7, "Add x")]}))
    monkeypatch.delenv("SIMPLICIO_247_PR_DRAFT", raising=False)
    baseline()
    run_tick()
    
    # Find the gh pr create call
    pr_calls = fake.ran("gh", "pr", "create")
    assert len(pr_calls) > 0, "gh pr create was not called"
    
    pr_create_argv = pr_calls[0]
    assert "--draft" not in pr_create_argv, f"--draft should not be in {pr_create_argv}"


def test_pr_draft_env_var_wrong_value_no_draft_flag(env, monkeypatch):
    """With SIMPLICIO_247_PR_DRAFT=true (not '1'), gh pr create should not have --draft."""
    fake = env(FakeRun({"simplicio-a": [issue(7, "Add x")]}))
    monkeypatch.setenv("SIMPLICIO_247_PR_DRAFT", "true")
    baseline()
    run_tick()
    
    # Find the gh pr create call
    pr_calls = fake.ran("gh", "pr", "create")
    assert len(pr_calls) > 0, "gh pr create was not called"
    
    pr_create_argv = pr_calls[0]
    assert "--draft" not in pr_create_argv, f"--draft should not be in {pr_create_argv}"
