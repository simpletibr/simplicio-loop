import json
from pathlib import Path

import pytest

from simplicio_loop.install.planner import (
    InstallError,
    apply_plan,
    plan_install,
    uninstall,
    verify_plan,
)


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    skill = bundle / "skills" / "simplicio-loop"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("loop\n", encoding="utf-8")
    hooks = bundle / "hooks"
    hooks.mkdir()
    (hooks / "loop_stop.py").write_text("# stop\n", encoding="utf-8")
    return bundle


def test_dry_run_does_not_write(tmp_path: Path):
    target = tmp_path / "repo"
    target.mkdir()
    plan = plan_install(target, host="claude")
    result = apply_plan(plan, dry_run=True, bundle=_bundle(tmp_path))
    assert result["status"] == "dry_run"
    assert result["written"] == 0
    assert not (target / ".claude").exists()
    assert not (target / ".simplicio-loop" / "install-ownership.json").exists()


def test_apply_is_idempotent_and_owned(tmp_path: Path):
    target = tmp_path / "repo"
    target.mkdir()
    bundle = _bundle(tmp_path)
    plan = plan_install(target, host="claude")
    first = apply_plan(plan, bundle=bundle)
    second = apply_plan(plan, bundle=bundle)
    assert first["status"] == second["status"] == "applied"
    assert (target / ".claude" / "skills" / "simplicio-loop" / "SKILL.md").is_file()
    assert (target / ".simplicio-loop" / "install-ownership.json").is_file()


def test_uninstall_removes_only_loop_ownership(tmp_path: Path):
    target = tmp_path / "repo"
    target.mkdir()
    (target / "keep.txt").write_text("user\n", encoding="utf-8")
    apply_plan(plan_install(target, host="claude"), bundle=_bundle(tmp_path))
    removed = uninstall(target)
    assert removed["status"] == "removed"
    assert (target / "keep.txt").is_file()
    assert not (target / ".simplicio-loop" / "install-ownership.json").exists()
    with pytest.raises(InstallError, match="ownership"):
        uninstall(target)


def test_version_mismatch_blocks(tmp_path: Path):
    plan = plan_install(tmp_path, host="vscode", version="0.0.1")
    with pytest.raises(InstallError, match="version mismatch"):
        verify_plan(plan)


def test_unknown_host_fails_closed(tmp_path: Path):
    with pytest.raises(InstallError, match="unknown host"):
        plan_install(tmp_path, host="not-a-host")


# --- lean default: only the simplicio-loop skill (the listing of every installed skill is shown to the model each turn) ------

SKILLS = ("simplicio-autoresearch", "simplicio-compress", "simplicio-dev-cli", "simplicio-learn", "simplicio-loop",
          "simplicio-mapper", "simplicio-orient", "simplicio-prism", "simplicio-review", "simplicio-tasks")


def _full_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    for name in SKILLS:
        (bundle / "skills" / name / "references").mkdir(parents=True)
        (bundle / "skills" / name / "SKILL.md").write_text(f"{name}\n", encoding="utf-8")
        (bundle / "skills" / name / "references" / "more.md").write_text("ref\n", encoding="utf-8")
    (bundle / "hooks").mkdir()
    (bundle / "hooks" / "loop_stop.py").write_text("# stop\n", encoding="utf-8")
    return bundle


def _installed(root: Path) -> list[str]:
    return sorted(p.name for p in (root / ".claude" / "skills").iterdir())


def test_the_default_install_puts_only_the_simplicio_loop_skill_and_the_hooks_in_place(tmp_path: Path):
    target = tmp_path / "repo"
    target.mkdir()
    result = apply_plan(plan_install(target, host="claude"), bundle=_full_bundle(tmp_path))
    assert _installed(target) == ["simplicio-loop"]
    assert (target / ".claude" / "skills" / "simplicio-loop" / "references" / "more.md").is_file()  # the whole skill folder
    assert (target / "hooks" / "loop_stop.py").is_file()
    assert result["owned"] == [".claude/skills/simplicio-loop", "hooks"]
    assert result["ownership"]["paths"] == [".claude/skills/simplicio-loop", "hooks"]


def test_all_skills_installs_every_bundled_skill(tmp_path: Path):
    target = tmp_path / "repo"
    target.mkdir()
    result = apply_plan(plan_install(target, host="claude", all_skills=True), bundle=_full_bundle(tmp_path))
    assert _installed(target) == sorted(SKILLS)
    assert ".claude/skills/simplicio-orient" in result["owned"]


def test_the_skill_selection_is_part_of_the_plan_digest(tmp_path: Path):
    assert plan_install(tmp_path, host="claude")["digest"] != plan_install(tmp_path, host="claude", all_skills=True)["digest"]


def test_a_bundle_without_the_simplicio_loop_skill_is_an_error(tmp_path: Path):
    bundle = tmp_path / "bundle"
    (bundle / "skills" / "simplicio-orient").mkdir(parents=True)
    with pytest.raises(InstallError, match="simplicio-loop"):
        apply_plan(plan_install(tmp_path / "repo", host="claude"), bundle=bundle)


def _legacy_install(target: Path, bundle: Path) -> None:
    """What the installer before this change left behind: every skill, and a receipt that owns the whole skills folder."""
    apply_plan(plan_install(target, host="claude", all_skills=True), bundle=bundle)
    marker = target / ".simplicio-loop" / "install-ownership.json"
    receipt = json.loads(marker.read_text(encoding="utf-8"))
    receipt["paths"] = [".claude/skills", "hooks"]
    marker.write_text(json.dumps(receipt), encoding="utf-8")


def test_an_upgrade_removes_the_skills_an_earlier_install_wrote_but_never_the_users_own(tmp_path: Path):
    target = tmp_path / "repo"
    target.mkdir()
    bundle = _full_bundle(tmp_path)
    _legacy_install(target, bundle)
    (target / ".claude" / "skills" / "my-own").mkdir()
    (target / ".claude" / "skills" / "my-own" / "SKILL.md").write_text("mine\n", encoding="utf-8")
    result = apply_plan(plan_install(target, host="claude"), bundle=bundle)  # the user did not opt in to the others
    assert _installed(target) == ["my-own", "simplicio-loop"]
    assert sorted(result["removed"]) == sorted(f".claude/skills/{n}" for n in SKILLS if n != "simplicio-loop")
    assert (target / ".claude" / "skills" / "my-own" / "SKILL.md").read_text(encoding="utf-8") == "mine\n"


def test_an_upgrade_that_opts_in_keeps_every_skill(tmp_path: Path):
    target = tmp_path / "repo"
    target.mkdir()
    bundle = _full_bundle(tmp_path)
    _legacy_install(target, bundle)
    result = apply_plan(plan_install(target, host="claude", all_skills=True), bundle=bundle)
    assert _installed(target) == sorted(SKILLS) and result["removed"] == []


def test_dropping_the_opt_in_removes_the_skills_this_installer_added_by_name(tmp_path: Path):
    target = tmp_path / "repo"
    target.mkdir()
    bundle = _full_bundle(tmp_path)
    apply_plan(plan_install(target, host="claude", all_skills=True), bundle=bundle)  # a receipt that names each skill
    apply_plan(plan_install(target, host="claude"), bundle=bundle)
    assert _installed(target) == ["simplicio-loop"]


def test_without_an_ownership_receipt_nothing_is_removed(tmp_path: Path):
    target = tmp_path / "repo"
    (target / ".claude" / "skills" / "simplicio-orient").mkdir(parents=True)
    (target / ".claude" / "skills" / "simplicio-orient" / "SKILL.md").write_text("not ours to remove\n", encoding="utf-8")
    result = apply_plan(plan_install(target, host="claude"), bundle=_full_bundle(tmp_path))
    assert _installed(target) == ["simplicio-loop", "simplicio-orient"] and result["removed"] == []


def test_a_dry_run_removes_nothing(tmp_path: Path):
    target = tmp_path / "repo"
    target.mkdir()
    bundle = _full_bundle(tmp_path)
    _legacy_install(target, bundle)
    result = apply_plan(plan_install(target, host="claude"), dry_run=True, bundle=bundle)
    assert _installed(target) == sorted(SKILLS) and result["removed"] == []


def test_uninstall_removes_only_the_skills_this_installer_wrote(tmp_path: Path):
    target = tmp_path / "repo"
    target.mkdir()
    apply_plan(plan_install(target, host="claude"), bundle=_full_bundle(tmp_path))
    (target / ".claude" / "skills" / "my-own").mkdir()
    (target / ".claude" / "skills" / "my-own" / "SKILL.md").write_text("mine\n", encoding="utf-8")
    removed = uninstall(target)
    assert _installed(target) == ["my-own"] and ".claude/skills/simplicio-loop" in removed["removed"]


def test_the_real_bundle_default_is_one_skill_and_all_skills_is_the_whole_bundle(tmp_path: Path):
    from simplicio_loop.install.__main__ import main

    lean, full = tmp_path / "lean", tmp_path / "full"
    assert main(["--target", str(lean)]) == 0 and main(["--target", str(full), "--all-skills"]) == 0
    assert _installed(lean) == ["simplicio-loop"]
    assert len(_installed(full)) == 10 and "simplicio-loop" in _installed(full)
