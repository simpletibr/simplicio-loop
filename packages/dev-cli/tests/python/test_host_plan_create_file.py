"""The contract of a host plan that creates a file (``compile_host_plan`` + ``execute_plan``).

A create is an operation with no anchor: ``find`` is left out (or ``""``) and ``replace`` is the whole new text. The loop
accepts the omitted form (``plan.valid.create.json``), so dev-cli accepts it too. A create never overwrites: any existing
path is refused. Parent directories are made. A plan is all or nothing, and a created file, even an empty one, is receipted.
"""

from __future__ import annotations

import hashlib
import subprocess

import pytest

from simplicio.commands.edit import compile_host_plan
from simplicio.mechanical_edit import execute_plan


def _git_init(repo):
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(repo), check=True)


def _apply(repo, plan):
    """(result, errors): the receipt of applying ``plan`` for real, or the compile refusals when it does not compile."""
    compiled, errors = compile_host_plan(str(repo), plan)
    if compiled is None:
        return None, errors
    return execute_plan(compiled, root=str(repo), apply=True, allow_native=False), []


def test_an_operation_without_find_creates_the_file(tmp_path):
    _git_init(tmp_path)
    result, errors = _apply(tmp_path, {"operations": [{"path": "new_module.py", "replace": "VALUE = 1\n"}]})
    assert errors == [] and result["applied"] is True, result
    assert (tmp_path / "new_module.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_an_operation_without_find_and_one_with_empty_find_compile_to_the_same_create(tmp_path):
    _git_init(tmp_path)
    omitted, _ = compile_host_plan(str(tmp_path), {"operations": [{"path": "a.py", "replace": "X = 1\n"}]})
    explicit, _ = compile_host_plan(
        str(tmp_path), {"operations": [{"path": "a.py", "find": "", "replace": "X = 1\n"}]}
    )
    assert (
        omitted["operations"]
        == explicit["operations"]
        == [{"op": "create_file", "path": "a.py", "text": "X = 1\n"}]
    )


@pytest.mark.parametrize("find", [None, 3, ["x"]])
def test_a_find_that_is_not_a_string_is_refused_and_says_a_create_leaves_it_out(tmp_path, find):
    _git_init(tmp_path)
    compiled, errors = compile_host_plan(
        str(tmp_path), {"operations": [{"path": "new.py", "find": find, "replace": "x\n"}]}
    )
    assert compiled is None
    assert errors[0]["code"] == "invalid_operation" and errors[0]["index"] == 0
    assert "absent" in errors[0]["message"] and "find" in errors[0]["message"], errors[0]["message"]
    assert not (tmp_path / "new.py").exists()


def test_an_operation_without_find_refuses_an_existing_file_as_a_create_does(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "existing.py").write_text("already here\n", encoding="utf-8")
    compiled, errors = compile_host_plan(
        str(tmp_path), {"operations": [{"path": "existing.py", "replace": "over\n"}]}
    )
    assert compiled is None and errors[0]["code"] == "create_target_exists"
    assert (tmp_path / "existing.py").read_text(encoding="utf-8") == "already here\n"


def test_an_empty_new_file_is_created_and_receipted(tmp_path):
    _git_init(tmp_path)
    result, errors = _apply(
        tmp_path, {"operations": [{"path": "pkg/__init__.py", "find": "", "replace": ""}]}
    )
    assert errors == []
    assert result["noop"] is False and result["applied"] is True, result
    assert (tmp_path / "pkg" / "__init__.py").read_bytes() == b""
    assert result["files"] == [
        {"path": "pkg/__init__.py", "before_sha256": None, "after_sha256": hashlib.sha256(b"").hexdigest()}
    ]


def test_an_existing_empty_file_is_refused_before_anything_is_written(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "marker.py").write_bytes(b"")
    compiled, errors = compile_host_plan(
        str(tmp_path), {"operations": [{"path": "marker.py", "find": "", "replace": "x = 1\n"}]}
    )
    assert compiled is None and errors[0]["code"] == "create_target_exists"
    assert (tmp_path / "marker.py").read_bytes() == b""


def test_a_create_under_an_existing_file_is_refused_cleanly(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "blocker").write_text("a file, not a directory\n", encoding="utf-8")
    compiled, errors = compile_host_plan(
        str(tmp_path), {"operations": [{"path": "blocker/new.py", "replace": "x\n"}]}
    )
    assert compiled is None and errors[0]["code"] == "create_parent_not_directory"
    assert (tmp_path / "blocker").read_text(encoding="utf-8") == "a file, not a directory\n"


@pytest.mark.parametrize("path", ["../escape.py", "/tmp/escape.py", ".git/hooks/post-checkout"])
def test_a_create_outside_the_repository_is_refused(tmp_path, path):
    _git_init(tmp_path)
    compiled, errors = compile_host_plan(str(tmp_path), {"operations": [{"path": path, "replace": "x\n"}]})
    assert compiled is None and errors[0]["code"] == "unsafe_path", errors


def test_parent_directories_of_a_create_are_made(tmp_path):
    _git_init(tmp_path)
    result, errors = _apply(
        tmp_path, {"operations": [{"path": "pkg/sub/deeper/new_mod.py", "replace": "V = 2\n"}]}
    )
    assert errors == [] and result["applied"] is True, result
    assert (tmp_path / "pkg" / "sub" / "deeper" / "new_mod.py").read_text(encoding="utf-8") == "V = 2\n"


def test_a_missing_anchor_refuses_the_creates_of_the_same_plan_too(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "existing.py").write_text("BEFORE\n", encoding="utf-8")
    plan = {
        "operations": [
            {"path": "brand_new.py", "replace": "NEW = True\n"},
            {"path": "existing.py", "find": "NOT THERE\n", "replace": "AFTER\n"},
        ]
    }
    compiled, errors = compile_host_plan(str(tmp_path), plan)
    assert compiled is None and [error["code"] for error in errors] == ["missing_anchor"]
    assert not (tmp_path / "brand_new.py").exists()
    assert (tmp_path / "existing.py").read_text(encoding="utf-8") == "BEFORE\n"


def test_two_creates_of_one_path_in_one_plan_refuse_the_whole_plan(tmp_path):
    _git_init(tmp_path)
    plan = {"operations": [{"path": "dup.py", "replace": "A = 1\n"}, {"path": "dup.py", "replace": "B = 2\n"}]}
    result, errors = _apply(tmp_path, plan)
    assert errors == [] and result["status"] == "refused" and result["applied"] is False, result
    assert not (tmp_path / "dup.py").exists()


def test_a_create_and_an_edit_in_one_plan_are_one_receipt(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "existing.py").write_text("BEFORE\n", encoding="utf-8")
    plan = {
        "operations": [
            {"path": "pkg/new_mod.py", "replace": "NEW = True\n"},
            {"path": "existing.py", "find": "BEFORE\n", "replace": "AFTER\n"},
        ]
    }
    result, errors = _apply(tmp_path, plan)
    assert errors == [] and result["applied"] is True, result
    assert sorted(row["path"] for row in result["files"]) == ["existing.py", "pkg/new_mod.py"]
    created = next(row for row in result["files"] if row["path"] == "pkg/new_mod.py")
    assert (
        created["before_sha256"] is None
        and created["after_sha256"] == hashlib.sha256(b"NEW = True\n").hexdigest()
    )
