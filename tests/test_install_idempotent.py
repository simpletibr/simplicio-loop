"""`simplicio-loop install` is idempotent, says what it changed and what it left alone, has --check, and reads the
bundled data through importlib.resources so it works from a frozen binary (#1575).
"""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from simplicio_loop import cli, cli_impl, host_rules, skill_sync
from simplicio_loop.install.planner import apply_plan, plan_install


def make_bundle(root: Path, skill_text="loop\n") -> Path:
    skill = root / "skills" / "simplicio-loop"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(skill_text, encoding="utf-8")
    (skill / "references").mkdir()
    (skill / "references" / "a.md").write_text("ref a\n", encoding="utf-8")
    (root / "hooks").mkdir()
    (root / "hooks" / "loop_stop.py").write_text("# stop\n", encoding="utf-8")
    (root / "hooks" / "__pycache__").mkdir()
    (root / "hooks" / "__pycache__" / "loop_stop.cpython-314.pyc").write_bytes(b"\0")
    return root


@pytest.fixture
def bundle(tmp_path):
    return make_bundle(tmp_path / "bundle")


@pytest.fixture
def repo(tmp_path):
    target = tmp_path / "repo"
    target.mkdir()
    return target


def apply(repo, bundle, **kw):
    return apply_plan(plan_install(repo, host=kw.pop("host", "claude")), bundle=bundle, **kw)


def test_first_install_creates_everything_and_the_pycache_is_not_shipped(repo, bundle):
    result = apply(repo, bundle)
    changes = result["changes"]
    assert sorted(changes["created"]) == [
        ".claude/skills/simplicio-loop/SKILL.md", ".claude/skills/simplicio-loop/references/a.md",
        ".simplicio-loop/install-ownership.json", "hooks/loop_stop.py"]
    assert changes["updated"] == [] and changes["unchanged"] == 0 and changes["left_alone"] == []
    assert result["written"] == 4 and result["up_to_date"] is False
    assert not list(repo.rglob("__pycache__"))


def test_a_second_install_changes_nothing_and_rewrites_nothing(repo, bundle):
    apply(repo, bundle)
    files = [p for p in repo.rglob("*") if p.is_file()]
    for path in files:
        os.utime(path, ns=(10**9, 10**9))
    result = apply(repo, bundle)
    changes = result["changes"]
    assert changes["created"] == [] and changes["updated"] == [] and changes["unchanged"] == 4
    assert result["written"] == 0 and result["up_to_date"] is True and result["status"] == "applied"
    assert {p.stat().st_mtime_ns for p in files} == {10**9}, "an identical file was rewritten"


def test_a_changed_bundle_file_is_updated_and_a_deleted_one_is_created_again(repo, bundle):
    apply(repo, bundle)
    (bundle / "skills" / "simplicio-loop" / "SKILL.md").write_text("loop v2\n", encoding="utf-8")
    (repo / "hooks" / "loop_stop.py").unlink()
    result = apply(repo, bundle)
    assert result["changes"]["updated"] == [".claude/skills/simplicio-loop/SKILL.md"]
    assert result["changes"]["created"] == ["hooks/loop_stop.py"]
    assert result["changes"]["unchanged"] == 2
    assert (repo / ".claude/skills/simplicio-loop/SKILL.md").read_text(encoding="utf-8") == "loop v2\n"


def test_files_that_loop_does_not_own_are_left_alone_and_reported(repo, bundle):
    other = repo / ".claude" / "skills" / "my-own-skill"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text("mine\n", encoding="utf-8")
    (repo / "hooks").mkdir()
    (repo / "hooks" / "my_hook.py").write_text("# mine\n", encoding="utf-8")
    result = apply(repo, bundle)
    assert sorted(result["changes"]["left_alone"]) == [".claude/skills/my-own-skill", "hooks/my_hook.py"]
    assert (other / "SKILL.md").read_text(encoding="utf-8") == "mine\n"


def test_an_existing_entry_file_is_left_alone_not_overwritten(repo, bundle):
    (repo / "AGENTS.md").write_text("# my own agents file\n", encoding="utf-8")
    result = apply(repo, bundle, host="codex")
    assert "AGENTS.md" in result["changes"]["left_alone"]
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "# my own agents file\n"
    fresh = apply(repo, bundle, host="grok")  # same entry file, already there
    assert "AGENTS.md" in fresh["changes"]["left_alone"]


def test_dry_run_reports_the_same_changes_and_writes_nothing(repo, bundle):
    before = sorted(repo.rglob("*"))
    result = apply(repo, bundle, dry_run=True)
    assert result["status"] == "dry_run" and result["written"] == 0
    assert len(result["changes"]["created"]) == 4
    assert sorted(repo.rglob("*")) == before
    apply(repo, bundle)
    again = apply(repo, bundle, dry_run=True)
    assert again["up_to_date"] is True and again["changes"]["unchanged"] == 4


def test_the_bundle_can_be_a_traversable_that_is_not_a_filesystem_path(tmp_path, repo, bundle):
    """A frozen binary can serve package data from an archive: nothing may need Path.rglob or shutil on the bundle."""
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for path in bundle.rglob("*"):
            if path.is_file():
                handle.write(path, path.relative_to(bundle).as_posix())
    result = apply_plan(plan_install(repo, host="claude"), bundle=zipfile.Path(archive))
    assert len(result["changes"]["created"]) == 4
    assert (repo / ".claude/skills/simplicio-loop/references/a.md").read_text(encoding="utf-8") == "ref a\n"
    assert apply_plan(plan_install(repo, host="claude"), bundle=zipfile.Path(archive))["up_to_date"] is True


def test_the_default_bundle_comes_from_importlib_resources():
    from simplicio_loop import distribution

    assert cli_impl.BUNDLE.joinpath("skills", "simplicio-loop", "SKILL.md").is_file()
    assert str(cli_impl.BUNDLE) == str(distribution.bundle_root())


# --- the command ----------------------------------------------------------------------------------------------------


def run(capsys, *argv):
    rc = cli.main(list(argv))
    return rc, capsys.readouterr().out


def test_install_prints_what_changed_then_says_it_is_up_to_date(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli_impl, "BUNDLE", make_bundle(tmp_path / "b"))
    target = tmp_path / "proj"
    target.mkdir()
    rc, out = run(capsys, "install", "--target", str(target))
    assert rc == 0 and "installed:" in out and "4 created, 0 updated, 0 unchanged" in out
    rc, out = run(capsys, "install", "--target", str(target))
    assert rc == 0 and "already up to date" in out and "0 created, 0 updated, 4 unchanged" in out


def test_install_check_exits_10_while_changes_are_pending_and_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli_impl, "BUNDLE", make_bundle(tmp_path / "b"))
    target = tmp_path / "proj"
    target.mkdir()
    rc, out = run(capsys, "install", "--check", "--target", str(target))
    assert rc == 10 and "4 created" in out and not (target / ".claude").exists()
    run(capsys, "install", "--target", str(target))
    rc, out = run(capsys, "install", "--check", "--target", str(target))
    assert rc == 0 and "up to date" in out


def test_install_dry_run_exits_0_even_with_pending_changes(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli_impl, "BUNDLE", make_bundle(tmp_path / "b"))
    target = tmp_path / "proj"
    target.mkdir()
    rc, out = run(capsys, "install", "--dry-run", "--target", str(target))
    assert rc == 0 and "dry_run" in out and "4 created" in out and not (target / ".claude").exists()


def test_install_json(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli_impl, "BUNDLE", make_bundle(tmp_path / "b"))
    target = tmp_path / "proj"
    target.mkdir()
    rc, out = run(capsys, "install", "--json", "--check", "--target", str(target))
    doc = json.loads(out)
    assert rc == 10 and doc["up_to_date"] is False and len(doc["changes"]["created"]) == 4
    assert doc["host"] == "claude" and doc["status"] == "dry_run"


def test_install_with_the_real_bundle_is_idempotent(tmp_path, capsys):
    target = tmp_path / "proj"
    target.mkdir()
    assert run(capsys, "install", "--target", str(target))[0] == 0
    rc, out = run(capsys, "install", "--check", "--target", str(target))
    assert rc == 0 and "0 created, 0 updated" in out


# --- global install also resyncs the other hosts --------------------------------------------------------------------


def test_global_install_resyncs_skills_and_rules_of_hosts_that_already_have_them(tmp_path, capsys, monkeypatch):
    home = tmp_path / "home"
    (home / ".codex" / "skills" / "simplicio-loop").mkdir(parents=True)
    (home / ".codex" / "skills" / "simplicio-loop" / "SKILL.md").write_text("old release\n", encoding="utf-8")
    rules = home / ".codex" / "rules"
    rules.mkdir(parents=True)
    (rules / host_rules.RULE_NAME).write_text("simplicio-loop-operator-flow OLD\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SIMPLICIO_HOME", str(home))
    rc, out = run(capsys, "install", "--global", "--check")
    assert rc == 10 and not (home / ".claude").exists()
    rc, out = run(capsys, "install", "--global")
    assert rc == 0 and "resynced" in out and "codex" in out
    codex = home / ".codex" / "skills" / "simplicio-loop"
    assert skill_sync.skill_digest(codex) == skill_sync.skill_digest(skill_sync.package_skills_dir() / "simplicio-loop")
    assert (rules / host_rules.RULE_NAME).read_text(encoding="utf-8") != "simplicio-loop-operator-flow OLD\n"
    rc, out = run(capsys, "install", "--global", "--check")
    assert rc == 0
