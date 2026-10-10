"""Uninstall never deletes outside the target, whatever the ownership receipt says (audit of #1617)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop.install.planner import OWNERSHIP_SCHEMA, InstallError, uninstall


def write_receipt(root: Path, **fields) -> None:
    marker = root / ".simplicio-loop" / "install-ownership.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    receipt = {"schema": OWNERSHIP_SCHEMA, "owner": "simplicio-loop", **fields}
    marker.write_text(json.dumps(receipt), encoding="utf-8")


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    folder = tmp_path / "outside"
    folder.mkdir()
    (folder / "keep.txt").write_text("mine", encoding="utf-8")
    return folder


@pytest.fixture
def target(tmp_path: Path) -> Path:
    folder = tmp_path / "target"
    folder.mkdir()
    return folder


def test_path_through_directory_symlink_is_refused(target, outside):
    (target / "link").symlink_to(outside, target_is_directory=True)
    write_receipt(target, paths=["link/keep.txt"], dirs=[])
    with pytest.raises(InstallError, match="through a symlink"):
        uninstall(target)
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "mine"


def test_dir_replaced_by_symlink_is_refused_before_deleting_anything(target, outside):
    (target / "a.txt").write_text("loop", encoding="utf-8")
    (target / "d").symlink_to(outside, target_is_directory=True)
    write_receipt(target, paths=["a.txt", "d/keep.txt"], dirs=["d"])
    with pytest.raises(InstallError, match="through a symlink"):
        uninstall(target)
    assert (target / "a.txt").is_file()
    assert (outside / "keep.txt").is_file()


@pytest.mark.parametrize(
    "fields",
    [
        {"paths": [1], "dirs": []},
        {"paths": [], "dirs": [None]},
        {"paths": "abc", "dirs": []},
        {"paths": None, "dirs": []},
        {"paths": [], "dirs": "abc"},
        {"paths": ["../outside/keep.txt"], "dirs": []},
        {"paths": ["/etc/hostname"], "dirs": []},
        {"paths": [""], "dirs": []},
    ],
)
def test_untrustworthy_receipt_is_refused_and_touches_nothing(target, outside, fields):
    (target / "a.txt").write_text("loop", encoding="utf-8")
    write_receipt(target, **fields)
    with pytest.raises(InstallError, match="malformed|escapes the target:"):
        uninstall(target)
    assert (target / "a.txt").is_file()
    assert (outside / "keep.txt").is_file()


@pytest.mark.parametrize("key", ["paths", "dirs"])
@pytest.mark.parametrize("kind", ["dotdot", "nested-dotdot", "absolute", "dot"])
def test_a_path_that_is_not_below_the_target_is_refused_by_name(target, outside, key, kind):
    rel = {
        "dotdot": "../outside/keep.txt",
        "nested-dotdot": "a/../../outside/keep.txt",
        "absolute": str(outside / "keep.txt"),
        "dot": ".",
    }[kind]
    (target / "a.txt").write_text("loop", encoding="utf-8")
    fields = {"paths": ["a.txt"], "dirs": []}
    fields[key].append(rel)
    write_receipt(target, **fields)
    with pytest.raises(InstallError, match="escapes the target:"):
        uninstall(target)
    assert (target / "a.txt").is_file()
    assert (outside / "keep.txt").is_file()


def test_a_registered_file_that_is_a_symlink_loses_only_the_link(target, outside):
    (target / "ln.txt").symlink_to(outside / "keep.txt")
    write_receipt(target, paths=["ln.txt"], dirs=[])
    result = uninstall(target)
    assert "ln.txt" in result["removed"]
    assert not (target / "ln.txt").is_symlink()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "mine"


def test_a_link_to_a_sibling_whose_name_starts_with_the_targets_is_outside(tmp_path, target):
    evil = tmp_path / "target-evil"
    evil.mkdir()
    (evil / "keep.txt").write_text("mine", encoding="utf-8")
    (target / "link").symlink_to(evil, target_is_directory=True)
    write_receipt(target, paths=["link/keep.txt"], dirs=[])
    with pytest.raises(InstallError, match="through a symlink"):
        uninstall(target)
    assert (evil / "keep.txt").is_file()


def test_a_target_reached_through_a_symlink_is_still_uninstalled(tmp_path, target):
    (target / "a.txt").write_text("loop", encoding="utf-8")
    write_receipt(target, paths=["a.txt"], dirs=[])
    via = tmp_path / "via"
    via.symlink_to(target, target_is_directory=True)
    result = uninstall(via)
    assert "a.txt" in result["removed"]
    assert not (target / "a.txt").exists()


def test_a_registered_directory_that_is_gone_is_ignored(target):
    (target / "a.txt").write_text("loop", encoding="utf-8")
    write_receipt(target, paths=["a.txt"], dirs=["gone"])
    result = uninstall(target)
    assert result["removed_dirs"] == [] and result["kept"] == []
    assert not (target / "a.txt").exists()


def test_a_registered_directory_with_a_foreign_file_is_reported_as_kept(target):
    (target / "d").mkdir()
    (target / "d" / "loop.txt").write_text("loop", encoding="utf-8")
    (target / "d" / "mine.txt").write_text("mine", encoding="utf-8")
    write_receipt(target, paths=["d/loop.txt"], dirs=["d"])
    result = uninstall(target)
    assert result["kept"] == ["d"] and result["removed_dirs"] == []
    assert (target / "d" / "mine.txt").is_file() and not (target / "d" / "loop.txt").exists()


def test_install_doc_says_global_resync_files_stay():
    text = (Path(__file__).resolve().parents[2] / "INSTALL.md").read_text(encoding="utf-8")
    assert "~/.codex/skills/simplicio-*" in text and "stay after" in text
