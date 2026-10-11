"""A sender that falls back to the built-in ceiling says why, in its refusal or receipt and on stderr (#1608).

The repository here has no ``origin/HEAD``, so the default branch cannot be read and the built-in 98,000 applies. That
fallback must be visible: the sender's result or refusal carries ``ceiling_source`` and ``ceiling_reason``.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from simplicio_loop import input_ceiling as ic
from simplicio_loop import provider_worker, turbo_provider, turbo_window


@pytest.fixture
def plain(tmp_path, monkeypatch):
    """A git repository with no origin/HEAD and no SIMPLICIO_AGENT_INPUT_TOKEN_CEILING in the environment."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True, capture_output=True)
    monkeypatch.delenv(ic.ENV_NAME, raising=False)
    monkeypatch.setattr(ic, "_warned", False)
    return root


BIG = "word " * 150_000  # far above 98,000 projected tokens


def test_the_built_in_default_is_reported_with_its_reason_on_a_passing_request(plain):
    result = provider_worker._gate_input("small prompt", plain, {})
    assert result["ceiling"] == 98_000
    assert result["ceiling_source"] == "built-in default"
    assert "origin/HEAD" in result["ceiling_reason"]


def test_a_refusal_over_the_built_in_default_names_the_reason(plain):
    with pytest.raises(provider_worker.ProviderWorkerError) as exc:
        provider_worker._gate_input(BIG, plain, {})
    assert exc.value.reason_code == "input_ceiling_exceeded"
    assert "built-in default" in str(exc.value) and "origin/HEAD" in str(exc.value)


def test_a_turbo_refusal_over_the_built_in_default_names_the_reason(plain):
    with pytest.raises(turbo_provider.TurboProviderError) as exc:
        turbo_provider._gate_input([{"role": "user", "content": BIG}], None, plain)
    assert exc.value.reason_code == "input_ceiling_exceeded"
    assert "built-in default" in str(exc.value) and "origin/HEAD" in str(exc.value)


def test_turbo_window_warns_on_stderr_when_it_uses_the_built_in_default(plain, capsys, tmp_path):
    (plain / "a.py").write_text("x = 1\n", encoding="utf-8")
    task = {"index": 1, "text": "Edit a.py", "target": "a.py", "context": []}
    turbo_window.build_files(plain, [task])
    err = capsys.readouterr().err
    assert "built-in default" in err and "origin/HEAD" in err
