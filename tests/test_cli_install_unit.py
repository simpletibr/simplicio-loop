"""Unit coverage for simplicio_loop/cli.py's install/copy-tree/GUI-availability helpers.

These are pure filesystem + env-var logic with no subprocess or network side effects, so they are
fast, deterministic in-process unit tests — the missing piece next to the existing subprocess-based
CLI contract tests (test_runner_cli.py, test_drain_cli.py, test_task_contract_cli.py), which already
exercise the argument-dispatch surface of cli.py but never import it directly, and so never register
in an in-process coverage run.
"""
import os

import simplicio_loop.cli as cli_mod


def test_copy_tree_copies_nested_files_and_returns_count(tmp_path):
    src = tmp_path / "src"
    (src / "a").mkdir(parents=True)
    (src / "a" / "one.txt").write_text("1", encoding="utf-8")
    (src / "b").mkdir(parents=True)
    (src / "b" / "two.txt").write_text("2", encoding="utf-8")
    dst = tmp_path / "dst"

    count = cli_mod._copy_tree(src, dst)

    assert count == 2
    assert (dst / "a" / "one.txt").read_text(encoding="utf-8") == "1"
    assert (dst / "b" / "two.txt").read_text(encoding="utf-8") == "2"


def test_copy_tree_on_empty_source_returns_zero(tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    dst = tmp_path / "dst"
    assert cli_mod._copy_tree(src, dst) == 0


def test_install_errors_when_bundled_skills_missing(tmp_path, monkeypatch, capsys):
    fake_bundle = tmp_path / "no-such-bundle"
    monkeypatch.setattr(cli_mod, "BUNDLE", fake_bundle)

    rc = cli_mod.install(tmp_path / "project", globally=False)

    assert rc == 1
    out = capsys.readouterr().out
    assert "bundled skills not found" in out


def test_install_copies_skills_and_hooks_project_local(tmp_path, monkeypatch, capsys):
    fake_bundle = tmp_path / "bundle"
    (fake_bundle / "skills" / "simplicio-loop").mkdir(parents=True)
    (fake_bundle / "skills" / "simplicio-loop" / "SKILL.md").write_text("x", encoding="utf-8")
    (fake_bundle / "hooks").mkdir(parents=True)
    (fake_bundle / "hooks" / "loop_stop.py").write_text("# hook", encoding="utf-8")
    monkeypatch.setattr(cli_mod, "BUNDLE", fake_bundle)

    target = tmp_path / "project"
    rc = cli_mod.install(target, globally=False)

    assert rc == 0
    assert (target / ".claude" / "skills" / "simplicio-loop" / "SKILL.md").is_file()
    assert (target / "hooks" / "loop_stop.py").is_file()
    out = capsys.readouterr().out
    assert "installed:" in out
    assert "/simplicio-loop finish all the open issues" in out


def test_install_copies_skills_globally_under_home(tmp_path, monkeypatch):
    fake_bundle = tmp_path / "bundle"
    (fake_bundle / "skills").mkdir(parents=True)
    (fake_bundle / "skills" / "s.md").write_text("x", encoding="utf-8")
    (fake_bundle / "hooks").mkdir(parents=True)
    (fake_bundle / "hooks" / "h.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli_mod, "BUNDLE", fake_bundle)

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(cli_mod.Path, "home", classmethod(lambda cls: fake_home))

    rc = cli_mod.install(tmp_path / "unused-target", globally=True)

    assert rc == 0
    assert (fake_home / ".claude" / "skills" / "s.md").is_file()
    assert (fake_home / ".claude" / "hooks" / "h.py").is_file()


def test_gui_available_true_on_darwin(monkeypatch):
    monkeypatch.setattr(cli_mod.sys, "platform", "darwin")
    assert cli_mod._gui_available() is True


def test_gui_available_true_on_nt(monkeypatch):
    monkeypatch.setattr(cli_mod.sys, "platform", "linux")
    from tests._os_proxy import os_with_name

    monkeypatch.setattr(cli_mod, "os", os_with_name(cli_mod.os, "nt"))
    assert cli_mod._gui_available() is True


def test_gui_available_false_headless_linux(monkeypatch):
    monkeypatch.setattr(cli_mod.sys, "platform", "linux")
    from tests._os_proxy import os_with_name

    monkeypatch.setattr(cli_mod, "os", os_with_name(cli_mod.os, "posix"))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert cli_mod._gui_available() is False


def test_gui_available_true_with_display_env(monkeypatch):
    monkeypatch.setattr(cli_mod.sys, "platform", "linux")
    from tests._os_proxy import os_with_name

    monkeypatch.setattr(cli_mod, "os", os_with_name(cli_mod.os, "posix"))
    monkeypatch.setenv("DISPLAY", ":0")
    assert cli_mod._gui_available() is True


def test_port_up_false_for_unused_port():
    # A high, unlikely-to-be-bound port on localhost: expect the connection to fail closed.
    assert cli_mod._port_up(65432) is False


def test_stop_dashboard_when_not_running_reports_not_running(tmp_path, monkeypatch, capsys):
    fake_pid_file = tmp_path / "pid"
    monkeypatch.setattr(cli_mod, "_pid_file", lambda: fake_pid_file)
    monkeypatch.setattr(cli_mod.subprocess, "run", lambda *a, **k: None)

    rc = cli_mod._stop_dashboard()

    assert rc == 0
    out = capsys.readouterr().out
    assert "dashboard was not running" in out or "stopped" in out


def test_dashboard_stop_delegates_to_stop_dashboard(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_mod, "_stop_dashboard", lambda: calls.append(1) or 0)

    rc = cli_mod.dashboard(port=9090, open_browser=False, stop=True)

    assert rc == 0
    assert calls == [1]


def test_dashboard_errors_when_bundled_dashboard_file_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli_mod, "DASHBOARD", tmp_path / "no-such-dashboard.py")

    rc = cli_mod.dashboard(port=9090, open_browser=False, stop=False)

    assert rc == 1
    out = capsys.readouterr().out
    assert "bundled dashboard not found" in out
