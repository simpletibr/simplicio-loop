"""Tests for simplicio.init — skill + hook installer."""
import json
import os

from simplicio.init import HOOK_MARKER, install


def test_install_fresh_claude_home(tmp_path):
    report = install(claude_home=tmp_path, dry_run=False)

    assert report.skill_installed is True
    assert report.hook_script_installed is True
    assert report.settings_updated is True

    assert report.skill_path.exists()
    assert report.hook_script_path.exists()
    assert report.settings_path.exists()

    skill_text = report.skill_path.read_text(encoding="utf-8")
    assert "name: simplicio-cli" in skill_text

    if os.name != "nt":
        mode = report.hook_script_path.stat().st_mode
        assert mode & 0o111
    hook_text = report.hook_script_path.read_text(encoding="utf-8")
    assert "simplicio-py detect" in hook_text
    assert "CLAUDE_USER_PROMPT" in hook_text

    settings = json.loads(report.settings_path.read_text(encoding="utf-8"))
    entries = settings["hooks"]["UserPromptSubmit"]
    assert len(entries) == 1
    commands = [h["command"] for h in entries[0]["hooks"]]
    assert any(HOOK_MARKER in c for c in commands)


def test_idempotent_second_run(tmp_path):
    install(claude_home=tmp_path, dry_run=False)
    second = install(claude_home=tmp_path, dry_run=False)

    assert second.skill_installed is False
    assert second.hook_script_installed is False
    assert second.settings_updated is False


def test_dry_run_writes_nothing(tmp_path):
    report = install(claude_home=tmp_path, dry_run=True)

    assert report.dry_run is True
    assert report.skill_installed is True
    assert not report.skill_path.exists()
    assert not report.hook_script_path.exists()
    assert not report.settings_path.exists()


def test_preserves_existing_settings(tmp_path):
    settings_path = tmp_path / "settings.json"
    existing = {
        "env": {"FOO": "bar"},
        "permissions": {"allow": ["Bash"]},
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}
            ]
        },
    }
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(existing), encoding="utf-8")

    install(claude_home=tmp_path, dry_run=False)

    merged = json.loads(settings_path.read_text(encoding="utf-8"))
    assert merged["env"]["FOO"] == "bar"
    assert merged["permissions"]["allow"] == ["Bash"]
    assert len(merged["hooks"]["PreToolUse"]) == 1
    assert merged["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "echo pre"
    assert "UserPromptSubmit" in merged["hooks"]
    assert len(merged["hooks"]["UserPromptSubmit"]) == 1


def test_creates_backup_when_settings_exists(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    original = {"env": {"X": "y"}}
    settings_path.write_text(json.dumps(original), encoding="utf-8")

    install(claude_home=tmp_path, dry_run=False)

    backup = settings_path.with_suffix(".json.bak")
    assert backup.exists()
    restored = json.loads(backup.read_text(encoding="utf-8"))
    assert restored == original
