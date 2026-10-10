"""The hints of `setup` for an agent CLI it does not run (#1688, follow-ups of #1683): every path is quoted for a shell,
the fix fits the cause, `--host` names the hint, and the hint reaches `pending`."""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path

import pytest

from simplicio_loop import setup_cli

from .fakes import Fakes, host, run

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX modes and symlinks")

ROOT = Path(setup_cli.__file__).resolve().parents[1]


def put_exe(directory, name="claude"):
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / name
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def fix_of(line):
    """The words of the first command (between backticks) that follows `Fix:` on the line."""
    return shlex.split(re.search(r"Fix: [^`]*`([^`]+)`", line).group(1))


def ignored_line(text):
    return next(line for line in text.splitlines() if "ignored PATH entry" in line)


# --- 1. the docs ------------------------------------------------------------------------------------------------------


def test_the_setup_row_of_the_docs_has_whole_short_sentences():
    row = next(line for line in (ROOT / "docs" / "CLI_COMMANDS.md").read_text().splitlines() if line.startswith("| `setup` |"))
    assert "moves it. in `setup.json`" not in row
    assert not re.findall(r"\. (?!git\b|gh\b|uv\b)[a-z]", row), "a sentence starts in lower case: a loose fragment"  # git is a name
    assert ";" not in row


# --- 4. quoting and the fix of each cause -------------------------------------------------------------------------------


def test_a_path_with_a_space_is_quoted_in_the_sudo_install_command(tmp_path):
    spaced = tmp_path / "ho me"
    claude = put_exe(spaced / ".local" / "bin")
    fakes = Fakes()
    fakes.hosts = [host("claude-code", installed=False), host("codex", login="no")]
    code, text = run(fakes, spaced, path=os.pathsep.join([str(claude.parent), "/usr/bin"]))
    assert fix_of(ignored_line(text)) == ["sudo", "install", "-m", "755", str(claude), "/usr/local/bin/claude"]


def test_every_path_in_a_fix_is_one_shell_word():
    odd = "/tmp/a b/it's $HOME/bin/claude"
    allowed = {odd, os.path.dirname(odd), "/usr/local/bin/claude"}
    for reason in ("user_local_bin", "writable_by_others", "foreign_owner", "writable_parent"):
        words = [w for part in re.findall(r"`([^`]+)`", setup_cli._ignored_fix(odd, reason)) for w in shlex.split(part)]
        assert words, reason
        assert {w for w in words if "/" in w} <= allowed, reason


def test_writable_by_others_is_fixed_by_making_the_folder_private():
    words = fix_of("x Fix: " + setup_cli._ignored_fix("/tmp/a b/claude", "writable_by_others"))
    assert words == ["chmod", "go-w", "/tmp/a b"]


def test_a_folder_of_another_user_is_not_fixed_with_chmod():
    fix = setup_cli._ignored_fix("/opt/other user/bin/claude", "foreign_owner")
    assert "go-w" not in fix and "chmod" not in fix
    assert fix_of("x Fix: " + fix) == ["sudo", "install", "-m", "755", "/opt/other user/bin/claude", "/usr/local/bin/claude"]


def test_a_folder_under_a_writable_parent_is_fixed_on_that_parent(home):
    parent = home / "wr par"
    parent.mkdir()
    parent.chmod(0o777)  # anyone can rewrite it and there is no sticky bit
    claude = put_exe(parent / "bin")
    fakes = Fakes()
    fakes.hosts = [host("claude-code", installed=False), host("codex", login="no")]
    code, text = run(fakes, home, path=os.pathsep.join([str(claude.parent), "/usr/bin"]))
    assert "(writable_parent)" in text
    fix = ignored_line(text)
    assert "go-w" not in fix, "the hint for the folder itself does not help: the folder above is the problem"
    assert ["chmod", "o-w", str(parent)] == fix_of(fix)
    assert "sudo install" in fix and shlex.quote(str(claude)) in fix


def test_writable_by_others_end_to_end_names_the_folder_quoted(home):
    shared = home / "sh ared"
    shared.mkdir()
    shared.chmod(0o777)
    claude = put_exe(shared)
    fakes = Fakes()
    fakes.hosts = [host("claude-code", installed=False), host("codex", login="no")]
    code, text = run(fakes, home, path=os.pathsep.join([str(shared), "/usr/bin"]))
    assert "(writable_by_others)" in text
    assert fix_of(ignored_line(text)) == ["chmod", "go-w", str(shared)]


# --- 5. --host with the CLI only in an ignored entry ----------------------------------------------------------------------


def test_host_that_sits_only_in_the_user_bin_is_refused_with_the_hint(home, capsys):
    spaced = home / "ho me"
    claude = put_exe(spaced / ".local" / "bin")
    fakes = Fakes()
    fakes.hosts = [host("claude-code", installed=False), host("codex", login="no")]
    code, _ = run(fakes, spaced, path=os.pathsep.join([str(claude.parent), "/usr/bin"]), host="claude-code")
    err = capsys.readouterr().err
    assert code == 2
    assert "--host claude-code is not installed" in err
    assert f"{claude} is in an ignored PATH entry (user_local_bin) and is not run" in err
    assert fix_of(err) == ["sudo", "install", "-m", "755", str(claude), "/usr/local/bin/claude"]
    assert "ensure" not in fakes.names() and not (home / ".simplicio-loop").exists()


def test_host_that_is_nowhere_is_refused_without_a_hint(home, capsys):
    fakes = Fakes()
    assert run(fakes, home, host="gemini")[0] == 2
    err = capsys.readouterr().err
    assert "--host gemini is not installed" in err and "ignored PATH entry" not in err


def test_the_hint_of_another_host_is_not_shown_for_the_asked_one(home, capsys):
    claude = put_exe(home / ".local" / "bin")
    fakes = Fakes()
    fakes.hosts = [host("claude-code", installed=False), host("gemini", installed=False), host("codex", login="no")]
    assert run(fakes, home, path=os.pathsep.join([str(claude.parent), "/usr/bin"]), host="gemini")[0] == 2
    assert "claude" not in capsys.readouterr().err


# --- mutants: the ignored hosts and the pending hint ------------------------------------------------------------------------


def test_a_host_that_is_installed_is_never_listed_as_ignored(home):
    put_exe(home / ".local" / "bin", "claude")  # a second claude, in an entry that is not searched
    put_exe(home / ".local" / "bin", "codex")
    fakes = Fakes()
    fakes.hosts = [host("claude-code"), host("codex", installed=False)]
    path = os.pathsep.join([str(home / ".local" / "bin"), "/usr/bin"])
    code, text = run(fakes, home, path=path, json_out=True)
    rows = json.loads(text)["ignored_hosts"]
    assert [r["host"] for r in rows] == ["codex"]  # claude-code is installed, so its second program is not news
    assert "claude-code:" not in run(fakes, home, path=path)[1]


def test_the_pending_host_item_names_the_ignored_agent_cli(home):
    claude = put_exe(home / ".local" / "bin")
    fakes = Fakes()
    fakes.hosts = [host("claude-code", installed=False), host("codex", installed=False)]
    code, text = run(fakes, home, path=os.pathsep.join([str(claude.parent), "/usr/bin"]), json_out=True)
    item = next(p for p in json.loads(text)["pending"] if p["item"] == "host")
    assert code == setup_cli.PENDING
    assert item["fix"] == "claude-code is in an ignored PATH entry: see Agent CLIs above"
    assert "ignored PATH entry" in run(fakes, home, path=os.pathsep.join([str(claude.parent), "/usr/bin"]))[1].split("Pending")[1]


def test_without_an_ignored_agent_cli_the_pending_host_item_says_to_install_one(home):
    fakes = Fakes()
    fakes.hosts = [host("claude-code", installed=False)]
    item = next(p for p in json.loads(run(fakes, home, json_out=True)[1])["pending"] if p["item"] == "host")
    assert "install one agent CLI" in item["fix"] and "ignored" not in item["fix"]
