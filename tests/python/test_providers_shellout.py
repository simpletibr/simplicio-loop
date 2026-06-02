"""Tests for Path 3 shell-out providers (claude-cli / codex-cli).

These providers spawn a logged-in CLI subprocess instead of calling an HTTP
API, so we mock subprocess.run and verify argv shape, env injection, and
error handling.
"""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from simplicio import providers
from simplicio._cache import reset_for_tests


@pytest.fixture(autouse=True)
def isolated_completion_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("SIMPLICIO_BUST_CACHE", raising=False)
    reset_for_tests()
    yield
    reset_for_tests()


def _ok(stdout="ok"):
    r = MagicMock()
    r.returncode = 0
    r.stdout = stdout
    r.stderr = ""
    return r


def test_claude_cli_builds_argv_and_injects_guard(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)
    monkeypatch.delenv("SIMPLICIO_BASE_URL", raising=False)

    with patch("subprocess.run", return_value=_ok("hello")) as run:
        out = providers.generate("write hello")

    assert out == "hello"
    args, kwargs = run.call_args
    cmd = args[0]
    assert cmd[0] in {"claude", "claude.cmd", "claude.exe"}
    assert cmd[1] == "-p"
    assert cmd[2] == "write hello"
    assert "--model" in cmd and "sonnet" in cmd
    assert kwargs["env"]["SIMPLICIO_HOOK_GUARD"] == "1"
    assert kwargs["env"]["SIMPLICIO_SKIP_AUTO_INIT"] == "1"
    assert kwargs["capture_output"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert kwargs["timeout"] == 600


def test_codex_cli_builds_argv_with_model_then_prompt(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/gpt-5")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    with patch("subprocess.run", return_value=_ok("done")) as run:
        out = providers.generate("refactor x")

    assert out == "done"
    cmd = run.call_args[0][0]
    kwargs = run.call_args[1]
    assert cmd[0] in {"codex", "codex.cmd", "codex.exe"}
    assert cmd[1] == "exec"
    assert "--skip-git-repo-check" in cmd
    assert "--model" in cmd
    assert cmd.index("gpt-5") == cmd.index("--model") + 1
    assert cmd[-1] == "-"
    assert kwargs["input"] == "refactor x"


def test_claude_cli_skips_model_flag_for_default(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/default")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    with patch("subprocess.run", return_value=_ok()) as run:
        providers.generate("x")

    cmd = run.call_args[0][0]
    assert "--model" not in cmd


def test_shell_out_feedback_inlined_into_prompt(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    with patch("subprocess.run", return_value=_ok()) as run:
        providers.generate("first attempt", feedback="missing import X")

    prompt_arg = run.call_args[0][0][2]
    assert "first attempt" in prompt_arg
    assert "missing import X" in prompt_arg
    assert "FAILED" in prompt_arg


def test_cli_not_on_path_raises_friendly(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    with patch("subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(SystemExit) as exc:
            providers.generate("x")

    assert "claude" in str(exc.value).lower()
    assert "path" in str(exc.value).lower()


def test_shell_out_nonzero_exit_raises_with_stderr(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/gpt-5")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    bad = MagicMock()
    bad.returncode = 2
    bad.stdout = ""
    bad.stderr = "not logged in"
    with patch("subprocess.run", return_value=bad):
        with pytest.raises(SystemExit) as exc:
            providers.generate("x")

    assert "not logged in" in str(exc.value)
    assert "exit 2" in str(exc.value)


def test_shell_out_timeout_raises_friendly(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-cli/sonnet")
    monkeypatch.delenv("SIMPLICIO_API_KEY", raising=False)

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=600),
    ):
        with pytest.raises(SystemExit) as exc:
            providers.generate("x")

    assert "timed out" in str(exc.value).lower()


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
    assert "SIMPLICIO_MODEL" in msg
    assert "claude-cli" in msg
    assert "codex-cli" in msg
    assert "openbmb/minicpm5:latest" in msg


def test_no_config_at_all_routes_to_local_llama_default(monkeypatch):
    # No model AND no base -> local llama.cpp primary, not a raise.
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    monkeypatch.delenv("SIMPLICIO_BASE_URL", raising=False)
    monkeypatch.setattr(
        providers,
        "_local_generate",
        lambda p, f, model, mt: f"local:{model}",
    )
    assert providers.generate("x") == "local:openbmb/minicpm5:latest"
