"""How simplicio-loop was installed (#1575): pip or source."""
from __future__ import annotations

import json

from simplicio_loop import distribution as dist


class FakeDist:
    def __init__(self, direct_url=None):
        self.direct_url = direct_url

    def read_text(self, name):
        assert name == "direct_url.json"
        return self.direct_url


def installed(monkeypatch, direct_url=None, present=True):
    """The install record the shared lookup answers with: pip's record (with this direct_url.json), or none."""
    record = FakeDist(direct_url) if present else None
    monkeypatch.setattr(dist, "install_record", lambda: record)


def test_editable_install_is_source(monkeypatch):
    installed(monkeypatch, json.dumps({"dir_info": {"editable": True}}))
    assert dist.is_editable() is True
    assert dist.kind(checkout=False) == dist.SOURCE


def test_a_git_checkout_is_source(monkeypatch):
    installed(monkeypatch)  # a wheel is also installed, but this code runs from the checkout
    assert dist.kind(checkout=True) == dist.SOURCE


def test_a_wheel_is_pip_with_or_without_direct_url(monkeypatch):
    for direct_url in (None, "", json.dumps({"url": "file:///x", "dir_info": {}}), "not json"):
        installed(monkeypatch, direct_url)
        assert dist.is_editable() is False
        assert dist.kind(checkout=False) == dist.PIP, direct_url


def test_no_metadata_and_no_checkout_is_source(monkeypatch):
    installed(monkeypatch, present=False)
    assert dist.is_editable() is False
    assert dist.kind(checkout=False) == dist.SOURCE


def test_checkout_is_detected_from_the_git_entry_above_the_package(tmp_path, monkeypatch):
    package = tmp_path / "repo" / "simplicio_loop"
    package.mkdir(parents=True)
    monkeypatch.setattr(dist, "__file__", str(package / "distribution.py"))
    assert dist.in_checkout() is False
    (tmp_path / "repo" / ".git").write_text("gitdir: elsewhere\n")  # a worktree has a .git FILE
    assert dist.in_checkout() is True


def test_this_test_tree_is_a_checkout():
    assert dist.in_checkout() is True


def test_bundle_root_reads_the_package_data_through_importlib_resources():
    root = dist.bundle_root()
    assert root.joinpath("skills").is_dir()
    assert root.joinpath("skills", "simplicio-loop", "SKILL.md").is_file()
