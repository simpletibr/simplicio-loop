from __future__ import annotations

import subprocess

import pytest

from simplicio import codex_wrapper


def test_wrapper_install_is_reversible_and_does_not_overwrite(tmp_path):
    target = tmp_path / "codex-wrapper"
    assert codex_wrapper.install_wrapper(target).is_file()
    assert codex_wrapper.WRAPPER_MARKER in target.read_text(encoding="utf-8")
    foreign = tmp_path / "foreign"
    foreign.write_text("foreign", encoding="utf-8")
    with pytest.raises(FileExistsError):
        codex_wrapper.install_wrapper(foreign)
    with pytest.raises(PermissionError):
        codex_wrapper.uninstall_wrapper(foreign)
    assert codex_wrapper.uninstall_wrapper(target) is True


def test_wrapper_forwards_args_and_preserves_approval_environment(monkeypatch):
    observed = {}

    def fake_run(argv, *, env, check):
        observed.update(argv=argv, env=env, check=check)
        return subprocess.CompletedProcess(argv, 7)

    monkeypatch.setattr(codex_wrapper.subprocess, "run", fake_run)
    code = codex_wrapper.run_wrapped(
        ["exec", "--sandbox", "workspace-write", "--approval-policy", "on-request"],
        command="codex-test",
    )
    assert code == 7
    assert observed["argv"] == [
        "codex-test",
        "exec",
        "--sandbox",
        "workspace-write",
        "--approval-policy",
        "on-request",
    ]
    assert observed["env"]["SIMPLICIO_HOOK_GUARD"] == "1"
    assert observed["check"] is False
