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
