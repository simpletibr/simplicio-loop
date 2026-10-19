"""The wiring of `setup` (#1588): the main parser, the end of `install`, and the watcher's first CLI."""
from __future__ import annotations

import json
import os

import pytest

from simplicio_loop import setup_cli

from .fakes import Fakes, run, summary_file

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX modes and symlinks")


def test_the_command_is_wired_into_the_main_parser_and_install(home, monkeypatch, capsys):
    from simplicio_loop import cli_impl
    seen = []
    monkeypatch.setattr(setup_cli, "run", lambda options, **kw: seen.append(options) or 10)
    assert cli_impl.main(["setup", "--check", "--json", "--host", "codex", "--yes"]) == 10
    assert seen == [setup_cli.Options(check=True, json_out=True, yes=True, host="codex")]
    target = home / "project"
    target.mkdir()
    monkeypatch.setattr(setup_cli, "after_install", lambda **kw: print("AFTER-INSTALL") or 0)
    assert cli_impl.main(["install", "--target", str(target)]) == 0
    assert "AFTER-INSTALL" in capsys.readouterr().out
    assert cli_impl.main(["install", "--target", str(target), "--check"]) in (0, 10)
    assert "AFTER-INSTALL" not in capsys.readouterr().out  # --check, --dry-run and --json stay as they were
    assert cli_impl.main(["install", "--target", str(target), "--json"]) == 0
    assert "AFTER-INSTALL" not in capsys.readouterr().out


# --- install ends with the setup (#1841) -----------------------------------------------------------------------------


def _project(home):
    target = home / "project"
    target.mkdir(exist_ok=True)
    return str(target)


def test_a_non_interactive_install_runs_the_setup_at_the_end(home, monkeypatch, capsys):
    from simplicio_loop import cli_impl
    monkeypatch.setattr(setup_cli, "real_seams", Fakes().seams)  # pytest's stdio is not a terminal: no prompt can appear
    assert cli_impl.main(["install", "--target", _project(home)]) == 0
    assert json.loads(summary_file(home).read_text())["schema"] == "simplicio.setup/v1"
    assert "simplicio-loop setup (" in capsys.readouterr().out


def test_a_setup_that_fails_makes_install_exit_2_after_the_files_are_in_place(home, monkeypatch, capsys):
    from simplicio_loop import cli_impl
    (home / ".simplicio-loop").write_text("a file where the folder should be", encoding="utf-8")
    monkeypatch.setattr(setup_cli, "real_seams", Fakes().seams)
    assert cli_impl.main(["install", "--target", _project(home)]) == 2
    captured = capsys.readouterr()
    assert "installed:" in captured.out
    assert "setup refused" in captured.err
    nexts = [line for line in captured.err.splitlines() if line.startswith("next:")]
    assert len(nexts) == 1 and "simplicio-loop setup" in nexts[0], captured.err


def test_a_second_install_does_not_run_a_complete_setup_again(home, monkeypatch, capsys):
    from simplicio_loop import cli_impl
    monkeypatch.setattr(setup_cli, "real_seams", Fakes().seams)
    target = _project(home)
    assert cli_impl.main(["install", "--target", target]) == 0
    before = summary_file(home).read_bytes()
    monkeypatch.setattr(setup_cli, "run", lambda *a, **k: pytest.fail("a complete setup must not run again"))
    capsys.readouterr()
    assert cli_impl.main(["install", "--target", target]) == 0
    assert "already up to date" in capsys.readouterr().out
    assert summary_file(home).read_bytes() == before


def test_a_pending_setup_is_retried_by_the_next_install(home, monkeypatch):
    from simplicio_loop import cli_impl, github_cred
    target = _project(home)
    no_login = Fakes()
    no_login.resolution = github_cred.Resolution(None, (("gh", "missing"),))
    monkeypatch.setattr(setup_cli, "real_seams", no_login.seams)
    assert cli_impl.main(["install", "--target", target]) == 0
    assert json.loads(summary_file(home).read_text())["github"]["status"] == "missing"
    monkeypatch.setattr(setup_cli, "real_seams", Fakes().seams)
    assert cli_impl.main(["install", "--target", target]) == 0
    assert json.loads(summary_file(home).read_text())["github"]["status"] == "ok"


def test_a_failed_retry_leaves_the_existing_setup_json_as_it_was(home, monkeypatch, capsys):
    from dataclasses import replace

    from simplicio_loop import cli_impl, github_cred
    target = _project(home)
    no_login = Fakes()
    no_login.resolution = github_cred.Resolution(None, (("gh", "missing"),))
    monkeypatch.setattr(setup_cli, "real_seams", no_login.seams)
    assert cli_impl.main(["install", "--target", target]) == 0
    before = summary_file(home).read_bytes()

    def refused(environ, **kw):
        raise setup_cli.Refused("the GitHub step refuses this run")
    monkeypatch.setattr(setup_cli, "real_seams", lambda: replace(Fakes().seams(), resolve=refused))
    capsys.readouterr()
    assert cli_impl.main(["install", "--target", target]) == 2
    assert summary_file(home).read_bytes() == before
    assert "setup refused" in capsys.readouterr().err


def test_dry_run_check_and_json_never_run_the_setup(home, monkeypatch):
    from simplicio_loop import cli_impl
    monkeypatch.setattr(setup_cli, "run", lambda *a, **k: pytest.fail("--dry-run, --check and --json must not run setup"))
    target = _project(home)
    for flags in (["--dry-run"], ["--check"], ["--json"]):
        cli_impl.main(["install", "--target", target, *flags])
    assert not summary_file(home).exists()


def test_a_secret_typed_where_a_host_belongs_is_not_echoed_by_the_parser(capsys):
    from simplicio_loop import cli_impl
    with pytest.raises(SystemExit) as caught:
        cli_impl.main(["setup", "--bogus=ghp_FAKEFAKEFAKEFAKEFAKE0042"])
    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert "ghp_FAKE" not in err and "never an argument" in err


def test_the_watcher_puts_the_chosen_family_first_unless_the_families_are_set(home):
    from simplicio_loop import exec_planner, executor_select
    run(Fakes(), home)
    summary = json.loads(summary_file(home).read_text())
    summary["default_family"] = "opencode"
    summary_file(home).write_text(json.dumps(summary))
    env = {"HOME": str(home)}
    assert executor_select.exec_families(env) == ["opencode", *exec_planner.DEFAULT_FAMILIES]
    summary["default_family"] = "gemini"
    summary_file(home).write_text(json.dumps(summary))
    assert executor_select.exec_families(env) == ["gemini", "claude", "codex", "grok"]
    assert executor_select.exec_families({**env, "SIMPLICIO_EXEC_FAMILIES": "codex,claude"}) == ["codex", "claude"]
    summary["default_family"] = "mystery"
    summary_file(home).write_text(json.dumps(summary))
    assert executor_select.exec_families(env) == exec_planner.DEFAULT_FAMILIES
    assert executor_select.exec_families({}) == exec_planner.DEFAULT_FAMILIES
