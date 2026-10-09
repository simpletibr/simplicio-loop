"""How simplicio-loop was installed (#1575): binary | pip | source, and the release artifact names."""
from __future__ import annotations

import json
import sys

import pytest

from simplicio_loop import distribution as dist


class FakeDist:
    def __init__(self, direct_url=None):
        self.direct_url = direct_url

    def read_text(self, name):
        assert name == "direct_url.json"
        return self.direct_url


def installed(monkeypatch, direct_url=None, present=True):
    def lookup(name):
        assert name == "simplicio-loop"
        if not present:
            raise dist.metadata.PackageNotFoundError(name)
        return FakeDist(direct_url)

    monkeypatch.setattr(dist.metadata, "distribution", lookup)


def test_frozen_means_binary_whatever_else_is_true(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    installed(monkeypatch, json.dumps({"dir_info": {"editable": True}}))
    assert dist.is_frozen() is True
    assert dist.kind() == dist.BINARY
    assert dist.kind(editable=True, checkout=True) == dist.BINARY


def test_not_frozen_is_not_binary(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    installed(monkeypatch)
    assert dist.is_frozen() is False
    assert dist.kind(checkout=False) != dist.BINARY


def test_editable_install_is_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    installed(monkeypatch, json.dumps({"dir_info": {"editable": True}}))
    assert dist.is_editable() is True
    assert dist.kind(checkout=False) == dist.SOURCE


def test_a_git_checkout_is_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    installed(monkeypatch)  # a wheel is also installed, but this code runs from the checkout
    assert dist.kind(checkout=True) == dist.SOURCE


def test_a_wheel_is_pip_with_or_without_direct_url(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    for direct_url in (None, "", json.dumps({"url": "file:///x", "dir_info": {}}), "not json"):
        installed(monkeypatch, direct_url)
        assert dist.is_editable() is False
        assert dist.kind(checkout=False) == dist.PIP, direct_url


def test_no_metadata_and_no_checkout_is_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
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


@pytest.mark.parametrize("system,machine,expected", [
    ("Linux", "x86_64", ("linux", "x86_64")),
    ("linux", "amd64", ("linux", "x86_64")),
    ("Darwin", "arm64", ("darwin", "aarch64")),
    ("Darwin", "x86_64", ("darwin", "x86_64")),
    ("Windows", "AMD64", ("windows", "x86_64")),
    ("Linux", "aarch64", ("linux", "aarch64")),
    ("Windows", "ARM64", ("windows", "aarch64")),
])
def test_platform_key(system, machine, expected):
    assert dist.platform_key(system, machine) == expected


@pytest.mark.parametrize("system,machine", [("Plan9", "x86_64"), ("Linux", "riscv64"), ("FreeBSD", "amd64")])
def test_platform_key_refuses_what_has_no_release(system, machine):
    with pytest.raises(dist.UnsupportedPlatform):
        dist.platform_key(system, machine)


def test_platform_key_of_this_machine_is_a_release_platform():
    os_name, arch = dist.platform_key()
    assert os_name in dist.OS_NAMES and arch in {"x86_64", "aarch64"}


@pytest.mark.parametrize("version,os_name,arch,name", [
    ("3.49.0", "linux", "x86_64", "simplicio-loop-v3.49.0-linux-x86_64"),
    ("v3.49.0", "linux", "x86_64", "simplicio-loop-v3.49.0-linux-x86_64"),
    ("3.49.0", "darwin", "aarch64", "simplicio-loop-v3.49.0-darwin-aarch64"),
    ("3.49.0", "windows", "x86_64", "simplicio-loop-v3.49.0-windows-x86_64.exe"),
])
def test_binary_asset_name_is_the_release_contract(version, os_name, arch, name):
    assert dist.binary_asset_name(version, os_name, arch) == name


@pytest.mark.parametrize("os_name,arch", [("plan9", "x86_64"), ("linux", "riscv64"), ("Linux", "x86_64")])
def test_binary_asset_name_refuses_unknown_names(os_name, arch):
    with pytest.raises(dist.UnsupportedPlatform):
        dist.binary_asset_name("3.49.0", os_name, arch)


def test_bundle_root_reads_the_package_data_through_importlib_resources():
    root = dist.bundle_root()
    assert root.joinpath("skills").is_dir()
    assert root.joinpath("skills", "simplicio-loop", "SKILL.md").is_file()
