"""`simplicio-loop install` (the command `pip install simplicio-loop` ships) registers the Claude Code hooks.

Before this, the packaged install copied `hooks/` but never wrote `.claude/settings.json`, so the Stop hook (loop
re-feed) and the PreToolUse safety gate were inactive. These tests run the real CLI into temporary projects.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import cli, cli_impl, setup_cli

REPO = Path(__file__).resolve().parents[2]
INSTALL_LIB = REPO / "scripts" / "install_lib.py"
HOOK_FILES = ("loop_stop.py", "action_gate.py", "orient_rewrite.py")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # `install` ends with the setup (#1841); these tests cover the hook wiring, and tests/setup_wizard covers the setup
    monkeypatch.setattr(setup_cli, "after_install", lambda **kw: 0)
    return home


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "bundle"
    skill = root / "skills" / "simplicio-loop"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("loop\n", encoding="utf-8")
    (root / "hooks").mkdir()
    for name in HOOK_FILES + ("hooks.json",):
        (root / "hooks" / name).write_text("# hook\n", encoding="utf-8")
    monkeypatch.setattr(cli_impl, "BUNDLE", root)
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


def run(capsys, *argv):
    rc = cli.main(list(argv))
    return rc, capsys.readouterr().out


def settings_of(root: Path) -> dict:
    return json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))


def commands_of(groups: list) -> list:
    return [hook["command"] for group in groups for hook in group["hooks"]]


def test_project_install_registers_stop_and_pretooluse_hooks_that_point_at_the_installed_files(
    capsys, bundle, project
):
    rc, out = run(capsys, "install", "--target", str(project))
    assert rc == 0, out
    hooks = settings_of(project)["hooks"]
    assert commands_of(hooks["Stop"]) == ["python3 ./hooks/loop_stop.py"]
    assert commands_of(hooks["PreToolUse"]) == [
        "python3 ./hooks/action_gate.py",
        "python3 ./hooks/orient_rewrite.py",
    ]
    assert hooks["PreToolUse"][1]["matcher"] == "Bash", "orient_rewrite is the Bash-only rewrite"
    for command in commands_of(hooks["Stop"]) + commands_of(hooks["PreToolUse"]):
        assert (project / command.split("./", 1)[1]).is_file(), command
    assert ".claude/settings.json" in out


def test_check_reports_pending_until_the_hooks_are_registered(capsys, bundle, project):
    rc, _ = run(capsys, "install", "--check", "--target", str(project))
    assert rc == 10, "a project without the hooks has changes pending"
    run(capsys, "install", "--target", str(project))
    rc, _ = run(capsys, "install", "--check", "--target", str(project))
    assert rc == 0


def test_dry_run_json_reports_the_settings_file_and_writes_nothing(capsys, bundle, project):
    rc, out = run(capsys, "install", "--dry-run", "--json", "--target", str(project))
    assert rc == 0
    payload = json.loads(out)
    assert ".claude/settings.json" in payload["changes"]["created"]
    assert not (project / ".claude").exists()


def test_uninstall_returns_the_project_settings_to_what_the_user_had(capsys, bundle, project):
    user = {"model": "sonnet", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(json.dumps(user), encoding="utf-8")
    run(capsys, "install", "--target", str(project))
    assert len(settings_of(project)["hooks"]["Stop"]) == 2
    rc, out = run(capsys, "install", "--uninstall", "--target", str(project))
    assert rc == 0, out
    assert settings_of(project) == user
    assert "unwired: .claude/settings.json" in out


def test_global_install_registers_absolute_hook_paths_in_the_home_settings(capsys, bundle, isolated_home):
    rc, out = run(capsys, "install", "--global")
    assert rc == 0, out
    hooks_dir = isolated_home.resolve() / ".claude" / "hooks"
    hooks = settings_of(isolated_home)["hooks"]
    assert commands_of(hooks["Stop"]) == [f'python3 "{(hooks_dir / "loop_stop.py").as_posix()}"']
    assert commands_of(hooks["PreToolUse"]) == [f'python3 "{(hooks_dir / "action_gate.py").as_posix()}"']
    assert (hooks_dir / "loop_stop.py").is_file()


def test_cursor_install_copies_the_cursor_hooks_file_and_leaves_claude_settings_alone(capsys, bundle, project):
    rc, out = run(capsys, "install", "--host", "cursor", "--target", str(project))
    assert rc == 0, out
    assert (project / "hooks" / "hooks.json").is_file()
    assert not (project / ".claude" / "settings.json").exists()


def test_package_install_and_git_clone_installer_write_the_same_claude_hooks(capsys, bundle, project, tmp_path):
    run(capsys, "install", "--target", str(project))
    clone = tmp_path / "clone"
    clone.mkdir()
    env = dict(os.environ)
    env["PATH"] = "/usr/bin:/bin"
    env["HOME"] = str(tmp_path / "clone-home")
    done = subprocess.run(
        [sys.executable, str(INSTALL_LIB), "claude", "--target", str(clone), "--skip-operators", "--minimal"],
        capture_output=True, text=True, cwd=str(clone), env=env, timeout=600, check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert settings_of(project)["hooks"] == settings_of(clone)["hooks"]
