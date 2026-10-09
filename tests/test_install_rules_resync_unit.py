"""#1472: installed host rules resync from the package; doctor flags stale rules.

Every test uses a fake HOME under tmp_path -- the real ~/.claude is never read or written.
"""
import shutil
import time
from pathlib import Path

import pytest

import host_rule_sync
from scripts import doctor, operator_check
from simplicio_loop import host_rules
from simplicio_loop.host_rules import (
    RULE_NAME,
    installed_rules,
    resync_installed_rules,
    stale_rules,
)
from simplicio_loop.skill_sync import HOST_RULE_REF, package_skills_dir, resync_installed_skills, stale_skills

OLD = "# old operator flow\nSIMPLICIO_LOOP_STRICT=0\n"
BODY = host_rules.RULE_SRC.read_text(encoding="utf-8")


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("SIMPLICIO_HOME", str(h))
    return h


def put(home, rel, text=OLD):
    p = home / rel / RULE_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_packaged_rule_ships_in_the_wheel_tree_and_matches_the_source():
    assert host_rules.RULE_SRC == (Path(host_rules.__file__).resolve().parent
                                   / "_bundle" / "host-rules" / RULE_NAME)
    repo = Path(__file__).resolve().parents[1]
    assert BODY == (repo / "packaging" / "host-rules" / RULE_NAME).read_text(encoding="utf-8")


def test_cli_script_reuses_the_package_implementation():
    assert host_rule_sync.sync is host_rules.sync
    assert host_rule_sync.check is host_rules.check


@pytest.mark.parametrize("surface,rel", [
    ("claude_rules", ".claude/rules"),
    ("cursor_user", ".cursor/rules"),
    ("grok", ".grok/rules"),
])
def test_stale_rule_is_rewritten_only_where_installed(home, surface, rel):
    path = put(home, rel)
    assert installed_rules(home) == {surface: path}
    assert stale_rules(home) == [{"surface": surface, "path": str(path)}]

    assert resync_installed_rules(home) == {"synced": [surface], "errors": []}

    assert path.read_text(encoding="utf-8") == BODY
    assert stale_rules(home) == []
    created = {p.relative_to(home).as_posix() for p in home.rglob("*") if p.is_file()}
    assert created == {path.relative_to(home).as_posix()}


def test_claude_and_cursor_are_compared_independently(home):
    put(home, ".claude/rules", BODY)
    cursor = put(home, ".cursor/rules")
    assert [e["surface"] for e in stale_rules(home)] == ["cursor_user"]
    assert resync_installed_rules(home)["synced"] == ["cursor_user"]
    assert cursor.read_text(encoding="utf-8") == BODY


def test_foreign_rule_file_is_never_overwritten(home):
    path = put(home, ".claude/rules", "my own team rule, nothing to do with the loop\n")
    assert installed_rules(home) == {}
    assert resync_installed_rules(home) == {"synced": [], "errors": []}
    assert path.read_text(encoding="utf-8") == "my own team rule, nothing to do with the loop\n"


def test_nothing_installed_writes_nothing(home):
    assert resync_installed_rules(home) == {"synced": [], "errors": []}
    assert list(home.iterdir()) == []


def test_rule_write_errors_are_reported_per_surface(home, monkeypatch):
    put(home, ".claude/rules")

    def boom(path, content):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(host_rules, "_write", boom)
    assert resync_installed_rules(home) == {
        "synced": [], "errors": [{"host": "claude_rules", "error": "read-only filesystem"}]}


# -- the rule ref inside the installed loop skill ------------------------------

def test_rule_ref_in_installed_skill_is_not_skill_divergence_and_survives_skill_resync(home):
    skill = home / ".claude" / "skills" / "simplicio-loop"
    shutil.copytree(package_skills_dir() / "simplicio-loop", skill)
    host_rules.sync(do_global=True, target=None)  # what the installer does: writes the ref
    ref = skill / HOST_RULE_REF
    assert ref.read_text(encoding="utf-8") == BODY
    assert "simplicio-loop" not in {e["skill"] for e in stale_skills(home)}

    (skill / "SKILL.md").write_text("old\n")
    ref.write_text(OLD)
    assert ("simplicio-loop", "stale") in {(e["skill"], e["reason"]) for e in stale_skills(home)}
    resync_installed_skills(home)
    assert ref.read_text(encoding="utf-8") == OLD  # skill resync leaves the rule ref alone
    assert [e["surface"] for e in stale_rules(home)] == ["claude_skill_ref"]
    resync_installed_rules(home)
    assert ref.read_text(encoding="utf-8") == BODY


# -- doctor ---------------------------------------------------------------

def test_doctor_rules_ok_when_nothing_installed(home, monkeypatch):
    monkeypatch.setattr(doctor, "HOME", home)
    r = doctor.chk_installed_rules_freshness()
    assert (r["status"], r["tier"], r["msg"]) == (
        doctor.OK, "OPTIONAL", "no host has the rules installed")


def test_doctor_rules_ok_when_fresh(home, monkeypatch):
    put(home, ".claude/rules", BODY)
    put(home, ".cursor/rules", BODY)
    monkeypatch.setattr(doctor, "HOME", home)
    r = doctor.chk_installed_rules_freshness()
    assert (r["status"], r["msg"]) == (doctor.OK, "installed rules match the package")


def test_doctor_flags_stale_rules_and_repair_rewrites(home, monkeypatch):
    put(home, ".claude/rules", BODY)
    cursor = put(home, ".cursor/rules")
    monkeypatch.setattr(doctor, "HOME", home)

    r = doctor.chk_installed_rules_freshness()
    assert r["status"] == doctor.WARN
    assert r["msg"] == "diverges from the package in: cursor_user"

    assert r["repair"]() is True
    assert cursor.read_text(encoding="utf-8") == BODY
    assert doctor.chk_installed_rules_freshness()["status"] == doctor.OK


def test_doctor_registers_the_rules_check():
    assert doctor.chk_installed_rules_freshness in doctor.CHECKS


# -- operator_check ---------------------------------------------------------

def _ok_upgrade():
    class R:
        returncode = 0
        stderr = ""
    return R()


def test_maybe_upgrade_resyncs_rules_after_a_successful_upgrade(tmp_path):
    calls = []

    def fake_rules():
        calls.append(1)
        return {"synced": ["claude_rules"], "errors": []}

    d = operator_check.maybe_upgrade(
        tmp_path / "c.json", binaries=(), upgrade_fn=_ok_upgrade,
        resync_fn=lambda: {"synced": [], "errors": []}, resync_rules_fn=fake_rules)
    assert calls == [1]
    assert d["rules_resynced"] == ["claude_rules"]
    assert d["rules_sync_errors"] == []


def test_maybe_upgrade_does_not_resync_rules_inside_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_OPERATOR_ALWAYS_LATEST", "0")
    cache = tmp_path / "c.json"
    operator_check.record_check(cache, {}, now=time.time())

    def must_not_run():
        raise AssertionError("resync ran inside the TTL window")

    d = operator_check.maybe_upgrade(cache, binaries=(), upgrade_fn=must_not_run,
                                     resync_fn=must_not_run, resync_rules_fn=must_not_run)
    assert d["upgraded"] is False and d["rules_resynced"] == []


def test_maybe_upgrade_default_resync_refreshes_skills_and_rules(tmp_path, home):
    skill = home / ".claude" / "skills" / "simplicio-loop"
    shutil.copytree(package_skills_dir() / "simplicio-loop", skill)
    (skill / "SKILL.md").write_text("old\n")
    rule = put(home, ".claude/rules")

    d = operator_check.maybe_upgrade(tmp_path / "c.json", binaries=(), upgrade_fn=_ok_upgrade)

    assert d["skills_resynced"] == ["claude"]
    assert d["rules_resynced"] == ["claude_rules"]
    assert rule.read_text(encoding="utf-8") == BODY
    assert (skill / "SKILL.md").read_text(encoding="utf-8") != "old\n"
