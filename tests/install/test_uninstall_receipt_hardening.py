"""Uninstall never deletes outside the target, whatever the ownership receipt says (audit of #1617)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio_loop.install.planner import InstallError, uninstall


def write_receipt(root: Path, **fields) -> None:
    marker = root / ".simplicio-loop" / "install-ownership.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(fields), encoding="utf-8")


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
    with pytest.raises(InstallError):
        uninstall(target)
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "mine"


def test_dir_replaced_by_symlink_is_refused_before_deleting_anything(target, outside):
    (target / "a.txt").write_text("loop", encoding="utf-8")
    (target / "d").symlink_to(outside, target_is_directory=True)
    write_receipt(target, paths=["a.txt", "d/keep.txt"], dirs=["d"])
    with pytest.raises(InstallError):
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
    with pytest.raises(InstallError):
        uninstall(target)
    assert (target / "a.txt").is_file()
    assert (outside / "keep.txt").is_file()


def test_install_doc_says_global_resync_files_stay():
    text = (Path(__file__).resolve().parents[2] / "INSTALL.md").read_text(encoding="utf-8")
    assert "~/.codex/skills/simplicio-*" in text and "stay after" in text
