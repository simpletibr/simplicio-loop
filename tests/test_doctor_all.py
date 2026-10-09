"""`simplicio-loop doctor` overview (#1575): login, update, distribution, Runtime, PATH operators, disk, setup.

Everything is injected or under tmp_path: no network, no real HOME, no real Runtime, no real /usr/local/bin.
The existing `doctor stack|source|mapper|--storage` outputs are pinned by their own tests, which are not touched.
"""
from __future__ import annotations

import json
import os
import time
from collections import namedtuple
from pathlib import Path

import pytest

from simplicio_loop import cli, distribution, doctor_overview as dov, self_update as su

FAKE_ACCESS = "fake-access-token-CCCC"
FAKE_REFRESH = "fake-refresh-token-DDDD"
FAKE_EMAIL = "wesley.fake@example.org"
MASKED = "w***@example.org"
Usage = namedtuple("Usage", "total used free")
GIB = 1 << 30
posix = pytest.mark.skipif(os.name == "nt", reason="shell script Runtime")


@pytest.fixture(autouse=True)
def normal_umask():
    """The login store refuses a folder that group or others can write: assume the usual umask."""
    old = os.umask(0o022)
    yield
    os.umask(old)


@pytest.fixture
def box(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SIMPLICIO_HOME", str(home))
    monkeypatch.setenv("PATH", str(bindir))
    for name in ("SIMPLICIO_247_LOGIN", "SIMPLICIO_AUTH_FILE"):
        monkeypatch.delenv(name, raising=False)
    return type("Box", (), {"home": home, "bin": bindir, "tmp": tmp_path, "login": home / ".simplicio" / "login.json",
                            "state": home / ".simplicio-loop"})


def put_login(path: Path, mode=0o600, **over):
    doc = {"access_token": FAKE_ACCESS, "refresh_token": FAKE_REFRESH, "access_expires_at": int(time.time()) + 900,
           "refresh_token_expires_at": 0,
           "verification": {"validated": {"user": {"email": FAKE_EMAIL},
                                          "entitlement": {"tier": "pro", "status": "active", "source": "stripe"}}}}
    doc.update(over)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    path.chmod(mode)
    return path


def fake_runtime(box, version="3.10.0"):
    script = box.bin / "simplicio"
    script.write_text(f"#!/bin/sh\necho 'simplicio {version}'\n")
    script.chmod(0o755)


def ok_operators(**kw):
    return [{"name": "simplicio-mapper", "path": None, "status": "absent", "reason_code": None, "found": None,
             "bundled": {}, "fix": None},
            {"name": "simplicio-dev-cli", "path": None, "status": "absent", "reason_code": None, "found": None,
             "bundled": "", "fix": None}]


def stale_operators(**kw):
    rows = ok_operators()
    rows[0].update(path="/usr/local/bin/simplicio-mapper", status="stale", reason_code="mapper_identity_missing",
                   fix="/usr/bin/python3 -m pip uninstall -y simplicio-mapper simplicio-cli && "
                       "/usr/bin/python3 -m pip install --force-reinstall simplicio-loop")
    return rows


def collect(box, **kw):
    kw.setdefault("operators", ok_operators)
    kw.setdefault("usage", lambda path: Usage(100 * GIB, 10 * GIB, 90 * GIB))
    kw.setdefault("installed", "3.48.1")
    kw.setdefault("kind", distribution.PIP)
    kw.setdefault("fetch", lambda: pytest.fail("the overview must not query the network offline"))
    kw.setdefault("repo", box.tmp / "no-repo")
    return dov.collect(**kw)


def put_setup(box):
    """A summary that `simplicio-loop setup` would leave on a healthy machine."""
    box.state.mkdir(parents=True, exist_ok=True)
    (box.state / "setup.json").write_text(json.dumps({
        "schema": "simplicio.setup/v1", "updated_at": "2026-10-09T00:00:00Z", "prereqs": [],
        "github": {"status": "ok", "source": "gh", "login": "octocat", "missing_scopes": []}, "default_host": "codex"}))


def check(doc, name):
    return next(c for c in doc["checks"] if c["name"] == name)


def everything(doc) -> str:
    return json.dumps(doc)


# --- login -----------------------------------------------------------------------------------------------------------


@posix
def test_a_good_login_shared_with_the_runtime_is_ok(box):
    put_login(box.login)
    fake_runtime(box)
    doc = collect(box)
    login = check(doc, "login")
    assert login["status"] == "ok"
    for text in (MASKED, "pro", "3.10.0", str(box.login)):
        assert text in login["summary"], text
    assert FAKE_ACCESS not in everything(doc) and FAKE_EMAIL not in everything(doc)
    runtime = check(doc, "runtime")
    assert runtime["status"] == "ok" and "3.10.0" in runtime["summary"] and "share" in runtime["summary"]


def test_a_missing_login_is_a_warning_with_the_fix(box):
    login = check(collect(box), "login")
    assert login["status"] == "warn" and login["fix"] == "simplicio-loop login"
    assert "not logged in" in login["summary"]


def test_an_expired_login_is_a_warning(box):
    put_login(box.login, access_expires_at=1, refresh_token="")
    login = check(collect(box), "login")
    assert login["status"] == "warn" and "login_expired" in login["summary"]


@posix
@pytest.mark.parametrize("mode", [0o644, 0o666])
def test_a_login_others_can_read_is_a_failure(box, mode):
    put_login(box.login, mode=mode)
    doc = collect(box)
    login = check(doc, "login")
    assert login["status"] == "fail" and login["fix"] == f"chmod 600 {box.login}" and doc["status"] == "fail"
    assert FAKE_ACCESS not in everything(doc)


@posix
def test_a_different_login_file_than_the_runtime_is_a_warning(box, monkeypatch):
    custom = put_login(box.tmp / "service" / "login.json")
    monkeypatch.setenv("SIMPLICIO_247_LOGIN", str(custom))
    fake_runtime(box)
    login = check(collect(box), "login")
    assert login["status"] == "warn" and "DIFFERENT" in login["summary"] and str(box.login) in login["summary"]


def test_a_different_login_file_is_not_a_problem_without_a_runtime(box, monkeypatch):
    custom = put_login(box.tmp / "service" / "login.json")
    monkeypatch.setenv("SIMPLICIO_247_LOGIN", str(custom))
    assert check(collect(box), "login")["status"] == "ok"


def test_the_runtime_is_optional(box):
    runtime = check(collect(box), "runtime")
    assert runtime["status"] == "ok" and "not installed" in runtime["summary"]


# --- update ----------------------------------------------------------------------------------------------------------


def test_update_is_offline_by_default_and_reads_the_cached_check(box):
    su.write_check({"installed": "3.48.1", "latest": "3.49.0", "update_available": True, "kind": "pip"}, box.state)
    doc = collect(box)
    update = check(doc, "update")
    assert update["status"] == "warn" and "3.49.0" in update["summary"] and "cached" in update["summary"]
    assert update["fix"] == "simplicio-loop update"
    assert update["detail"]["checked_at"] > 0 and "T" in update["summary"]  # an ISO timestamp


def test_a_cached_update_that_was_installed_since_is_not_reported(box):
    su.write_check({"installed": "3.48.1", "latest": "3.49.0", "update_available": True}, box.state)
    update = check(collect(box, installed="3.49.0"), "update")
    assert update["status"] == "ok"


def test_without_a_cached_check_update_says_so(box):
    update = check(collect(box), "update")
    assert update["status"] == "ok" and "no cached check" in update["summary"]
    assert "doctor --online" in update["summary"]


def test_online_queries_the_release_and_refreshes_the_cache(box):
    asked = []
    doc = collect(box, online=True, fetch=lambda: asked.append(1) or "v3.50.0")
    update = check(doc, "update")
    assert asked and update["status"] == "warn" and "3.50.0" in update["summary"] and "cached" not in update["summary"]
    assert su.read_check(box.state)["latest"] == "3.50.0"
    ok = check(collect(box, online=True, fetch=lambda: "v3.48.1"), "update")
    assert ok["status"] == "ok" and "up to date" in ok["summary"]


def test_online_failure_is_a_warning_not_a_crash(box):
    def boom():
        raise OSError("offline")

    update = check(collect(box, online=True, fetch=boom), "update")
    assert update["status"] == "warn" and "could not" in update["summary"] and "offline" in update["summary"]


# --- distribution ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", [distribution.PIP, distribution.SOURCE, distribution.BINARY])
def test_the_distribution_kind_is_shown(box, kind):
    dist = check(collect(box, kind=kind), "distribution")
    assert dist["status"] == "ok" and kind in dist["summary"] and dist["detail"]["kind"] == kind


def test_the_real_distribution_kind_is_detected_by_default(box):
    doc = dov.collect(operators=ok_operators, usage=lambda p: Usage(1, 1, 90 * GIB), installed="3.48.1",
                      fetch=lambda: "v3.48.1", repo=box.tmp)
    assert check(doc, "distribution")["detail"]["kind"] in {"pip", "source", "binary"}


# --- operators on PATH -------------------------------------------------------------------------------------------------


def test_a_stale_operator_on_path_is_a_warning_with_the_exact_fix(box):
    doc = collect(box, operators=stale_operators)
    ops = check(doc, "operators")
    assert ops["status"] == "warn" and "/usr/local/bin/simplicio-mapper" in ops["summary"]
    assert "mapper_identity_missing" in ops["summary"]
    assert ops["fix"].startswith("/usr/bin/python3 -m pip uninstall -y simplicio-mapper")
    assert ops["detail"]["stale"][0]["name"] == "simplicio-mapper"


def test_matching_operators_are_ok(box):
    assert check(collect(box), "operators")["status"] == "ok"


def test_the_frozen_binary_is_passed_to_the_operator_check(box):
    seen = {}
    collect(box, kind=distribution.BINARY, operators=lambda **kw: seen.update(kw) or ok_operators())
    assert seen["frozen_exe"]
    seen.clear()
    collect(box, kind=distribution.PIP, operators=lambda **kw: seen.update(kw) or ok_operators())
    assert seen["frozen_exe"] is None


# --- disk ------------------------------------------------------------------------------------------------------------


def test_disk_below_the_squad_capacity_floor_is_a_warning(box):
    from simplicio_loop import squad_capacity

    low = lambda path: Usage(100 * GIB, 99 * GIB, squad_capacity.DISK_FLOOR_BYTES - 1)
    disk = check(collect(box, usage=low), "disk")
    assert disk["status"] == "warn" and "free" in disk["summary"] and "floor" in disk["summary"]
    just = lambda path: Usage(100 * GIB, 98 * GIB, squad_capacity.DISK_FLOOR_BYTES)
    assert check(collect(box, usage=just), "disk")["status"] == "ok"


def test_disk_looks_at_the_nearest_existing_folder_of_each_state_dir(box, tmp_path):
    asked = []
    repo = tmp_path / "repo"
    (repo / ".simplicio-loop").mkdir(parents=True)
    collect(box, usage=lambda path: asked.append(Path(path)) or Usage(1, 1, 90 * GIB), repo=repo)
    assert box.home in asked  # ~/.simplicio-loop does not exist yet: its parent is measured
    assert repo / ".simplicio-loop" in asked


# --- the whole document and the command -----------------------------------------------------------------------------------


def test_the_document_has_every_section_and_the_worst_status(box):
    doc = collect(box)
    assert doc["schema"] == "simplicio.doctor/v1"
    assert [c["name"] for c in doc["checks"]] == ["login", "update", "distribution", "runtime", "operators", "disk", "setup"]
    assert doc["status"] == "warn"  # no login in the box
    put_login(box.login)
    assert collect(box)["status"] == "warn" and check(collect(box), "setup")["fix"] == "simplicio-loop setup"  # setup did not run
    put_setup(box)
    assert collect(box)["status"] == "ok" and "octocat" in check(collect(box), "setup")["summary"]


def test_run_prints_one_line_per_check_with_the_fix_and_returns_0_for_warnings(box, capsys):
    rc = dov.run(operators=stale_operators, usage=lambda p: Usage(1, 1, 90 * GIB), installed="3.48.1",
                 kind=distribution.PIP, fetch=lambda: "v3.48.1", repo=box.tmp)
    out = capsys.readouterr().out
    assert rc == 0
    for name in ("login", "update", "distribution", "runtime", "operators", "disk", "setup"):
        assert name in out
    assert "warn" in out and "fix:" in out and "pip install --force-reinstall simplicio-loop" in out


def test_run_returns_1_when_a_check_fails(box, capsys):
    put_login(box.login, mode=0o644)
    rc = dov.run(operators=ok_operators, usage=lambda p: Usage(1, 1, 90 * GIB), installed="3.48.1",
                 kind=distribution.PIP, fetch=lambda: "v3.48.1", repo=box.tmp)
    assert rc == (1 if os.name != "nt" else 0)
    assert "fail" in capsys.readouterr().out or os.name == "nt"


def test_run_json_is_one_document_without_secrets(box, capsys):
    put_login(box.login)
    put_setup(box)
    rc = dov.run(as_json=True, operators=ok_operators, usage=lambda p: Usage(1, 1, 90 * GIB), installed="3.48.1",
                 kind=distribution.PIP, fetch=lambda: "v3.48.1", repo=box.tmp)
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert rc == 0 and doc["status"] == "ok"
    assert FAKE_ACCESS not in out and FAKE_REFRESH not in out and FAKE_EMAIL not in out


def test_doctor_login_shows_only_the_login_section(box, capsys):
    put_login(box.login)
    assert dov.run(only="login", as_json=True) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [c["name"] for c in doc["checks"]] == ["login"]


def test_the_commands_are_wired(box, capsys, monkeypatch):
    monkeypatch.setattr(dov.path_operators, "check", ok_operators)
    put_login(box.login)
    assert cli.main(["doctor", "login", "--json"]) == 0
    assert [c["name"] for c in json.loads(capsys.readouterr().out)["checks"]] == ["login"]
    assert cli.main(["doctor", "all", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["checks"]) == 7
    assert cli.main(["doctor", "--json"]) == 0  # a bare `doctor` is the overview
    assert len(json.loads(capsys.readouterr().out)["checks"]) == 7


def test_the_old_doctor_forms_still_exist():
    import subprocess, sys

    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    out = subprocess.run([sys.executable, "-m", "simplicio_loop.cli", "doctor", "--help"], capture_output=True,
                         text=True, env=env, timeout=60).stdout
    for word in ("stack", "source", "mapper", "--storage", "all", "login", "--online"):
        assert word in out, word
