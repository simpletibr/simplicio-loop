"""Tests for Path 3 shell-out providers (claude-cli / codex-cli).

These providers spawn a logged-in CLI subprocess instead of calling an HTTP
API. Issue #210 moved the actual spawn/wait from a single blocking
``subprocess.run(timeout=600)`` into
:func:`simplicio.task_operator.run_bounded_subprocess` (heartbeats, a
startup-vs-total timeout split, process-tree kill, cooperative
cancellation) — see ``tests/python/test_task_operator.py`` for coverage of
that helper itself. These tests mock
``simplicio.task_operator.run_bounded_subprocess`` and verify that
``providers._shell_out``/``_shell_out_claude``/``_shell_out_codex`` still
build the right argv, inject the right env, and translate every
non-``"completed"`` phase into the same friendly ``SystemExit`` contract
callers relied on before #210.
"""

from unittest.mock import patch

import pytest

from simplicio import providers
from simplicio._cache import reset_for_tests
from simplicio.task_operator import (
    PHASE_CANCELLED,
    PHASE_COMPLETED,
    PHASE_FAILED,
    PHASE_STARTUP_TIMEOUT,
    PHASE_TOTAL_TIMEOUT,
    BoundedRunResult,
)


@pytest.fixture(autouse=True)
def isolated_completion_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("SIMPLICIO_BUST_CACHE", raising=False)
    reset_for_tests()
    yield
    reset_for_tests()


def _ok(stdout="ok", label="", cmd=None):
    return BoundedRunResult(
        phase=PHASE_COMPLETED,
        elapsed_s=0.01,
        returncode=0,
        stdout=stdout,
        stderr="",
        recovery="",
        label=label,
        cmd=cmd or [],
    )


def _codex_ok_with_output_file(stdout="ignored", content="done"):
    def _side_effect(cmd, **kwargs):
        out_path = cmd[cmd.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return _ok(stdout, cmd=cmd)

    return _side_effect


def test_claude_cli_builds_argv_and_injects_guard(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)
    monkeypatch.delenv("SIMPLICIO_BASE_URL", raising=False)

    with patch("simplicio.task_operator.run_bounded_subprocess", return_value=_ok("hello")) as run:
        out = providers.generate("write hello")

    assert out == "hello"
    args, kwargs = run.call_args
    cmd = args[0]
    assert cmd[0] in {"claude", "claude.cmd", "claude.exe"}
    assert cmd[1] == "-p"
    assert cmd[2].startswith(providers.LLM_DIRECTIVES)
    assert "write hello" in cmd[2]
    assert "--model" in cmd and "sonnet" in cmd
    assert kwargs["env"]["SIMPLICIO_HOOK_GUARD"] == "1"
    assert kwargs["env"]["SIMPLICIO_SKIP_AUTO_INIT"] == "1"
    assert kwargs["label"] == "Claude Code CLI (`claude -p`)"


def test_codex_cli_builds_argv_with_model_then_prompt(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/gpt-5")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)
    monkeypatch.delenv("SIMPLICIO_CODEX_EFFORT", raising=False)

    with patch(
        "simplicio.task_operator.run_bounded_subprocess",
        side_effect=_codex_ok_with_output_file(content="done"),
    ) as run:
        out = providers.generate("refactor x")

    assert out == "done"
    cmd = run.call_args[0][0]
    kwargs = run.call_args[1]
    assert cmd[0] in {"codex", "codex.cmd", "codex.exe"}
    assert cmd[1] == "exec"
    assert "--skip-git-repo-check" in cmd
    assert "--cd" in cmd
    assert "--ignore-rules" in cmd
    assert "--output-last-message" in cmd
    assert "--color" in cmd
    assert "--model" in cmd
    assert cmd.index("gpt-5") == cmd.index("--model") + 1
    assert cmd[-1] == "-"
    assert kwargs["stdin_text"].startswith(providers.LLM_DIRECTIVES)
    assert "refactor x" in kwargs["stdin_text"]


def test_codex_cli_adds_effort_when_configured(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/gpt-5.4")
    monkeypatch.setenv("SIMPLICIO_CODEX_EFFORT", "medium")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    with (
        patch("simplicio.providers._codex_supports_effort_flag", return_value=True),
        patch(
            "simplicio.task_operator.run_bounded_subprocess",
            side_effect=_codex_ok_with_output_file(content="done"),
        ) as run,
    ):
        out = providers.generate("refactor x")

    assert out == "done"
    cmd = run.call_args[0][0]
    assert "--effort" in cmd
    assert cmd[cmd.index("--effort") + 1] == "medium"


def test_codex_cli_skips_effort_when_cli_does_not_support_it(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/gpt-5.4")
    monkeypatch.setenv("SIMPLICIO_CODEX_EFFORT", "medium")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    with (
        patch("simplicio.providers._codex_supports_effort_flag", return_value=False),
        patch(
            "simplicio.task_operator.run_bounded_subprocess",
            side_effect=_codex_ok_with_output_file(content="done"),
        ) as run,
    ):
        out = providers.generate("refactor x")

    assert out == "done"
    cmd = run.call_args[0][0]
    assert "--effort" not in cmd


def test_claude_cli_skips_model_flag_for_default(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/default")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    with patch("simplicio.task_operator.run_bounded_subprocess", return_value=_ok()) as run:
        providers.generate("x")

    cmd = run.call_args[0][0]
    assert "--model" not in cmd


def test_shell_out_feedback_inlined_into_prompt(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    with patch("simplicio.task_operator.run_bounded_subprocess", return_value=_ok()) as run:
        providers.generate("first attempt", feedback="missing import X")

    prompt_arg = run.call_args[0][0][2]
    assert "first attempt" in prompt_arg
    assert "missing import X" in prompt_arg
    assert "FAILED" in prompt_arg


def test_cli_not_on_path_raises_friendly(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    not_found = BoundedRunResult(
        phase=PHASE_FAILED,
        elapsed_s=0.0,
        returncode=None,
        stdout="",
        stderr="`claude` CLI not on PATH.",
        recovery="Install Claude Code CLI first, then re-run.",
    )
    with patch("simplicio.task_operator.run_bounded_subprocess", return_value=not_found):
        with pytest.raises(SystemExit) as exc:
            providers.generate("x")

    assert "claude" in str(exc.value).lower()
    assert "path" in str(exc.value).lower()


def test_shell_out_nonzero_exit_raises_with_stderr(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/gpt-5")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    bad = BoundedRunResult(
        phase=PHASE_FAILED,
        elapsed_s=0.1,
        returncode=2,
        stdout="",
        stderr="not logged in",
        recovery="Non-zero exit; inspect stderr for the CLI's reported cause.",
    )
    with patch("simplicio.task_operator.run_bounded_subprocess", return_value=bad):
        with pytest.raises(SystemExit) as exc:
            providers.generate("x")

    assert "not logged in" in str(exc.value)
    assert "exit 2" in str(exc.value)


def test_shell_out_total_timeout_raises_friendly(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    timed_out = BoundedRunResult(
        phase=PHASE_TOTAL_TIMEOUT,
        elapsed_s=600.5,
        returncode=None,
        stdout="",
        stderr="",
        recovery="raise the deadline",
    )
    with patch("simplicio.task_operator.run_bounded_subprocess", return_value=timed_out):
        with pytest.raises(SystemExit) as exc:
            providers.generate("x")

    assert "timed out" in str(exc.value).lower()


def test_shell_out_startup_timeout_raises_distinct_message(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    stalled = BoundedRunResult(
        phase=PHASE_STARTUP_TIMEOUT,
        elapsed_s=30.2,
        returncode=None,
        stdout="",
        stderr="",
        recovery="check login",
    )
    with patch("simplicio.task_operator.run_bounded_subprocess", return_value=stalled):
        with pytest.raises(SystemExit) as exc:
            providers.generate("x")

    message = str(exc.value).lower()
    assert "never started producing output" in message
    assert "timed out" not in message.split("never started")[0]


def test_shell_out_cancelled_raises_with_recovery(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    cancelled = BoundedRunResult(
        phase=PHASE_CANCELLED,
        elapsed_s=12.0,
        returncode=None,
        stdout="",
        stderr="",
        recovery="no automatic retry",
    )
    with patch("simplicio.task_operator.run_bounded_subprocess", return_value=cancelled):
        with pytest.raises(SystemExit) as exc:
            providers.generate("x")

    assert "cancelled" in str(exc.value).lower()


def test_info_reports_shell_out_modes(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = providers.info()
    assert "claude-cli" in s
    assert "key=not-needed" in s

    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/gpt-5")
    s = providers.info()
    assert "codex-cli" in s
    assert "key=not-needed" in s


def test_native_path_still_requires_key(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-opus-4-7")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SIMPLICIO_BASE_URL", raising=False)

    with pytest.raises(SystemExit) as exc:
        providers.generate("x")
    assert "SIMPLICIO_API_KEY" in str(exc.value)
    assert "claude-cli" in str(exc.value)


def test_no_model_with_base_raises_with_hint(monkeypatch):
    # With no model but an OpenAI-compatible base_url set, the local default
    # does NOT kick in (the base signals a remote endpoint) so we still raise.
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    monkeypatch.setenv("SIMPLICIO_BASE_URL", "http://localhost:11434/v1")

    with pytest.raises(SystemExit) as exc:
        providers.generate("x")
    msg = str(exc.value)
    assert "LOCAL_INFERENCE_PAUSED" in msg
    assert "SIMPLICIO_LOCAL_INFERENCE=enabled" in msg


def test_no_config_at_all_keeps_local_inference_paused(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    monkeypatch.delenv("SIMPLICIO_BASE_URL", raising=False)
    with pytest.raises(SystemExit, match="LOCAL_INFERENCE_PAUSED"):
        providers.generate("x")
