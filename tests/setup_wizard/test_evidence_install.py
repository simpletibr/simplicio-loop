"""`simplicio-loop install` ends with the evidence tools (#1843), then the setup (#1841): it is complete only while every
required evidence tool is ok, and the exit code is 1 while one is not (2 when the setup failed, and 2 wins)."""
from __future__ import annotations

import io

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
    monkeypatch.setattr(setup_cli, "_setup_at_the_end", lambda out: 0)  # the setup has tests of its own
    assert setup_cli.after_install() == 1
    out = capsys.readouterr().out
    assert "evidence:chromium" in out and "download failed" in out and "simplicio-loop setup" in out


def test_install_is_not_complete_while_a_required_evidence_tool_is_missing(home, monkeypatch, capsys):
    target = home / "project"
    target.mkdir()
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda environ: chromium_missing())
    monkeypatch.setattr(setup_cli, "_setup_at_the_end", lambda out: 0)
    assert cli_impl.main(["install", "--target", str(target)]) == 1
    assert "install is not complete: evidence:chromium" in capsys.readouterr().out


def test_install_is_complete_when_the_evidence_tools_are_ok(home, monkeypatch):
    target = home / "project"
    target.mkdir()
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda environ: all_ok())
    monkeypatch.setattr(setup_cli, "_setup_at_the_end", lambda out: 0)
    assert cli_impl.main(["install", "--target", str(target)]) == 0


def test_the_setup_runs_after_the_evidence_step_and_a_missing_tool_still_decides(home, monkeypatch):
    fakes = Fakes()
    fakes.evidence_checks, fakes.evidence_actions = chromium_missing()
    monkeypatch.setattr(setup_cli, "evidence_for_install", lambda environ: chromium_missing())
    monkeypatch.setattr(setup_cli, "real_seams", lambda: fakes.seams())
    assert setup_cli.after_install(out=io.StringIO()) == 1
    assert summary_file(home).exists()  # the setup ran after the evidence step and recorded its summary


def test_every_install_checks_the_evidence_tools_before_the_setup(home, monkeypatch):
    seen, order = [], []

    def evidence(environ):
        seen.append(dict(environ))
        return all_ok()

    monkeypatch.setattr(setup_cli, "evidence_for_install", evidence)
    monkeypatch.setattr(setup_cli, "_setup_at_the_end", lambda out: order.append("setup") or 0)
    assert setup_cli.after_install(out=io.StringIO()) == 0
    assert seen and order == ["setup"]
