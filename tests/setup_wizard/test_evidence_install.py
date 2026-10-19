"""`simplicio-loop install` ends with the evidence tools (#1843): it is complete only while every required tool is ok."""
from __future__ import annotations

from simplicio_loop import cli_impl, prereqs, setup_cli

from .fakes import Fakes, check, summary_file


def chromium_missing():
    return ([check("evidence:node"), check("evidence:playwright"),
             prereqs.Check("evidence:chromium", "missing", True, None, None, None, "simplicio-loop setup", "user")],
            [prereqs.Action("evidence:chromium", "failed", "download failed")])


def all_ok():
    return [check("evidence:node"), check("evidence:playwright"), check("evidence:chromium"), check("evidence:check")], []


def test_after_install_names_the_missing_tool_its_fix_and_the_failure(home, monkeypatch, capsys):
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda environ: chromium_missing())
    items = setup_cli.after_install(interactive=False)
    assert [item["item"] for item in items] == ["evidence:chromium"]
    out = capsys.readouterr().out
    assert "evidence:chromium" in out and "download failed" in out and "simplicio-loop setup" in out


def test_install_is_not_complete_while_a_required_evidence_tool_is_missing(home, monkeypatch, capsys):
    target = home / "project"
    target.mkdir()
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda environ: chromium_missing())
    assert cli_impl.main(["install", "--target", str(target)]) == 1
    assert "install is not complete: evidence:chromium" in capsys.readouterr().out


def test_install_is_complete_when_the_evidence_tools_are_ok(home, monkeypatch):
    target = home / "project"
    target.mkdir()
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda environ: all_ok())
    assert cli_impl.main(["install", "--target", str(target)]) == 0


def test_a_first_run_in_a_terminal_is_the_whole_setup_and_its_evidence_decides(home, monkeypatch):
    fakes = Fakes()
    fakes.evidence_checks, fakes.evidence_actions = chromium_missing()
    monkeypatch.setattr(setup_cli, "_terminal", lambda: True)
    monkeypatch.setattr(setup_cli, "real_seams", lambda: fakes.seams())
    items = setup_cli.after_install()
    assert [item["item"] for item in items] == ["evidence:chromium"]
    assert summary_file(home).exists()  # the whole setup ran, and it recorded its summary


def test_later_installs_still_check_the_evidence_tools_without_a_setup_summary(home, monkeypatch, capsys):
    seen = []

    def evidence(environ):
        seen.append(dict(environ))
        return all_ok()

    monkeypatch.setattr(setup_cli, "evidence_for_install", evidence)
    setup_cli.after_install(interactive=False)
    assert seen and not summary_file(home).exists()
    assert "Next: run `simplicio-loop setup`" in capsys.readouterr().out  # the rest of setup is still the user's next step
