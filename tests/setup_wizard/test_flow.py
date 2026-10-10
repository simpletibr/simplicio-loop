"""`simplicio-loop setup` flow (#1588): the steps are fakes, the summary file and the exit codes are real."""
from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import github_cred, prereqs, setup_cli

from .fakes import OTHER_TOKEN, TOKEN, Fakes, check, credential, host, run, summary_file

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX modes and symlinks")


def test_first_run_writes_a_private_summary_without_secrets(home):
    fakes = Fakes()
    code, text = run(fakes, home)
    assert code == 0, text
    path = summary_file(home)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    doc = json.loads(path.read_text())
    assert doc["schema"] == "simplicio.setup/v1" and doc["updated_at"]
    assert doc["github"] == {"status": "ok", "source": "gh", "login": "octocat", "scopes": ["repo", "workflow"],
                             "missing_scopes": []}
    assert doc["default_host"] == "claude-code" and doc["default_login"] == "ok"
    assert [h["id"] for h in doc["hosts"]] == ["claude-code", "codex"]
    assert TOKEN not in path.read_text() and TOKEN not in text and "@" not in path.read_text()
    assert "ghp_...0042" in text and "octocat" in text  # the screen shows the masked token and the login


def test_second_run_is_unchanged_and_check_agrees(home):
    fakes = Fakes()
    run(fakes, home)
    path = summary_file(home)
    before = (path.stat().st_ino, path.stat().st_mtime_ns, path.read_text())
    code, text = run(fakes, home)
    assert code == 0 and "setup.json: unchanged" in text
    assert (path.stat().st_ino, path.stat().st_mtime_ns, path.read_text()) == before
    code, _ = run(fakes, home, check=True)
    assert code == 0


def test_check_changes_nothing_asks_nothing_and_exits_10_when_the_summary_is_missing(home):
    fakes = Fakes()
    fakes.tty = True
    code, text = run(fakes, home, check=True)
    assert code == setup_cli.PENDING and "summary" in text
    assert not (home / ".simplicio-loop").exists()
    resolve = [c for c in fakes.calls if c[0] == "resolve"][0][1]
    assert resolve["ask"] is None and resolve["provided"] is None  # --check never prompts
    assert [c for c in fakes.calls if c[0] == "ensure"][0][1]["dry_run"] is True
    assert "save" not in fakes.names()


def test_dry_run_writes_and_stores_nothing_even_with_a_new_token(home):
    fakes = Fakes()
    fakes.tty = False
    fakes.stdin_text = OTHER_TOKEN
    fakes.resolution = github_cred.Resolution(credential("provided", OTHER_TOKEN), (("provided", "ok"),))
    code, text = run(fakes, home, dry_run=True, token_stdin=True)
    assert code == 0, text
    assert not (home / ".simplicio-loop").exists() and fakes.stored is None
    assert OTHER_TOKEN not in text
    assert [c for c in fakes.calls if c[0] == "ensure"][0][1]["dry_run"] is True


def test_yes_reaches_ensure_and_the_default_is_no(home):
    fakes = Fakes()
    run(fakes, home)
    assert [c for c in fakes.calls if c[0] == "ensure"][0][1]["yes"] is False
    fakes.calls.clear()
    run(fakes, home, yes=True)
    assert [c for c in fakes.calls if c[0] == "ensure"][0][1]["yes"] is True


def test_without_a_terminal_it_never_asks_and_names_the_way_out(home):
    fakes = Fakes()
    fakes.resolution = github_cred.Resolution(None, (("env:GH_TOKEN", "missing"), ("gh", "missing")))
    code, text = run(fakes, home)
    assert code == setup_cli.PENDING
    assert [c for c in fakes.calls if c[0] == "resolve"][0][1]["ask"] is None
    assert "--github-token-stdin" in text and "github" in text
    assert json.loads(summary_file(home).read_text())["github"]["status"] == "missing"


def test_a_typed_token_is_stored_once_and_the_summary_says_stored(home):
    fakes = Fakes()
    fakes.tty = True
    fakes.resolution = github_cred.Resolution(credential("prompt"), (("prompt", "ok"),))
    code, text = run(fakes, home)
    assert code == 0 and fakes.stored == TOKEN
    assert [c for c in fakes.calls if c[0] == "resolve"][0][1]["ask"] is not None
    assert json.loads(summary_file(home).read_text())["github"]["source"] == "stored"
    fakes.calls.clear()
    run(fakes, home)  # the token is already stored: not written again
    assert "save" not in fakes.names()
    assert TOKEN not in text and TOKEN not in summary_file(home).read_text()


def test_a_token_from_gh_or_the_environment_is_never_copied(home):
    fakes = Fakes()
    for source in ("gh", "env:GH_TOKEN", "git-credential"):
        fakes.resolution = github_cred.Resolution(credential(source), ((source, "ok"),))
        run(fakes, home)
    assert "save" not in fakes.names() and fakes.stored is None
    assert json.loads(summary_file(home).read_text())["github"]["source"] == "git-credential"


def test_token_stdin_is_read_from_a_pipe_and_handed_over_as_provided(home):
    fakes = Fakes()
    fakes.stdin_text = f"  {OTHER_TOKEN}\n"
    fakes.resolution = github_cred.Resolution(credential("provided", OTHER_TOKEN), (("provided", "ok"),))
    code, text = run(fakes, home, token_stdin=True)
    assert code == 0 and fakes.stored == OTHER_TOKEN
    assert [c for c in fakes.calls if c[0] == "resolve"][0][1]["provided"] == OTHER_TOKEN
    assert OTHER_TOKEN not in text and OTHER_TOKEN not in summary_file(home).read_text()


def test_token_stdin_in_a_terminal_and_oversized_input_are_refused_with_nothing_changed(home, capsys):
    fakes = Fakes()
    fakes.tty = True
    assert run(fakes, home, token_stdin=True)[0] == 2
    fakes.tty = False
    fakes.stdin_text = "x" * 5000
    assert run(fakes, home, token_stdin=True)[0] == 2
    assert not (home / ".simplicio-loop").exists() and fakes.stored is None
    assert "setup refused" in capsys.readouterr().err


def test_a_rejected_or_unreachable_credential_is_pending_not_ok(home):
    fakes = Fakes()
    fakes.resolution = github_cred.Resolution(None, (("gh", "rejected"),))
    code, text = run(fakes, home)
    assert code == setup_cli.PENDING and "rejected" in text
    fakes.resolution = github_cred.Resolution(None, (("gh", "unreachable"),))
    code, text = run(fakes, home)
    assert code == setup_cli.PENDING and json.loads(summary_file(home).read_text())["github"]["status"] == "unverified"


def test_missing_scopes_are_pending_with_the_names(home):
    fakes = Fakes()
    fakes.resolution = github_cred.Resolution(credential(scopes=("repo",), missing=("workflow",)), (("gh", "ok"),))
    code, text = run(fakes, home)
    assert code == setup_cli.PENDING and "workflow" in text


def test_a_required_prerequisite_that_stays_missing_is_pending_with_its_fix(home):
    fakes = Fakes()
    fakes.checks = [check("python"), check("git", "missing", fix="sudo apt-get install -y git"), check("gh")]
    fakes.actions = [prereqs.Action(name="git", result="skipped", detail="sudo apt-get install -y git")]
    code, text = run(fakes, home)
    assert code == setup_cli.PENDING
    assert "git: missing. Fix: sudo apt-get install -y git" in text
    assert "git: skipped sudo apt-get install -y git" in text


def test_an_optional_missing_tool_is_not_pending(home):
    fakes = Fakes()
    fakes.checks = [check("python"), check("uv", "missing", required=False)]
    assert run(fakes, home)[0] == 0


def install_gh(home, content=b"#!/bin/sh\necho gh\n"):
    """The file `prereqs.ensure` would have written, and the action it would have reported."""
    gh = home / ".local" / "bin" / "gh"
    gh.parent.mkdir(parents=True, exist_ok=True)
    gh.write_bytes(content)
    gh.chmod(0o755)
    return gh


def trusted_of(fakes):
    return [c[1]["trusted"] for c in fakes.calls if c[0] == "check_all"]


def test_after_an_install_the_checks_run_again_with_that_exact_file_vouched_and_the_path_unchanged(home):
    fakes = Fakes()
    fakes.actions = [prereqs.Action(name="gh", result="installed", detail="2.60.0")]
    run(fakes, home)
    paths = [c[2] for c in fakes.calls if c[0] == "check_all"]
    assert paths == ["/usr/bin", "/usr/bin"]  # ~/.local/bin is never added to the PATH that detection searches
    assert trusted_of(fakes) == [{}, {"gh": str(home / ".local" / "bin" / "gh")}]


def test_only_gh_and_uv_installs_are_vouched(home):
    fakes = Fakes()
    fakes.actions = [prereqs.Action(name="python", result="installed", detail="x"), prereqs.Action(name="git", result="installed", detail="x"),
                     prereqs.Action(name="uv", result="installed", detail="x"), prereqs.Action(name="gh", result="unchanged", detail="x")]
    run(fakes, home)
    assert trusted_of(fakes)[1] == {"uv": str(home / ".local" / "bin" / "uv")}


def test_the_sha256_of_what_the_setup_installed_is_recorded_and_vouches_for_the_next_run(home):
    import hashlib
    gh = install_gh(home)
    fakes = Fakes()
    fakes.actions = [prereqs.Action(name="gh", result="installed", detail="2.60.0")]
    run(fakes, home)
    digest = hashlib.sha256(gh.read_bytes()).hexdigest()
    assert json.loads(summary_file(home).read_text())["installs"] == {"gh": digest}
    later = Fakes()
    code, text = run(later, home)
    assert trusted_of(later)[0] == {"gh": str(gh)}  # the folder is not searched, the recorded file is used
    assert "unchanged" in text and json.loads(summary_file(home).read_text())["installs"]["gh"] == digest


def test_a_changed_file_is_no_longer_vouched_and_the_record_is_dropped(home):
    gh = install_gh(home)
    fakes = Fakes()
    fakes.actions = [prereqs.Action(name="gh", result="installed", detail="2.60.0")]
    run(fakes, home)
    gh.write_bytes(b"#!/bin/sh\ntouch /tmp/planted\n")
    later = Fakes()
    run(later, home)
    assert trusted_of(later)[0] == {}
    assert "installs" in json.loads(summary_file(home).read_text()) and json.loads(summary_file(home).read_text())["installs"] == {}


def test_a_symlink_in_place_of_the_installed_file_is_not_vouched(home):
    gh = install_gh(home)
    fakes = Fakes()
    fakes.actions = [prereqs.Action(name="gh", result="installed", detail="2.60.0")]
    run(fakes, home)
    copy = home / "elsewhere"
    copy.write_bytes(gh.read_bytes())
    gh.unlink()
    gh.symlink_to(copy)
    later = Fakes()
    run(later, home)
    assert trusted_of(later)[0] == {}


def test_a_record_that_is_forged_or_names_another_tool_is_not_vouched(home):
    import hashlib
    install_gh(home)
    git = home / ".local" / "bin" / "git"
    git.write_bytes(b"x")
    first = Fakes()
    run(first, home)
    doc = json.loads(summary_file(home).read_text())
    doc["installs"] = {"gh": hashlib.sha256(b"something else").hexdigest(), "git": hashlib.sha256(b"x").hexdigest(), "uv": 123}
    summary_file(home).write_text(json.dumps(doc))
    summary_file(home).chmod(0o600)
    later = Fakes()
    run(later, home)
    assert trusted_of(later)[0] == {}


def test_a_tool_in_the_user_bin_that_the_setup_did_not_install_is_not_run_and_the_fix_says_to_remove_it(home):
    gh = install_gh(home)
    fakes = Fakes()
    fakes.checks = [check("python"), check("gh", "missing", fix="download it")]
    code, text = run(fakes, home)
    assert code == setup_cli.PENDING and f"remove {gh}" in text and "export PATH=" not in text and "download it" not in text


def test_unsafe_path_entries_are_listed_in_the_output_with_the_reason_and_are_not_pending(home):
    shared = home / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    path = os.pathsep.join(["reldir", str(shared), str(home / ".local" / "bin"), "/usr/bin"])
    code, text = run(Fakes(), home, path=path)
    assert code == 0, text
    assert "PATH entries that are not searched" in text
    assert "reldir  (relative)" in text and f"{shared}  (writable_by_others)" in text and f"{home / '.local' / 'bin'}  (user_local_bin)" in text
    _, raw = run(Fakes(), home, path=path, json_out=True)
    assert json.loads(raw)["path_warnings"] == [{"entry": "reldir", "reason": "relative"},
                                                {"entry": str(shared), "reason": "writable_by_others"},
                                                {"entry": str(home / ".local" / "bin"), "reason": "user_local_bin"}]


def test_a_clean_path_prints_no_path_section(home):
    code, text = run(Fakes(), home, path="/usr/bin")
    assert "PATH entries" not in text
    assert json.loads(run(Fakes(), home, path="/usr/bin", json_out=True)[1])["path_warnings"] == []


def test_node_is_asked_only_for_installed_hosts_that_need_it(home):
    fakes = Fakes()
    fakes.hosts = [host("codex", needs_node=True), host("claude-code"), host("gemini", installed=False, needs_node=True)]
    run(fakes, home)
    assert [c for c in fakes.calls if c[0] == "check_all"][0][1]["node_for"] == ["codex"]


def test_the_previous_default_is_kept_and_host_overrides_it(home):
    fakes = Fakes()
    fakes.hosts = [host("claude-code"), host("codex")]
    run(fakes, home, host="codex")
    assert json.loads(summary_file(home).read_text())["default_host"] == "codex"
    run(fakes, home)  # no --host: codex is still installed and logged in, so it stays
    assert json.loads(summary_file(home).read_text())["default_host"] == "codex"


def test_host_that_is_not_installed_is_refused_before_anything_runs(home, capsys):
    fakes = Fakes()
    assert run(fakes, home, host="gemini")[0] == 2
    assert not (home / ".simplicio-loop").exists() and "ensure" not in fakes.names()
    assert "not installed" in capsys.readouterr().err


def test_no_installed_host_is_pending_with_the_install_hint(home):
    fakes = Fakes()
    fakes.hosts = [host("claude-code", installed=False), host("codex", installed=False)]
    code, text = run(fakes, home)
    assert code == setup_cli.PENDING and "no_host_installed" in text
    assert json.loads(summary_file(home).read_text())["default_host"] is None


def test_json_output_is_one_document_with_the_masked_token_only(home):
    fakes = Fakes()
    code, text = run(fakes, home, json_out=True)
    doc = json.loads(text)
    assert code == 0 and doc["github"]["masked"] == "ghp_...0042" and doc["pending"] == []
    assert doc["summary_file"] == "updated" and {"actions", "checks", "hosts_detected", "undetectable_hosts"} <= set(doc)
    assert TOKEN not in text
    assert "masked" not in summary_file(home).read_text()


def test_a_loose_state_folder_or_a_symlinked_summary_is_refused(home, capsys):
    directory = home / ".simplicio-loop"
    directory.mkdir()
    directory.chmod(0o777)
    assert run(Fakes(), home)[0] == 2
    assert "cannot write" in capsys.readouterr().err
    directory.chmod(0o700)
    victim = home / "victim.json"
    victim.write_text("keep")
    (directory / "setup.json").symlink_to(victim)
    assert run(Fakes(), home)[0] == 2
    assert victim.read_text() == "keep"


def test_read_summary_rejects_other_schemas_and_big_files(home):
    directory = home / ".simplicio-loop"
    directory.mkdir()
    path = directory / "setup.json"
    assert setup_cli.read_summary(directory) is None
    path.write_text(json.dumps({"schema": "other/v1"}))
    assert setup_cli.read_summary(directory) is None
    path.write_text("x" * (setup_cli.MAX_SUMMARY_BYTES + 1))
    assert setup_cli.read_summary(directory) is None
    path.write_text(json.dumps({"schema": setup_cli.SCHEMA, "default_host": "codex"}))
    assert setup_cli.read_summary(directory)["default_host"] == "codex"


def plant_summary(home, mode=0o600, padding=0):
    directory = home / ".simplicio-loop"
    directory.mkdir(exist_ok=True)
    path = directory / "setup.json"
    path.write_text(json.dumps({"schema": setup_cli.SCHEMA, "default_host": "codex", "pad": "x" * padding}))
    path.chmod(mode)
    return directory, path


@pytest.mark.parametrize("mode, readable", [(0o600, True), (0o644, True), (0o620, False), (0o602, False), (0o666, False)])
def test_read_summary_reads_a_private_file_and_refuses_one_writable_by_group_or_others(home, mode, readable):
    directory, _ = plant_summary(home, mode)
    assert (setup_cli.read_summary(directory) is not None) is readable


def test_read_summary_does_not_follow_a_symlink(home):
    directory, path = plant_summary(home)
    real = home / "real.json"
    path.rename(real)
    path.symlink_to(real)
    assert setup_cli.read_summary(directory) is None


def test_read_summary_refuses_a_file_owned_by_someone_else(home, monkeypatch):
    directory, path = plant_summary(home)
    assert setup_cli.read_summary(directory) is not None
    monkeypatch.setattr(os, "geteuid", lambda: path.stat().st_uid + 1)
    assert setup_cli.read_summary(directory) is None


def test_read_summary_refuses_a_valid_summary_over_the_size_limit(home):
    directory, path = plant_summary(home)
    assert setup_cli.read_summary(directory) is not None
    directory, path = plant_summary(home, padding=setup_cli.MAX_SUMMARY_BYTES)  # still valid JSON of the right schema
    assert path.stat().st_size > setup_cli.MAX_SUMMARY_BYTES
    assert setup_cli.read_summary(directory) is None


def test_a_setup_json_that_is_a_fifo_does_not_hang_doctor_after_install_or_the_watcher(home):
    directory = home / ".simplicio-loop"
    directory.mkdir()
    os.mkfifo(directory / "setup.json")
    code = (
        "import io, json, sys\n"
        "from simplicio_loop import setup_cli\n"
        "out = io.StringIO()\n"
        "setup_cli.after_install(interactive=False, out=out)\n"
        "print(json.dumps([setup_cli.doctor_row()['summary'], setup_cli.default_family({'HOME': sys.argv[1]}), 'Next: run' in out.getvalue()]))\n"
    )
    root = str(Path(setup_cli.__file__).resolve().parents[1])
    done = subprocess.run([sys.executable, "-c", code, str(home)], capture_output=True, text=True, timeout=20,
                          env={**os.environ, "HOME": str(home), "PYTHONPATH": root})
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["setup has not run on this machine yet", None, True]


def test_a_non_linux_platform_is_marked_unverified(home, monkeypatch):
    monkeypatch.setattr(setup_cli.platform, "system", lambda: "Windows")
    code, text = run(Fakes(), home)
    assert "UNVERIFIED" in text
    assert json.loads(summary_file(home).read_text())["platform"]["os_verified"] is False


def test_after_install_runs_the_setup_in_a_terminal_and_only_hints_without_one(home, monkeypatch):
    calls = []
    monkeypatch.setattr(setup_cli, "run", lambda options, out=None: calls.append(options) or 0)
    out = io.StringIO()
    setup_cli.after_install(interactive=False, out=out)
    assert calls == [] and "simplicio-loop setup" in out.getvalue()
    setup_cli.after_install(interactive=True, out=io.StringIO())
    assert calls == [setup_cli.Options()]


def test_after_install_is_quiet_once_the_setup_has_run(home, monkeypatch):
    run(Fakes(), home)
    monkeypatch.setattr(setup_cli, "run", lambda *a, **k: pytest.fail("the setup must not start again"))
    for interactive in (True, False):
        out = io.StringIO()
        setup_cli.after_install(interactive=interactive, out=out)
        assert out.getvalue() == ""


def test_the_real_parser_flags_match_the_options():
    import argparse
    parser = argparse.ArgumentParser()
    setup_cli.add_arguments(parser)
    args = parser.parse_args(["--check", "--json", "--yes", "--github-token-stdin", "--host", "codex"])
    assert (args.check, args.json_out, args.yes, args.token_stdin, args.host) == (True, True, True, True, "codex")
    assert parser.parse_args([]).host is None


# --- what the watcher and doctor read ---------------------------------------------------------------------------------


def test_the_summary_names_the_exec_family_of_the_default_host_for_the_watcher(home):
    fakes = Fakes()
    run(fakes, home)
    assert json.loads(summary_file(home).read_text())["default_family"] == "claude"
    assert setup_cli.default_family({"HOME": str(home)}) == "claude"
    assert setup_cli.default_family({"SIMPLICIO_HOME": str(home), "HOME": "/nonexistent"}) == "claude"
    assert setup_cli.default_family({}) is None and setup_cli.default_family({"HOME": str(home / "other")}) is None
    fakes.hosts = [host("cursor")]  # a host the watcher cannot run has no family
    run(fakes, home)
    assert json.loads(summary_file(home).read_text())["default_family"] is None
    assert setup_cli.default_family({"HOME": str(home)}) is None


def test_doctor_row_reads_the_summary(home):
    directory = home / ".simplicio-loop"
    assert setup_cli.doctor_row(directory)["status"] == "warn" and "has not run" in setup_cli.doctor_row(directory)["summary"]
    fakes = Fakes()
    run(fakes, home)
    row = setup_cli.doctor_row(directory)
    assert (row["name"], row["status"], row["fix"]) == ("setup", "ok", None)
    assert "octocat" in row["summary"] and "claude-code" in row["summary"] and TOKEN not in json.dumps(row)
    fakes.resolution = github_cred.Resolution(None, ())
    fakes.checks = [check("python"), check("git", "missing", fix="x")]
    fakes.hosts = [host("claude-code", installed=False)]
    run(fakes, home)
    row = setup_cli.doctor_row(directory)
    assert row["status"] == "warn" and row["fix"] == "simplicio-loop setup"
    assert "git missing" in row["summary"] and "GitHub missing" in row["summary"] and "no default agent CLI" in row["summary"]
