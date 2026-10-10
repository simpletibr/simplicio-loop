"""PATH hygiene (#1657, point 3 of #1637): a program in a relative, other-writable or ~/.local/bin PATH entry is never run.

The fake programs below write a marker file when they run. A marker that exists means the setup executed code from an
unsafe directory. Everything here runs real programs: no fake `which` and no fake `run`.
"""
from __future__ import annotations

import os
import sys

import pytest

from simplicio_loop import host_detect, prereqs, setup_hardening

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX sh scripts and modes")


def program(directory, name, body):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


class Machine:
    """A PATH with three unsafe entries followed by one safe entry; every unsafe entry holds fake `codex` and `gh`."""

    def __init__(self, tmp_path, monkeypatch):
        self.home = tmp_path / "home"
        self.markers = {}
        monkeypatch.chdir(tmp_path)
        shared = tmp_path / "shared"
        shared.mkdir()
        shared.chmod(0o777)
        self.unsafe = {"relative": tmp_path / "reldir", "writable_by_others": shared, "user_local_bin": self.home / ".local" / "bin"}
        for kind, directory in self.unsafe.items():
            self.markers[kind] = tmp_path / f"marker-{kind}"
            for name, output in (("codex", "codex-cli 9.9.9"), ("gh", "gh version 9.9.9 (2024-11-01)")):
                program(directory, name, f": > {self.markers[kind]}\necho '{output}'\n")
        self.good = tmp_path / "good"
        self.good_codex = program(self.good, "codex", "echo 'codex-cli 1.2.3'\n")
        self.good_gh = program(self.good, "gh", "echo 'gh version 2.60.0 (2024-11-01)'\n")
        self.entries = {"relative": "reldir", "writable_by_others": str(shared), "user_local_bin": str(self.unsafe["user_local_bin"])}
        self.environ = self.environ_for(*self.entries)

    def environ_for(self, *kinds):
        """HOME plus a PATH of the named unsafe entries (in that order) and then the safe one."""
        return {"PATH": os.pathsep.join([*(self.entries[kind] for kind in kinds), str(self.good)]), "HOME": str(self.home)}

    def ran(self):
        return sorted(kind for kind, marker in self.markers.items() if marker.exists())


@pytest.fixture
def machine(tmp_path, monkeypatch):
    return Machine(tmp_path, monkeypatch)


KINDS = ("relative", "writable_by_others", "user_local_bin")


@pytest.mark.parametrize("kind", KINDS)
def test_host_detection_never_runs_a_program_from_an_unsafe_path_entry(machine, kind):
    found = {s.id: s for s in host_detect.detect(machine.environ_for(kind))}
    assert machine.ran() == []
    assert found["codex"].installed and found["codex"].path == str(machine.good_codex) and found["codex"].version == "1.2.3"


@pytest.mark.parametrize("kind", KINDS)
def test_check_all_never_runs_a_program_from_an_unsafe_path_entry(machine, kind):
    checks = {c.name: c for c in prereqs.check_all(machine.environ_for(kind), platform="linux", interpreter=sys.executable)}
    assert machine.ran() == []
    assert checks["gh"].status == "ok" and checks["gh"].path == str(machine.good_gh) and checks["gh"].version == "2.60.0"


def test_a_tool_found_only_in_unsafe_entries_counts_as_missing_and_is_still_not_run(machine):
    machine.good_gh.unlink()
    machine.good_codex.unlink()
    checks = {c.name: c for c in prereqs.check_all(machine.environ, platform="linux", interpreter=sys.executable)}
    found = {s.id: s for s in host_detect.detect(machine.environ)}
    assert machine.ran() == []
    assert checks["gh"].status == "missing" and not found["codex"].installed


def test_the_probe_environment_of_check_all_has_no_unsafe_entry(machine, monkeypatch):
    # the real runner reads os.environ: the unsafe entries are there, the probe must not see them
    seen = machine.good.parent / "probe-path.txt"
    program(machine.good, "gh", f"echo \"$PATH\" > {seen}\necho 'gh version 2.60.0 (2024-11-01)'\n")
    monkeypatch.setenv("PATH", machine.environ["PATH"])
    monkeypatch.setenv("HOME", machine.environ["HOME"])
    prereqs.check_all(dict(machine.environ), platform="linux", interpreter=sys.executable)
    assert seen.read_text().strip() == str(machine.good)


def test_the_probe_environment_of_host_detection_has_no_unsafe_entry(machine):
    seen = machine.good.parent / "host-path.txt"
    program(machine.good, "codex", f"echo \"$PATH\" > {seen}\necho 'codex-cli 1.2.3'\n")
    host_detect.detect(machine.environ)
    assert seen.read_text().strip() == str(machine.good)


def test_a_tool_the_setup_vouches_for_is_used_from_its_exact_path_even_inside_local_bin(machine):
    vouched = machine.unsafe["user_local_bin"] / "gh"
    checks = {c.name: c for c in prereqs.check_all(machine.environ, platform="linux", interpreter=sys.executable,
                                                   trusted={"gh": str(vouched)})}
    assert checks["gh"].path == str(vouched)
    assert machine.ran() == ["user_local_bin"]  # only the exact vouched file ran; the other entries stay unrun


def test_a_vouched_path_that_is_not_a_file_is_ignored(machine, tmp_path):
    checks = {c.name: c for c in prereqs.check_all(machine.environ, platform="linux", interpreter=sys.executable,
                                                   trusted={"gh": str(tmp_path / "gone")})}
    assert checks["gh"].path == str(machine.good_gh)


def test_safe_which_finds_nothing_in_an_empty_path_and_uses_the_default_path_without_one(machine):
    assert setup_hardening.safe_which({"PATH": "", "HOME": str(machine.home)})("gh") is None
    assert setup_hardening.safe_which({"HOME": str(machine.home)})("sh") is not None  # os.defpath has /bin and /usr/bin


def test_setup_with_the_real_steps_runs_nothing_from_unsafe_entries_and_prints_each_warning(machine, monkeypatch):
    import io

    from simplicio_loop import github_cred, setup_cli
    monkeypatch.setenv("HOME", str(machine.home))
    monkeypatch.delenv("SIMPLICIO_HOME", raising=False)
    seams = setup_cli.Seams(
        detect=host_detect.detect, check_all=prereqs.check_all, ensure=prereqs.ensure,
        resolve=lambda environ, **kw: github_cred.Resolution(None, ()), save_token=lambda *a: None, load_token=lambda d: None,
        isatty=lambda: False, ask=lambda: "", read_stdin=lambda size: "")
    out = io.StringIO()
    setup_cli.run(setup_cli.Options(check=True), environ=machine.environ, seams=seams, out=out)
    text = out.getvalue()
    assert machine.ran() == []
    for entry, reason in (("reldir", "relative"), (machine.entries["writable_by_others"], "writable_by_others"),
                          (machine.entries["user_local_bin"], "user_local_bin")):
        assert f"{entry}  ({reason})" in text


def test_python_install_never_runs_a_uv_that_setup_did_not_verify(tmp_path):
    marker = tmp_path / "uv-ran"
    bin_dir = tmp_path / "home" / ".local" / "bin"
    program(bin_dir, "uv", f": > {marker}\nexit 0\n")  # there before the setup: nobody checked its bytes

    def no_network(url):
        raise AssertionError(url)

    checks = [prereqs.Check("python", "missing", True, None, None, "3.11", "uv python install 3.11", "user"),
              prereqs.Check("uv", "missing", True, None, None, None, "", "user")]
    actions = prereqs.ensure(checks, environ={"HOME": str(tmp_path / "home"), "PATH": "/usr/bin"}, bin_dir=bin_dir,
                             platform="linux", machine="x86_64", get=no_network, pins={})
    assert not marker.exists()
    assert [(a.name, a.result) for a in actions] == [("uv", "unchanged"), ("python", "skipped")]
    assert "remove" in actions[0].detail and "uv" in actions[1].detail


def test_the_real_runner_resolves_a_bare_program_name_only_through_safe_path_entries(machine, monkeypatch):
    monkeypatch.setenv("PATH", machine.environ["PATH"])
    monkeypatch.setenv("HOME", machine.environ["HOME"])
    assert prereqs._run(["gh", "--version"], 5) == (0, "gh version 2.60.0 (2024-11-01)\n")  # the safe gh answered
    assert machine.ran() == []
