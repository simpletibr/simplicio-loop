"""Tests for simplicio.cli.maybe_autoinstall — first-run bootstrap."""

from simplicio.cli import maybe_autoinstall


def test_autoinstall_runs_on_fresh_claude_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SIMPLICIO_SKIP_AUTO_INIT", raising=False)
    (tmp_path / ".claude").mkdir()

    ran = maybe_autoinstall(cmd="smoke")

    assert ran is True
    assert (tmp_path / ".claude" / "hooks" / "simplicio-userpromptsubmit.sh").exists()
    assert (tmp_path / ".claude" / "skills" / "simplicio-cli" / "SKILL.md").exists()
    assert (tmp_path / ".claude" / "settings.json").exists()


def test_autoinstall_skipped_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    (tmp_path / ".claude").mkdir()

    ran = maybe_autoinstall(cmd="smoke")

    assert ran is False
    assert not (tmp_path / ".claude" / "hooks").exists()


def test_autoinstall_skipped_when_no_claude_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SIMPLICIO_SKIP_AUTO_INIT", raising=False)

    ran = maybe_autoinstall(cmd="smoke")

    assert ran is False


def test_autoinstall_skipped_for_init_and_detect(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SIMPLICIO_SKIP_AUTO_INIT", raising=False)
    (tmp_path / ".claude").mkdir()

    assert maybe_autoinstall(cmd="init") is False
    assert maybe_autoinstall(cmd="detect") is False
    assert not (tmp_path / ".claude" / "hooks").exists()


def test_autoinstall_skipped_when_hook_already_present(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SIMPLICIO_SKIP_AUTO_INIT", raising=False)
    hook_path = tmp_path / ".claude" / "hooks" / "simplicio-userpromptsubmit.sh"
    hook_path.parent.mkdir(parents=True)
    hook_path.write_text("# placeholder")

    ran = maybe_autoinstall(cmd="smoke")

    assert ran is False
    assert hook_path.read_text() == "# placeholder"
