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
    monkeypatch.setattr(setup_cli, "after_install", lambda **kw: print("AFTER-INSTALL"))
    assert cli_impl.main(["install", "--target", str(target)]) == 0
    assert "AFTER-INSTALL" in capsys.readouterr().out
    assert cli_impl.main(["install", "--target", str(target), "--check"]) in (0, 10)
    assert "AFTER-INSTALL" not in capsys.readouterr().out  # --check, --dry-run and --json stay as they were
    assert cli_impl.main(["install", "--target", str(target), "--json"]) == 0
    assert "AFTER-INSTALL" not in capsys.readouterr().out


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
