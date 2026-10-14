"""host_detect (#1588): exact executable names, version and official login command only, one table."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from simplicio_loop import exec_auth, exec_planner, host_detect
from simplicio_loop.host_detect import HOSTS, Choice, HostStatus, choose_default, detect

REPO = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX sh scripts and modes")


@pytest.fixture
def bin_dir(tmp_path):
    path = tmp_path / "bin"
    path.mkdir()
    return path


def fake(bin_dir, name, body):
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def scan(bin_dir, tmp_path, **env):
    return {s.id: s for s in detect({"PATH": str(bin_dir), "HOME": str(tmp_path), **env})}


# --- finding ------------------------------------------------------------------------------------------------------


def test_only_the_exact_executable_name_counts(bin_dir, tmp_path):
    for decoy in ("claude-code", "claude-code-extra", "claude2", "xclaude", "claude.sh", "cod", "codex-old"):
        fake(bin_dir, decoy, "echo 9.9.9\n")
    (bin_dir / "codex").mkdir()  # a folder with the right name is not a program
    found = scan(bin_dir, tmp_path)
    assert not found["claude-code"].installed and not found["codex"].installed
    assert found["claude-code"].path is None and found["claude-code"].login == "n/a"


def test_an_installed_host_reports_path_and_version(bin_dir, tmp_path):
    claude = fake(bin_dir, "claude", "echo '2.1.292 (Claude Code)'\n")
    status = scan(bin_dir, tmp_path)["claude-code"]
    assert (status.installed, status.path, status.version) == (True, str(claude), "2.1.292")
    assert (status.name, status.watcher, status.exe_verified) == ("Claude Code", True, True)


def test_the_first_known_name_wins_and_only_rows_with_a_program_are_listed(bin_dir, tmp_path):
    fake(bin_dir, "kimi-cli", "echo 0.5.1\n")
    found = scan(bin_dir, tmp_path)
    assert found["kimi"].path.endswith("/kimi-cli") and found["kimi"].version == "0.5.1"
    assert set(found) == {h.id for h in HOSTS if h.exes} and not set(found) & set(host_detect.NO_EXECUTABLE)


def test_windows_style_names_come_from_which(tmp_path):
    found = {s.id: s for s in detect({"PATH": "", "HOME": str(tmp_path)},
                                     which=lambda name: "C:\\bin\\codex.cmd" if name == "codex" else None,
                                     run=lambda argv, env: (0, "codex-cli 0.154.0"))}
    assert found["codex"].path == "C:\\bin\\codex.cmd" and found["codex"].version == "0.154.0"
    assert not found["claude-code"].installed


# --- version and login ----------------------------------------------------------------------------------------------


def test_only_a_version_number_is_kept_never_the_output(bin_dir, tmp_path):
    fake(bin_dir, "gemini", "echo 'TOKEN=ghp_FAKEFAKEFAKEFAKEFAKE0001 version 1.2.3'\n")
    fake(bin_dir, "amp", "echo 'no number here ghp_FAKEFAKEFAKEFAKEFAKE0001'\n")
    fake(bin_dir, "goose", "echo 'goose 3.4.5-ghp_FAKEFAKEFAKEFAKEFAKE0001'\n")
    found = scan(bin_dir, tmp_path)
    assert (found["gemini"].version, found["goose"].version, found["amp"].version) == ("1.2.3", "3.4.5", None)
    assert "ghp_FAKE" not in json.dumps([s.as_dict() for s in found.values()])


def test_a_failing_version_command_gives_no_version(bin_dir, tmp_path):
    fake(bin_dir, "amp", "echo 1.2.3; exit 1\n")
    assert scan(bin_dir, tmp_path)["amp"].version is None


def test_a_hung_command_is_stopped_and_nothing_is_claimed(bin_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(host_detect, "VERSION_TIMEOUT_S", 0.3)
    fake(bin_dir, "claude", "exec /bin/sleep 30\n")
    started = time.monotonic()
    status = scan(bin_dir, tmp_path)["claude-code"]
    assert time.monotonic() - started < 5
    assert (status.installed, status.version, status.login) == (True, None, "UNVERIFIED")


@pytest.mark.parametrize("code, login", [(0, "ok"), (1, "no")])
def test_login_is_the_exit_code_of_the_official_status_command(bin_dir, tmp_path, code, login):
    log = tmp_path / "calls.txt"
    fake(bin_dir, "claude", f'echo "$@" >> {log}\n[ "$1" = auth ] && exit {code}\necho 2.0.0\n')
    assert scan(bin_dir, tmp_path)["claude-code"].login == login
    assert log.read_text().splitlines() == ["--version", "auth status"]


def test_codex_login_status_and_opencode_credential_count(bin_dir, tmp_path):
    fake(bin_dir, "codex", '[ "$1" = login ] && exit 0\necho codex-cli 0.1.0\n')
    fake(bin_dir, "opencode", '[ "$1" = auth ] && { echo "| x"; echo "  2 credentials"; exit 0; }\necho 1.0.0\n')
    found = scan(bin_dir, tmp_path)
    assert found["codex"].login == "ok" and found["opencode"].login == "ok"
    fake(bin_dir, "opencode", '[ "$1" = auth ] && { echo "0 credentials"; exit 0; }\necho 1.0.0\n')
    assert scan(bin_dir, tmp_path)["opencode"].login == "no"
    fake(bin_dir, "opencode", '[ "$1" = auth ] && { echo "garbage"; exit 0; }\necho 1.0.0\n')
    assert scan(bin_dir, tmp_path)["opencode"].login == "no"  # exit 0 alone is not a login for opencode


def test_a_host_without_an_official_status_command_is_never_asked_and_stays_unverified(bin_dir, tmp_path):
    log = tmp_path / "calls.txt"
    for name in ("grok", "agy", "gemini", "copilot", "kimi"):
        fake(bin_dir, name, f'echo "$@" >> {log}\necho 1.0.0\n')
    found = scan(bin_dir, tmp_path)
    assert {found[i].login for i in ("grok", "antigravity", "gemini", "github-copilot", "kimi")} == {"UNVERIFIED"}
    assert set(log.read_text().split()) == {"--version"}  # no login, auth or status argument was ever tried


def test_children_get_a_scrubbed_environment_and_the_given_home(bin_dir, tmp_path):
    dump = tmp_path / "env.txt"
    fake(bin_dir, "claude", f"/usr/bin/env > {dump}\necho 1.0.0\n")
    scan(bin_dir, tmp_path, GH_TOKEN="leak1", GITHUB_TOKEN="leak2", OPENAI_API_KEY="leak3", ANTHROPIC_API_KEY="leak4")
    text = dump.read_text()
    assert not [leak for leak in ("leak1", "leak2", "leak3", "leak4") if leak in text]
    assert f"HOME={tmp_path}" in text


# --- the table ------------------------------------------------------------------------------------------------------


def test_the_watcher_flag_follows_exec_planner(bin_dir, tmp_path):
    for spec in HOSTS:
        for exe in spec.exes[:1]:
            fake(bin_dir, exe, "echo 1.0.0\n")
    found = scan(bin_dir, tmp_path)
    assert {i for i, s in found.items() if s.watcher} == {"claude-code", "codex", "grok", "gemini", "antigravity", "opencode"}
    assert {h.family for h in HOSTS if h.family} == set(exec_planner.SUPPORTED_FAMILIES)


def test_the_table_is_sound():
    ids = [h.id for h in HOSTS]
    assert len(ids) == len(set(ids))
    names = [exe for h in HOSTS for exe in h.exes]
    assert len(names) == len(set(names)) and all(re.fullmatch(r"[a-z0-9][a-z0-9._-]*", exe) for exe in names)
    assert "cmd" not in names  # the Windows shell
    assert host_detect.NO_EXECUTABLE == ("vscode", "orca-dev", "mimo-code", "command-code")
    for wanted in ("claude-code", "codex", "grok", "kimi", "opencode", "antigravity", "github-copilot"):
        assert any(h.id == wanted and h.exes for h in HOSTS), wanted
    assert {h.exes[0] for h in HOSTS if h.id in ("claude-code", "grok", "kimi", "github-copilot", "antigravity")} == {
        "claude", "grok", "kimi", "copilot", "agy"}


def test_login_commands_agree_with_the_ones_the_watcher_uses():
    for spec in HOSTS:
        if spec.family in exec_auth._STATUS_ARGS:
            assert list(spec.login_args) == exec_auth._STATUS_ARGS[spec.family], spec.id
        elif spec.family:
            assert spec.login_args is None, spec.id  # exec_auth has no status command for it either


def _runtime_source():
    for candidate in (os.environ.get("SIMPLICIO_RUNTIME_SRC"), REPO.parent / "simplicio-runtime" / "src"):
        if candidate and (Path(candidate) / "host_registry.rs").is_file():
            return Path(candidate)
    return None


def test_the_ids_match_the_runtime_host_registry():
    source = _runtime_source()
    if source is None:
        pytest.skip("UNVERIFIED: the Simplicio Runtime source is not here (set SIMPLICIO_RUNTIME_SRC to its src folder)")
    registry = (source / "host_registry.rs").read_text()
    listed = re.search(r"const HOSTS: &\[&str\] = &\[(.*?)\];", registry, re.S).group(1)
    runtime_ids = set(re.findall(r'"([a-z0-9-]+)"', listed))
    assert len(runtime_ids) > 20
    adapters = (source / "commands" / "adapters.rs").read_text()
    adapter_ids = set(re.findall(r'AdapterSpec \{ id: "([a-z0-9-]+)"', adapters))
    ours = {h.id for h in HOSTS}
    assert runtime_ids <= ours, f"the Runtime has hosts this table lacks: {sorted(runtime_ids - ours)}"
    assert ours - runtime_ids <= adapter_ids, f"hosts the Runtime does not know: {sorted(ours - runtime_ids - adapter_ids)}"
    assert ours - runtime_ids == {"grok"}


# --- the default host -----------------------------------------------------------------------------------------------


def status(id, installed=True, login="ok"):
    return HostStatus(id, id, installed, f"/bin/{id}" if installed else None, "1.0.0" if installed else None,
                      login if installed else "n/a", True, "", False, False)


def test_requested_host_must_be_installed():
    rows = [status("codex", login="no"), status("gemini", installed=False)]
    assert choose_default(rows, requested="codex") == Choice("codex", "", "requested")
    assert choose_default(rows, requested="gemini") == Choice(None, "", "requested_not_installed")
    assert choose_default(rows, requested="nope") == Choice(None, "", "requested_not_installed")


def test_a_logged_in_host_is_chosen_by_order_and_a_logged_out_one_never_is():
    rows = [status("zzz"), status("codex"), status("claude-code", login="no"), status("grok", login="UNVERIFIED")]
    assert choose_default(rows) == Choice("codex", "ok", "chosen")
    assert choose_default([status("zzz"), status("aaa")]) == Choice("zzz", "ok", "chosen")  # unknown ids: table order


def test_the_previous_default_is_kept_while_it_is_still_usable():
    rows = [status("claude-code"), status("zzz")]
    assert choose_default(rows, previous="zzz") == Choice("zzz", "ok", "kept")
    gone = [status("claude-code"), status("zzz", login="no")]
    assert choose_default(gone, previous="zzz") == Choice("claude-code", "ok", "chosen")
    assert choose_default([status("claude-code")], previous="codex").host == "claude-code"


def test_unverified_hosts_are_the_second_choice():
    rows = [status("zzz", login="UNVERIFIED"), status("grok", login="UNVERIFIED"), status("codex", login="no")]
    assert choose_default(rows) == Choice("grok", "UNVERIFIED", "chosen_unverified")
    assert choose_default(rows, previous="zzz") == Choice("zzz", "UNVERIFIED", "kept")
    assert choose_default(rows + [status("claude-code")]).login == "ok"


def test_no_choice_says_why():
    assert choose_default([status("codex", login="no")]) == Choice(None, "", "no_host_logged_in")
    assert choose_default([status("codex", installed=False)]) == Choice(None, "", "no_host_installed")
    assert choose_default([]) == Choice(None, "", "no_host_installed")
