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


# --- audit follow-up: what the receipt may name, and which directories are Loop's ---------------------------------


def loop_skill(root: Path) -> Path:
    return root / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"


def tamper(root: Path, **changes) -> None:
    marker = root / ".simplicio-loop" / "install-ownership.json"
    receipt = json.loads(marker.read_text(encoding="utf-8"))
    receipt.update(changes)
    marker.write_text(json.dumps(receipt), encoding="utf-8")


def receipt_of(root: Path) -> dict:
    return json.loads(
        (root / ".simplicio-loop" / "install-ownership.json").read_text(encoding="utf-8")
    )


def test_directories_that_existed_before_install_are_not_removed(repo, bundle):
    (repo / ".claude" / "skills").mkdir(parents=True)
    (repo / "hooks").mkdir()
    install(repo, bundle)
    uninstall(repo)
    assert (repo / ".claude" / "skills").is_dir() and (repo / "hooks").is_dir()
    assert not loop_skill(repo).exists()


@pytest.mark.parametrize("key", ["paths", "dirs"])
@pytest.mark.parametrize("kind", ["absolute", "dotdot", "nested-dotdot"])
def test_a_receipt_path_outside_the_target_is_refused_before_anything_is_removed(
    tmp_path, repo, bundle, key, kind
):
    outside = tmp_path / "outside.txt"
    outside.write_text("keep\n", encoding="utf-8")
    install(repo, bundle)
    bad = {
        "absolute": str(outside),
        "dotdot": "../outside.txt",
        "nested-dotdot": ".claude/../../outside.txt",
    }[kind]
    tamper(repo, **{key: receipt_of(repo)[key] + [bad]})
    with pytest.raises(InstallError, match="escapes"):
        uninstall(repo)
    assert outside.is_file() and loop_skill(repo).is_file()


def test_a_receipt_not_owned_by_loop_is_refused(repo, bundle):
    install(repo, bundle)
    tamper(repo, owner="someone-else")
    with pytest.raises(InstallError, match="not Loop-owned"):
        uninstall(repo)
    assert loop_skill(repo).is_file()


@pytest.mark.parametrize("body", ["{not json", "", "[1, 2]", "null"])
def test_a_corrupt_receipt_is_refused_and_nothing_is_removed(repo, bundle, body):
    user_skill = write(
        repo / ".claude" / "skills" / "minha-skill" / "SKILL.md", "mine\n"
    )
    install(repo, bundle)
    (repo / ".simplicio-loop" / "install-ownership.json").write_text(
        body, encoding="utf-8"
    )
    with pytest.raises(InstallError):
        uninstall(repo)
    assert user_skill.is_file() and loop_skill(repo).is_file()


def test_a_missing_receipt_removes_nothing(repo, bundle):
    install(repo, bundle)
    (repo / ".simplicio-loop" / "install-ownership.json").unlink()
    with pytest.raises(InstallError, match="no Loop ownership receipt"):
        uninstall(repo)
    assert loop_skill(repo).is_file()


def test_a_registered_directory_is_never_removed_as_if_it_were_a_file(repo, bundle):
    user_skill = write(
        repo / ".claude" / "skills" / "minha-skill" / "SKILL.md", "mine\n"
    )
    install(repo, bundle)
    tamper(
        repo, paths=receipt_of(repo)["paths"] + [".claude/skills/minha-skill"]
    )
    result = uninstall(repo)
    assert user_skill.is_file()
    assert ".claude/skills/minha-skill" in result["skipped"]


def test_a_glob_in_the_receipt_is_a_literal_name_not_a_pattern(repo, bundle):
    user_skill = write(
        repo / ".claude" / "skills" / "minha-skill" / "SKILL.md", "mine\n"
    )
    install(repo, bundle)
    tamper(repo, paths=[".claude/skills/*", ".claude/skills/**/*.md"])
    uninstall(repo)
    assert user_skill.is_file() and loop_skill(repo).is_file()


@pytest.mark.parametrize(
    "changes",
    [{"paths": [1]}, {"paths": "abc"}, {"paths": None}, {"dirs": [None]}, {"dirs": "x"}],
)
def test_a_receipt_with_the_wrong_field_types_is_refused(repo, bundle, changes):
    install(repo, bundle)
    tamper(repo, **changes)
    with pytest.raises(InstallError, match="malformed"):
        uninstall(repo)
    assert loop_skill(repo).is_file()


def test_a_symlink_in_a_registered_path_never_reaches_outside_the_target(
    tmp_path, repo, bundle
):
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = write(outside / "x.txt", "keep\n")
    install(repo, bundle)
    (repo / "docs").symlink_to(outside, target_is_directory=True)
    tamper(repo, paths=receipt_of(repo)["paths"] + ["docs/x.txt"])
    with pytest.raises(InstallError, match="escapes"):
        uninstall(repo)
    assert victim.is_file() and loop_skill(repo).is_file()


def test_a_registered_directory_replaced_by_a_symlink_is_refused_not_a_crash(
    tmp_path, repo, bundle
):
    install(repo, bundle)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / "hooks" / "loop_stop.py").unlink()
    (repo / "hooks").rmdir()
    (repo / "hooks").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(InstallError, match="escapes"):
        uninstall(repo)
    assert (repo / "hooks").is_symlink() and loop_skill(repo).is_file()


def test_a_registered_directory_that_is_a_symlink_is_left_alone(tmp_path, repo, bundle):
    install(repo, bundle)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / "mylink").symlink_to(elsewhere, target_is_directory=True)
    tamper(repo, dirs=receipt_of(repo)["dirs"] + ["mylink"])
    result = uninstall(repo)
    assert "mylink" not in result["removed_dirs"]
    assert (repo / "mylink").is_symlink() and elsewhere.is_dir()


# --- item 5 (#1635): the global scope's resync files are outside the receipt, and the command says so ---------------


def test_global_uninstall_says_which_resynced_files_stay(tmp_path, capsys, monkeypatch, bundle):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(cli_impl, "BUNDLE", bundle)
    run(capsys, "install", "--global")
    rc, out = run(capsys, "install", "--uninstall", "--global")
    assert rc == 0
    assert "outside the ownership receipt" in out and "simplicio-*" in out

    target = tmp_path / "proj"
    target.mkdir()
    run(capsys, "install", "--target", str(target))
    rc, out = run(capsys, "install", "--uninstall", "--target", str(target))
    assert rc == 0 and "outside the ownership receipt" not in out


# --- 22 tampered receipts (#1635): nothing outside the target is ever deleted -------------------------------------


def snapshot(folder: Path) -> dict:
    return {
        path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8") if path.is_file() else None
        for path in folder.rglob("*")
    }


def _add(root: Path, key: str, *items) -> None:
    tamper(root, **{key: receipt_of(root)[key] + list(items)})


def _link(root: Path, name: str, target: Path) -> None:
    (root / name).symlink_to(target, target_is_directory=target.is_dir())


def _through_dir_symlink(root, outside):
    _link(root, "docs", outside)
    _add(root, "paths", "docs/keep.txt")


def _leaf_symlink_to_file(root, outside):
    _link(root, "ln.txt", outside / "keep.txt")
    _add(root, "paths", "ln.txt")


def _symlink_to_dir_listed_as_file(root, outside):
    _link(root, "link", outside)
    _add(root, "paths", "link")


def _symlink_to_dir_listed_as_dir(root, outside):
    _link(root, "link", outside)
    _add(root, "dirs", "link")


def _hooks_replaced_by_symlink(root, outside):
    (root / "hooks" / "loop_stop.py").unlink()
    (root / "hooks").rmdir()
    _link(root, "hooks", outside)


def _replace(root, **changes):
    tamper(root, **changes)


TAMPERS = [
    pytest.param(lambda r, o: _add(r, "paths", str(o / "keep.txt")), True, id="paths-absolute-file"),
    pytest.param(lambda r, o: _add(r, "paths", "../outside/keep.txt"), True, id="paths-dotdot"),
    pytest.param(lambda r, o: _add(r, "paths", ".claude/../../outside/keep.txt"), True, id="paths-nested-dotdot"),
    pytest.param(lambda r, o: _add(r, "paths", "../*"), True, id="paths-dotdot-glob"),
    pytest.param(lambda r, o: _add(r, "paths", "."), True, id="paths-dot"),
    pytest.param(lambda r, o: _add(r, "paths", ""), True, id="paths-empty"),
    pytest.param(lambda r, o: _add(r, "paths", "/"), True, id="paths-root"),
    pytest.param(_through_dir_symlink, True, id="paths-through-dir-symlink"),
    pytest.param(_leaf_symlink_to_file, False, id="paths-leaf-symlink-to-file"),
    pytest.param(_symlink_to_dir_listed_as_file, False, id="paths-symlink-to-dir-listed-as-file"),
    pytest.param(lambda r, o: _add(r, "paths", "*"), False, id="paths-glob-is-literal"),
    pytest.param(lambda r, o: _replace(r, paths=[1]), True, id="paths-int-item"),
    pytest.param(lambda r, o: _replace(r, paths="abc"), True, id="paths-string"),
    pytest.param(lambda r, o: _replace(r, paths=None), True, id="paths-null"),
    pytest.param(lambda r, o: _add(r, "dirs", str(o)), True, id="dirs-absolute-outside"),
    pytest.param(lambda r, o: _add(r, "dirs", "../outside"), True, id="dirs-dotdot"),
    pytest.param(lambda r, o: _add(r, "dirs", "."), True, id="dirs-dot"),
    pytest.param(_symlink_to_dir_listed_as_dir, False, id="dirs-symlink-to-outside-dir"),
    pytest.param(_hooks_replaced_by_symlink, True, id="dirs-replaced-by-symlink"),
    pytest.param(lambda r, o: _replace(r, dirs=[None]), True, id="dirs-int-item"),
    pytest.param(lambda r, o: _replace(r, dirs="x"), True, id="dirs-string"),
    pytest.param(lambda r, o: _replace(r, owner="someone-else"), True, id="owner-tampered"),
]


@pytest.mark.parametrize("tamper_case, refused", TAMPERS)
def test_no_tampered_receipt_deletes_anything_outside_the_target(
    tmp_path, repo, bundle, tamper_case, refused
):
    outside = tmp_path / "outside"
    write(outside / "keep.txt", "keep\n")
    write(outside / "sub" / "keep2.txt", "keep2\n")
    install(repo, bundle)
    before = snapshot(outside)
    tamper_case(repo, outside)
    if refused:
        with pytest.raises(InstallError):
            uninstall(repo)
        assert loop_skill(repo).is_file()
    else:
        uninstall(repo)
    assert snapshot(outside) == before
