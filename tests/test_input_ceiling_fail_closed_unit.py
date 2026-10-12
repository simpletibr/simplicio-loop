"""The input ceiling fails closed when the repository has a remote but its default branch cannot be read (#1608).

Parte de #1608. A reviewer deleted ``refs/remotes/origin/HEAD`` in a shared clone and the ceiling fell from the
configured 50,000 to the built-in 98,000. Now: with a remote, no env var and no readable default branch, every sender
refuses and sends nothing. Without a remote (tests, scratch repositories) the built-in default applies, with its reason.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import author_flow, exec_planner, handoff_cli, input_ceiling as ic
from simplicio_loop import openrouter_operator, provider_worker, turbo_provider, turbo_window

BIG = "word " * 150_000  # far above any ceiling


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def clone(tmp_path, monkeypatch):
    """A clone of an upstream whose default branch sets the ceiling to 50,000. A clone has origin/HEAD set by git."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    (upstream / ".simplicio-loop").mkdir()
    (upstream / ".simplicio-loop" / "loop.toml").write_text("agent_input_token_ceiling = 50000\n", encoding="utf-8")
    _git(upstream, "add", ".")
    _git(upstream, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "config")
    root = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(upstream), str(root)], check=True, capture_output=True)
    monkeypatch.delenv(ic.ENV_NAME, raising=False)
    monkeypatch.setattr(ic, "_warned", False)
    return root


@pytest.fixture
def unreadable(clone):
    """The reviewer's reproduction: the clone keeps its remote and loses origin/HEAD."""
    _git(clone, "update-ref", "-d", "refs/remotes/origin/HEAD")
    return clone


@pytest.fixture
def no_git_call(monkeypatch):
    """Any git call fails the test: the env var wins without reading the repository."""
    def boom(*args, **kwargs):
        raise AssertionError("git must not be called when the env var sets the ceiling")
    monkeypatch.setattr(handoff_cli, "_git", boom)


# --- the ceiling itself ------------------------------------------------------------------------------------------------

def test_the_default_branch_value_is_read_from_the_clone(clone):
    got = ic.explain_ceiling(clone, environ={})
    assert (got.value, got.source, got.reason) == (50_000, "default branch", "")


def test_the_reviewers_bypass_is_refused_not_widened_to_the_built_in_default(unreadable):
    with pytest.raises(ic.CeilingUnreadable) as exc:
        ic.explain_ceiling(unreadable, environ={})
    assert exc.value.reason_code == "ceiling_unreadable"
    assert exc.value.ceiling_source == "default branch unreadable"
    assert "default_branch_unresolved" in exc.value.ceiling_reason


def test_a_deleted_origin_head_symref_is_refused(clone):
    """origin/HEAD itself unresolved (the symbolic ref is gone), the case the message names."""
    _git(clone, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
    with pytest.raises(ic.CeilingUnreadable) as exc:
        ic.explain_ceiling(clone, environ={})
    assert "origin/HEAD" in exc.value.ceiling_reason


def test_resolve_ceiling_refuses_too(unreadable):
    with pytest.raises(ic.CeilingUnreadable):
        ic.resolve_ceiling(unreadable, environ={})


def test_a_missing_default_branch_ref_is_refused(clone):
    _git(clone, "update-ref", "-d", "refs/remotes/origin/main")
    with pytest.raises(ic.CeilingUnreadable) as exc:
        ic.explain_ceiling(clone, environ={})
    assert "default_branch_unresolved" in exc.value.ceiling_reason


def test_the_env_var_wins_without_any_git_call(unreadable, no_git_call):
    got = ic.explain_ceiling(unreadable, environ={ic.ENV_NAME: "12345"})
    assert (got.value, got.source) == (12_345, "env " + ic.ENV_NAME)


def test_no_remote_gives_the_built_in_default_with_its_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "_warned", False)
    _git(tmp_path, "init", "-q", "-b", "main")
    got = ic.explain_ceiling(tmp_path, environ={})
    assert (got.value, got.source) == (98_000, "built-in default")
    assert "origin/HEAD" in got.reason


def test_a_directory_that_is_not_git_gives_the_built_in_default(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "_warned", False)
    got = ic.explain_ceiling(tmp_path, environ={})
    assert (got.value, got.source) == (98_000, "built-in default")


# --- every sender refuses before it sends anything ---------------------------------------------------------------------

def _provider_worker(repo):
    provider_worker._gate_input("small prompt", repo, {})


def _turbo_provider(repo):
    turbo_provider._gate_input([{"role": "user", "content": "small"}], None, repo)


def _turbo_window(repo):
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    turbo_window.build_files(repo, [{"index": 1, "text": "Edit a.py", "target": "a.py", "context": []}])


def _openrouter(repo, monkeypatch):
    def urlopen(*args, **kwargs):
        raise AssertionError("no request may be sent")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api")
    monkeypatch.setenv("SIMPLICIO_MODEL", "anthropic/claude-opus")
    monkeypatch.setattr(openrouter_operator.urllib.request, "urlopen", urlopen)
    openrouter_operator.request_mechanical_plan(
        task={"id": "T-1", "goal": "small", "type": "creation"}, target="test.txt", repo_path=repo,
        mapper_context={"mapper_generation": "g1"}, run_id="run-1", task_index=1, attempt=1)


def _exec_planner(repo, monkeypatch):
    async def no_run(*args, **kwargs):
        raise AssertionError("no CLI may start")
    monkeypatch.setattr(exec_planner, "_run_subprocess", no_run)
    monkeypatch.setattr(exec_planner, "_find_cli", lambda name: f"/usr/bin/{name}")
    return asyncio.run(exec_planner.run_planner("claude", "coordination", "small", repo_root=repo, cwd=str(repo)))


SENDERS = ["provider_worker", "turbo_provider", "turbo_window", "author_flow", "openrouter_operator", "exec_planner"]


@pytest.mark.parametrize("sender", SENDERS)
def test_every_sender_refuses_when_the_default_branch_is_unreadable(sender, unreadable, monkeypatch):
    if sender == "provider_worker":
        with pytest.raises(provider_worker.ProviderWorkerError) as exc:
            _provider_worker(unreadable)
        assert exc.value.reason_code == "ceiling_unreadable"
    elif sender == "turbo_provider":
        with pytest.raises(turbo_provider.TurboProviderError) as exc:
            _turbo_provider(unreadable)
        assert exc.value.reason_code == "ceiling_unreadable"
    elif sender == "turbo_window":
        with pytest.raises(ic.CeilingUnreadable) as exc:
            _turbo_window(unreadable)
        assert exc.value.reason_code == "ceiling_unreadable"
    elif sender == "author_flow":
        refusal = _author_flow_result(unreadable)
        assert (refusal.status, refusal.reason_code) == ("failed", "ceiling_unreadable")
    elif sender == "openrouter_operator":
        with pytest.raises(ic.CeilingUnreadable):
            _openrouter(unreadable, monkeypatch)
    else:
        result = _exec_planner(unreadable, monkeypatch)
        assert result.reason_code == "ceiling_unreadable"


def _author_flow_result(repo):
    def runner(*args, **kwargs):
        raise AssertionError("no CLI may start")
    return author_flow._Run(repo, None, 1, runner, False).ceiling_refusal("small prompt")


def test_handoff_check_exits_non_zero_with_the_same_reason(unreadable, capsys):
    code = handoff_cli.main(["check", "--repo", str(unreadable), "--input-tokens", "10", "--cache-read", "0",
                             "--cache-write", "0"])
    captured = capsys.readouterr()
    assert code != 0
    assert "ceiling_unreadable" in captured.err
    assert captured.out == ""


def test_the_reviewers_bypass_sends_nothing_at_the_configured_50000(clone, monkeypatch):
    """Configured 50,000 ⇒ a prompt projected at about 60,000 is over it. Deleting origin/HEAD must not lift it to 98,000."""
    monkeypatch.setattr(ic, "_warned", False)
    _git(clone, "update-ref", "-d", "refs/remotes/origin/HEAD")
    with pytest.raises(provider_worker.ProviderWorkerError) as exc:
        provider_worker._gate_input("word " * 60_000, clone, {})
    assert exc.value.reason_code == "ceiling_unreadable"
