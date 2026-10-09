"""`uninstall` removes exactly what `install` registered: its files, and the directories install created that are empty
afterwards. A user's skill, rule or hook next to Loop's, and any directory the user already had, always survive.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop import cli, cli_impl
from simplicio_loop.install.planner import (
    InstallError,
    apply_plan,
    plan_install,
    uninstall,
)


def make_bundle(root: Path) -> Path:
    skill = root / "skills" / "simplicio-loop"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("loop\n", encoding="utf-8")
    (skill / "references").mkdir()
    (skill / "references" / "a.md").write_text("ref a\n", encoding="utf-8")
    (root / "hooks").mkdir()
    (root / "hooks" / "loop_stop.py").write_text("# stop\n", encoding="utf-8")
    return root


def write(path: Path, text: str = "user\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def bundle(tmp_path):
    return make_bundle(tmp_path / "bundle")


@pytest.fixture
def repo(tmp_path):
    target = tmp_path / "repo"
    target.mkdir()
    return target


def install(
    root: Path, bundle: Path, *, host: str = "claude", globally: bool = False
) -> dict:
    return apply_plan(plan_install(root, host=host, globally=globally), bundle=bundle)


def test_user_skill_next_to_loop_skills_survives_uninstall(repo, bundle):
    user_skill = write(
        repo / ".claude" / "skills" / "minha-skill" / "SKILL.md", "mine\n"
    )
    install(repo, bundle)
    uninstall(repo)
    assert user_skill.read_text(encoding="utf-8") == "mine\n"
    assert not (repo / ".claude" / "skills" / "simplicio-loop").exists()


def test_user_skill_added_after_install_survives_uninstall(repo, bundle):
    install(repo, bundle)
    user_skill = write(
        repo / ".claude" / "skills" / "minha-skill" / "SKILL.md", "mine\n"
    )
    uninstall(repo)
    assert user_skill.is_file()
    assert (repo / ".claude" / "skills").is_dir()


def test_directories_install_created_are_removed_when_empty(repo, bundle):
    install(repo, bundle)
    uninstall(repo)
    assert sorted(repo.rglob("*")) == [], (
        "uninstall must return a fresh target to its baseline"
    )


def test_project_hooks_dir_with_a_user_file_survives(repo, bundle):
    user_hook = write(repo / "hooks" / "my_hook.py", "# mine\n")
    install(repo, bundle)
    uninstall(repo)
    assert user_hook.read_text(encoding="utf-8") == "# mine\n"
    assert not (repo / "hooks" / "loop_stop.py").exists()


def test_pre_existing_entry_file_is_never_removed(repo, bundle):
    agents = write(repo / "AGENTS.md", "# my own agents file\n")
    install(repo, bundle, host="codex")
    uninstall(repo)
    assert agents.read_text(encoding="utf-8") == "# my own agents file\n"


def test_entry_file_written_by_install_is_removed(repo, bundle):
    install(repo, bundle, host="codex")
    assert (repo / "AGENTS.md").is_file()
    uninstall(repo)
    assert not (repo / "AGENTS.md").exists()


@pytest.mark.parametrize("host", ["cursor", "codex", "kiro", "vscode", "grok"])
def test_host_directories_keep_their_user_files(repo, bundle, host):
    user_files = [
        write(repo / ".cursor" / "rules" / "mine.mdc", "cursor mine\n"),
        write(repo / ".codex" / "config.toml", "codex mine\n"),
        write(repo / ".kiro" / "steering" / "mine.md", "kiro mine\n"),
        write(repo / ".github" / "workflows" / "ci.yml", "ci mine\n"),
    ]
    install(repo, bundle, host=host)
    uninstall(repo)
    for path in user_files:
        assert path.is_file(), f"uninstall --host {host} removed a user file: {path}"
    assert not (repo / ".claude" / "skills" / "simplicio-loop").exists()


def test_global_scope_keeps_user_skills_rules_and_codex_files(tmp_path, bundle):
    home = tmp_path / "home"
    home.mkdir()
    user_skill = write(
        home / ".claude" / "skills" / "minha-skill" / "SKILL.md", "mine\n"
    )
    user_rule = write(home / ".claude" / "rules" / "mine.md", "rule mine\n")
    codex_skill = write(
        home / ".codex" / "skills" / "my-codex-skill" / "SKILL.md", "codex mine\n"
    )
    install(home, bundle, globally=True)
    uninstall(home)
    assert user_skill.is_file() and user_rule.is_file() and codex_skill.is_file()
    assert not (home / ".claude" / "skills" / "simplicio-loop").exists()
    assert not (home / ".claude" / "hooks").exists()


def test_dry_run_removes_nothing_and_lists_what_would_go(repo, bundle):
    user_skill = write(
        repo / ".claude" / "skills" / "minha-skill" / "SKILL.md", "mine\n"
    )
    install(repo, bundle)
    before = sorted(repo.rglob("*"))
    result = uninstall(repo, dry_run=True)
    assert result["status"] == "dry_run"
    assert ".claude/skills/simplicio-loop/SKILL.md" in result["removed"]
    assert ".simplicio-loop/install-ownership.json" in result["removed"]
    assert sorted(repo.rglob("*")) == before, "a dry run must not touch the disk"
    assert user_skill.is_file()
    assert uninstall(repo)["status"] == "removed"


def test_an_obsolete_receipt_schema_fails_closed(repo, bundle):
    user_skill = write(
        repo / ".claude" / "skills" / "minha-skill" / "SKILL.md", "mine\n"
    )
    marker = repo / ".simplicio-loop" / "install-ownership.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "schema": "simplicio.loop-install-ownership/v1",
                "owner": "simplicio-loop",
                "version": "0",
                "digest": "sha256:0",
                "paths": [".claude/skills"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(InstallError, match="obsolete"):
        uninstall(repo)
    assert user_skill.is_file()


def test_two_hosts_installed_in_sequence_are_both_uninstalled(repo, bundle):
    install(repo, bundle, host="claude")
    install(repo, bundle, host="codex")
    uninstall(repo)
    assert sorted(repo.rglob("*")) == []


# --- the command --------------------------------------------------------------------------------------------------


def run(capsys, *argv):
    rc = cli.main(list(argv))
    return rc, capsys.readouterr().out


def test_cli_uninstall_dry_run_exits_0_and_removes_nothing(
    tmp_path, capsys, monkeypatch, bundle
):
    monkeypatch.setattr(cli_impl, "BUNDLE", bundle)
    target = tmp_path / "proj"
    target.mkdir()
    user_skill = write(
        target / ".claude" / "skills" / "minha-skill" / "SKILL.md", "mine\n"
    )
    run(capsys, "install", "--target", str(target))
    before = sorted(target.rglob("*"))
    rc, out = run(
        capsys, "install", "--uninstall", "--dry-run", "--target", str(target)
    )
    assert rc == 0 and "dry_run" in out and "simplicio-loop/SKILL.md" in out
    assert sorted(target.rglob("*")) == before and user_skill.is_file()
    rc, out = run(capsys, "install", "--uninstall", "--target", str(target))
    assert rc == 0 and user_skill.is_file()
    assert not (target / ".claude" / "skills" / "simplicio-loop").exists()
