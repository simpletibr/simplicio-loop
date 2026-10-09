"""#1472: installed host skills resync from the package; doctor flags divergence.

Every test uses a fake HOME under tmp_path -- the real ~/.claude is never read or written.
"""
import shutil
import time
from pathlib import Path

import pytest

from scripts import doctor, operator_check
from simplicio_loop import skill_sync
from simplicio_loop.skill_sync import (
    HOST_SKILL_ROOTS,
    SKILLS,
    installed_skill_hosts,
    package_skills_dir,
    resync_installed_skills,
    skill_digest,
    stale_skills,
)

PKG = package_skills_dir()


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("SIMPLICIO_HOME", str(h))
    return h


def install(home, host, *, stale=(), skills=SKILLS):
    """Install the package skills under the host's layout; `stale` ones get old content."""
    root = home / HOST_SKILL_ROOTS[host]
    for skill in skills:
        shutil.copytree(PKG / skill, root / skill)
    for skill in stale:
        (root / skill / "SKILL.md").write_text("old skill from a previous release\n")
        (root / skill / "removed-upstream.md").write_text("gone from the package\n")
    return root


def test_package_skills_ship_inside_the_wheel_tree():
    assert PKG == Path(skill_sync.__file__).resolve().parent / "_bundle" / "skills"
    for skill in SKILLS:
        assert (PKG / skill / "SKILL.md").is_file(), skill


def test_digest_is_content_and_path_sensitive(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    (a / "SKILL.md").write_text("v1")
    d1 = skill_digest(a)
    assert d1 == skill_digest(a) and len(d1) == 64
    (a / "SKILL.md").write_text("v2")
    assert skill_digest(a) != d1
    b = tmp_path / "b"
    b.mkdir()
    (b / "OTHER.md").write_text("v2")
    assert skill_digest(b) != skill_digest(a)
    assert skill_digest(tmp_path / "missing") == ""


@pytest.mark.parametrize("host,rel", [
    ("claude", ".claude/skills"),
    ("cursor", ".cursor/skills"),
    ("grok", ".grok/skills"),
    ("vscode", ".vscode/simplicio-skills"),
    ("opencode", ".config/opencode/skills"),
])
def test_stale_skill_is_replaced_per_host_layout(home, host, rel):
    root = install(home, host, stale=["simplicio-loop"])
    assert root == home / rel
    assert installed_skill_hosts(home) == {host: root}
    assert [(e["host"], e["skill"], e["reason"]) for e in stale_skills(home)] == [
        (host, "simplicio-loop", "stale")]

    report = resync_installed_skills(home)

    assert report == {"synced": [host], "errors": []}
    assert skill_digest(root / "simplicio-loop") == skill_digest(PKG / "simplicio-loop")
    assert not (root / "simplicio-loop" / "removed-upstream.md").exists()
    assert stale_skills(home) == []


def test_each_host_is_compared_against_its_own_directory(home):
    install(home, "claude")  # up to date
    install(home, "cursor", stale=["simplicio-loop"])  # stale
    flagged = {(e["host"], e["skill"]) for e in stale_skills(home)}
    assert flagged == {("cursor", "simplicio-loop")}

    assert resync_installed_skills(home)["synced"] == ["cursor"]
    assert not (home / ".claude" / "skills" / "simplicio-loop" / "removed-upstream.md").exists()
    assert stale_skills(home) == []


def test_missing_companion_skill_is_installed(home):
    root = install(home, "claude", skills=["simplicio-loop"])
    missing = {e["skill"] for e in stale_skills(home) if e["reason"] == "missing"}
    assert missing == set(SKILLS) - {"simplicio-loop"}

    resync_installed_skills(home)

    for skill in SKILLS:
        assert skill_digest(root / skill) == skill_digest(PKG / skill)


def test_hosts_without_an_install_are_left_alone(home):
    assert installed_skill_hosts(home) == {}
    assert resync_installed_skills(home) == {"synced": [], "errors": []}
    assert list(home.iterdir()) == []


def test_resync_reports_copy_errors_per_host(home, monkeypatch):
    install(home, "claude", stale=["simplicio-loop"])

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(skill_sync.shutil, "copytree", boom)
    report = resync_installed_skills(home)
    assert report["synced"] == []
    assert report["errors"] == [{"host": "claude", "error": "simplicio-loop: disk full"}]


# -- doctor ---------------------------------------------------------------

def test_doctor_ok_when_nothing_installed(home, monkeypatch):
    monkeypatch.setattr(doctor, "HOME", home)
    r = doctor.chk_installed_skills_freshness()
    assert r["status"] == doctor.OK and r["tier"] == "OPTIONAL"
    assert r["msg"] == "no host has the skills installed"


def test_doctor_ok_when_installed_matches_package(home, monkeypatch):
    install(home, "claude")
    install(home, "cursor")
    monkeypatch.setattr(doctor, "HOME", home)
    r = doctor.chk_installed_skills_freshness()
    assert r["status"] == doctor.OK
    assert r["msg"] == "installed skills match the package"


def test_doctor_flags_stale_host_and_repair_resyncs(home, monkeypatch):
    install(home, "claude")
    install(home, "cursor", stale=["simplicio-loop"])
    monkeypatch.setattr(doctor, "HOME", home)

    r = doctor.chk_installed_skills_freshness()
    assert r["status"] == doctor.WARN
    assert r["msg"] == "diverges from the package in: cursor (1 skill dirs)"

    assert r["repair"]() is True
    assert doctor.chk_installed_skills_freshness()["status"] == doctor.OK


def test_doctor_registers_the_check():
    assert doctor.chk_installed_skills_freshness in doctor.CHECKS


# -- operator_check -------------------------------------------------------

def _ok_upgrade():
    class R:
        returncode = 0
        stderr = ""
    return R()


def test_maybe_upgrade_resyncs_after_a_successful_upgrade(tmp_path):
    calls = []

    def fake_resync():
        calls.append(1)
        return {"synced": ["claude"], "errors": []}

    d = operator_check.maybe_upgrade(tmp_path / "c.json", binaries=(), upgrade_fn=_ok_upgrade,
                                     resync_fn=fake_resync)
    assert d["upgraded"] is True
    assert calls == [1]
    assert d["skills_resynced"] == ["claude"]
    assert d["skills_sync_errors"] == []


def test_maybe_upgrade_does_not_resync_inside_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_OPERATOR_ALWAYS_LATEST", "0")
    cache = tmp_path / "c.json"
    operator_check.record_check(cache, {}, now=time.time())

    def must_not_run():
        raise AssertionError("resync ran inside the TTL window")

    d = operator_check.maybe_upgrade(cache, binaries=(), upgrade_fn=must_not_run,
                                     resync_fn=must_not_run)
    assert d["should_upgrade"] is False and d["upgraded"] is False
    assert d["skills_resynced"] == []


def test_maybe_upgrade_does_not_resync_when_the_upgrade_failed(tmp_path):
    def failed():
        class R:
            returncode = 1
            stderr = "no network"
        return R()

    def must_not_run():
        raise AssertionError("resync ran after a failed upgrade")

    d = operator_check.maybe_upgrade(tmp_path / "c.json", binaries=(), upgrade_fn=failed,
                                     resync_fn=must_not_run)
    assert d["upgraded"] is False and d["upgrade_error"] == "no network"
    assert d["skills_resynced"] == []


def test_maybe_upgrade_default_resync_uses_the_package_module(tmp_path, home):
    install(home, "claude", stale=["simplicio-loop"])

    d = operator_check.maybe_upgrade(tmp_path / "c.json", binaries=(), upgrade_fn=_ok_upgrade)

    assert d["skills_resynced"] == ["claude"]
    root = home / ".claude" / "skills"
    assert skill_digest(root / "simplicio-loop") == skill_digest(PKG / "simplicio-loop")
