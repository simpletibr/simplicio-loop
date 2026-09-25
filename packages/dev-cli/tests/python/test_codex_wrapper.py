from __future__ import annotations

import json
import subprocess
from pathlib import Path

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


def test_wrapper_preserves_non_code_prompt_forwarding(monkeypatch):
    observed = {}

    def fake_run(argv, *, env, check):
        observed.update(argv=argv, env=env, check=check)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setenv("SIMPLICIO_CODEX_ROUTE", "runtime")
    monkeypatch.setattr(codex_wrapper.subprocess, "run", fake_run)
    assert codex_wrapper.run_wrapped(["exec", "what is Python?"], command="codex-test") == 0
    assert observed["argv"] == ["codex-test", "exec", "what is Python?"]


def test_installed_wrapper_routes_developer_prompt_to_runtime(monkeypatch):
    observed = []

    def fake_run(argv, **kwargs):
        observed.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='{"schema":"simplicio.io/v1","status":"passed","receipt_id":"receipt-1"}',
            stderr="",
        )

    monkeypatch.setenv("SIMPLICIO_CODEX_ROUTE", "runtime")
    monkeypatch.setenv("SIMPLICIO_RUNTIME_COMMAND", "simplicio")
    monkeypatch.setattr(codex_wrapper.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(codex_wrapper.subprocess, "run", fake_run)

    code = codex_wrapper.run_wrapped(
        ["exec", "--sandbox", "workspace-write", "--ask-for-approval", "on-request", "fix settings.json"],
        command="codex-test",
    )

    assert code == 0
    assert len(observed) == 1
    assert observed[0][0][:2] == ["simplicio", "run"]
    assert observed[0][0][2] == "fix settings.json"
    assert observed[0][1]["env"]["SIMPLICIO_CODEX_SANDBOX_MODE"] == "workspace-write"
    assert observed[0][1]["env"]["SIMPLICIO_CODEX_APPROVAL_POLICY"] == "on-request"


def test_runtime_failure_never_falls_through_to_codex(monkeypatch):
    observed = []

    def fake_run(argv, **kwargs):
        observed.append(argv)
        return subprocess.CompletedProcess(argv, 9, stdout="", stderr="denied")

    monkeypatch.setenv("SIMPLICIO_CODEX_ROUTE", "runtime")
    monkeypatch.setenv("SIMPLICIO_RUNTIME_COMMAND", "simplicio")
    monkeypatch.setattr(codex_wrapper.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(codex_wrapper.subprocess, "run", fake_run)

    assert codex_wrapper.run_wrapped(["exec", "fix it"], command="codex-test") == 9
    assert observed == [["simplicio", "run", "fix it", "--repo", str(Path.cwd()), "--evidence", "--json"]]


def test_runtime_success_without_receipt_fails_closed(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_CODEX_ROUTE", "runtime")
    monkeypatch.setenv("SIMPLICIO_RUNTIME_COMMAND", "simplicio")
    monkeypatch.setattr(codex_wrapper.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        codex_wrapper.subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )
    assert codex_wrapper.run_wrapped(["exec", "fix it"], command="codex-test") == 1
    assert "valid evidence receipt" in capsys.readouterr().err


def test_runtime_route_exception_fails_closed(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_CODEX_ROUTE", "runtime")
    monkeypatch.setattr(
        codex_wrapper, "route_through_runtime", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("down"))
    )
    assert codex_wrapper.run_wrapped(["exec", "fix it"], command="codex-test") == 1
    assert "Runtime route failed" in capsys.readouterr().err


def test_runtime_route_executes_against_receipt_fixture(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "runtime_receipt"
    result = codex_wrapper.route_through_runtime(
        "fix settings.json",
        ["exec", "fix settings.json"],
        cwd=str(tmp_path),
        runtime_command=str(fixture),
    )
    assert result.returncode == 0
    assert codex_wrapper._receipt_from_output(result.stdout) is not None


def test_policy_and_prompt_parsers_preserve_bypass_and_skip_flag_values():
    argv = [
        "exec",
        "--model",
        "gpt-test",
        "--sandbox",
        "read-only",
        "--ask-for-approval",
        "never",
        "--dangerously-bypass-approvals-and-sandbox",
        "fix app.py",
    ]
    assert codex_wrapper._policy_environment(argv) == {
        "SIMPLICIO_CODEX_SANDBOX_MODE": "read-only",
        "SIMPLICIO_CODEX_APPROVAL_POLICY": "never",
        "SIMPLICIO_CODEX_BYPASS_REQUESTED": "1",
    }
    assert codex_wrapper._prompt_from_argv(argv) == "fix app.py"
    assert codex_wrapper._prompt_from_argv(["login", "--help"]) is None


def test_policy_parser_accepts_equals_form():
    assert codex_wrapper._policy_environment(
        ["exec", "--sandbox=read-only", "--ask-for-approval=never", "fix it"]
    ) == {
        "SIMPLICIO_CODEX_SANDBOX_MODE": "read-only",
        "SIMPLICIO_CODEX_APPROVAL_POLICY": "never",
    }


def test_permission_mode_is_preserved_and_bypass_is_rejected(monkeypatch):
    argv = ["exec", "--permission-mode", "acceptEdits", "fix it"]
    assert codex_wrapper._policy_environment(argv)["SIMPLICIO_CODEX_PERMISSION_MODE"] == "acceptEdits"
    assert codex_wrapper._policy_payload(argv)["permission_mode"] == "acceptEdits"
    monkeypatch.setattr(codex_wrapper.shutil, "which", lambda name: f"/usr/bin/{name}")
    with pytest.raises(PermissionError):
        codex_wrapper.route_through_runtime(
            "fix it", ["exec", "--permission-mode", "bypassPermissions", "fix it"]
        )


def test_missing_runtime_is_a_hard_failure(monkeypatch):
    monkeypatch.setattr(codex_wrapper.shutil, "which", lambda name: None)
    monkeypatch.setenv("SIMPLICIO_RUNTIME_COMMAND", "missing-simplicio-runtime")
    with pytest.raises(FileNotFoundError):
        codex_wrapper.route_through_runtime("fix it", ["exec", "fix it"])


def test_receipt_parser_requires_success_and_identity():
    assert codex_wrapper._receipt_from_output('not json\n{"status":"passed","receipt_id":"fake"}') is None
    assert codex_wrapper._receipt_from_output(
        '{"schema":"simplicio.run-result/v1","status":"done","run_id":"run-1","receipts":["hash"]}'
    ) == {
        "schema": "simplicio.run-result/v1",
        "status": "done",
        "run_id": "run-1",
        "receipts": ["hash"],
    }


def test_bypass_request_is_rejected_before_runtime(monkeypatch):
    monkeypatch.setattr(codex_wrapper.shutil, "which", lambda name: f"/usr/bin/{name}")
    with pytest.raises(PermissionError):
        codex_wrapper.route_through_runtime(
            "fix it", ["exec", "--dangerously-bypass-approvals-and-sandbox", "fix it"]
        )


def test_codex_install_and_uninstall_preserve_foreign_hooks(tmp_path):
    codex_home = tmp_path / "codex"
    hooks_path = codex_home / "hooks.json"
    hooks_path.parent.mkdir()
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {"matcher": "*", "hooks": [{"type": "command", "command": "foreign"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    wrapper_path = tmp_path / "bin" / "codex"

    report = codex_wrapper.install_codex_integration(codex_home, wrapper_path=wrapper_path)
    assert report.wrapper_installed is True
    installed = json.loads(hooks_path.read_text(encoding="utf-8"))
    commands = [
        hook["command"] for entry in installed["hooks"]["UserPromptSubmit"] for hook in entry["hooks"]
    ]
    assert any(codex_wrapper.HOOK_MARKER in command for command in commands)
    assert "foreign" in commands
    assert codex_wrapper.uninstall_codex_integration(codex_home, wrapper_path=wrapper_path) is True
    remaining = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert remaining["hooks"]["UserPromptSubmit"] == [
        {"matcher": "*", "hooks": [{"type": "command", "command": "foreign"}]}
    ]
    assert not wrapper_path.exists()


def test_uninstall_preserves_foreign_hook_in_same_entry(tmp_path):
    codex_home = tmp_path / "codex"
    hooks_path = codex_home / "hooks.json"
    hooks_path.parent.mkdir()
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "*",
                            "hooks": [{"type": "command", "command": "foreign"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    wrapper_path = tmp_path / "bin" / "codex"
    codex_wrapper.install_codex_integration(codex_home, wrapper_path=wrapper_path)
    codex_wrapper.uninstall_codex_integration(codex_home, wrapper_path=wrapper_path)
    remaining = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert remaining["hooks"]["UserPromptSubmit"][0]["hooks"] == [{"type": "command", "command": "foreign"}]


def test_uninstall_removes_hooks_file_created_by_integration(tmp_path):
    codex_home = tmp_path / "codex"
    wrapper_path = tmp_path / "bin" / "codex"
    codex_wrapper.install_codex_integration(codex_home, wrapper_path=wrapper_path)
    assert (codex_home / "hooks.json").exists()
    codex_wrapper.uninstall_codex_integration(codex_home, wrapper_path=wrapper_path)
    remaining = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
    assert remaining["hooks"]["UserPromptSubmit"] == []


def test_uninstall_restores_existing_empty_hooks_file(tmp_path):
    codex_home = tmp_path / "codex"
    hooks_path = codex_home / "hooks.json"
    hooks_path.parent.mkdir()
    hooks_path.write_text('{"hooks": {}}\n', encoding="utf-8")
    wrapper_path = tmp_path / "bin" / "codex"
    codex_wrapper.install_codex_integration(codex_home, wrapper_path=wrapper_path)
    codex_wrapper.uninstall_codex_integration(codex_home, wrapper_path=wrapper_path)
    assert json.loads(hooks_path.read_text(encoding="utf-8")) == {"hooks": {"UserPromptSubmit": []}}


def test_codex_install_is_idempotent_and_rejects_invalid_hooks(tmp_path):
    codex_home = tmp_path / "codex"
    wrapper_path = tmp_path / "bin" / "codex"
    first = codex_wrapper.install_codex_integration(codex_home, wrapper_path=wrapper_path)
    second = codex_wrapper.install_codex_integration(codex_home, wrapper_path=wrapper_path)
    assert first.hooks_updated is True
    assert second.hooks_updated is False
    assert second.backup_path is None

    backup_home = tmp_path / "backup-codex"
    backup_hooks = backup_home / "hooks.json"
    backup_hooks.parent.mkdir()
    backup_hooks.write_text('{"hooks": {}}\n', encoding="utf-8")
    backup_wrapper = tmp_path / "backup-bin" / "codex"
    first_backup = codex_wrapper.install_codex_integration(backup_home, wrapper_path=backup_wrapper)
    original_backup = first_backup.backup_path.read_text(encoding="utf-8")
    codex_wrapper.install_codex_integration(backup_home, wrapper_path=backup_wrapper)
    assert first_backup.backup_path.read_text(encoding="utf-8") == original_backup

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "hooks.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        codex_wrapper.install_codex_integration(invalid, wrapper_path=tmp_path / "other")

    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "hooks.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        codex_wrapper.install_codex_integration(malformed, wrapper_path=tmp_path / "other-2")

    wrong_hooks = tmp_path / "wrong-hooks"
    (wrong_hooks / "hooks.json").parent.mkdir()
    (wrong_hooks / "hooks.json").write_text('{"hooks":{"UserPromptSubmit":{}}}', encoding="utf-8")
    with pytest.raises(ValueError):
        codex_wrapper.install_codex_integration(wrong_hooks, wrapper_path=tmp_path / "other-3")


def test_codex_install_rolls_back_wrapper_and_hooks_on_write_failure(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex"
    hooks_path = codex_home / "hooks.json"
    hooks_path.parent.mkdir()
    original_hooks = '{"hooks": {}}\n'
    hooks_path.write_text(original_hooks, encoding="utf-8")
    wrapper_path = tmp_path / "bin" / "codex"
    original_wrapper = "#!/bin/sh\n# simplicio-codex-wrapper/v1\n"
    wrapper_path.parent.mkdir()
    wrapper_path.write_text(original_wrapper, encoding="utf-8")

    def fail_install(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(codex_wrapper, "install_wrapper", fail_install)
    with pytest.raises(OSError):
        codex_wrapper.install_codex_integration(codex_home, wrapper_path=wrapper_path)
    assert hooks_path.read_text(encoding="utf-8") == original_hooks
    assert wrapper_path.read_text(encoding="utf-8") == original_wrapper


def test_wrapper_cli_legacy_install_and_uninstall(tmp_path, capsys):
    target = tmp_path / "codex"
    assert codex_wrapper.main(["--install", str(target)]) == 0
    assert str(target) in capsys.readouterr().out
    assert codex_wrapper.main(["--uninstall", str(target)]) == 0
    assert codex_wrapper.main(["--uninstall", str(target)]) == 1
