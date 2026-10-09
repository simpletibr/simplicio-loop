from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

from simplicio_loop import distribution


class TestIsFrozen:
    def test_not_frozen_by_default(self):
        assert distribution.is_frozen() is False

    def test_frozen_when_set(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert distribution.is_frozen() is True


class TestKind:
    def test_frozen_priority(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        result = distribution.kind(frozen=True)
        assert result == distribution.BINARY

    def test_editable_when_not_frozen(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        
        # Mock the distribution with direct_url.json
        def mock_distribution(name):
            mock_dist = mock.Mock()
            mock_dist.read_text.return_value = '{"dir_info": {"editable": true}}'
            return mock_dist
        
        with mock.patch("simplicio_loop.distribution.metadata.distribution", side_effect=mock_distribution):
            result = distribution.kind(editable=True)
            assert result == distribution.SOURCE

    def test_checkout_when_git_exists(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        
        # Create a fake .git
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        
        # Mock Path to return our tmp_path
        with mock.patch("pathlib.Path.resolve") as mock_resolve:
            mock_path = mock.Mock()
            mock_path.parent.parent = tmp_path
            mock_resolve.return_value = mock_path
            
            with mock.patch("pathlib.Path.exists", return_value=True):
                result = distribution.kind(checkout=True)
                assert result == distribution.SOURCE

    def test_pip_when_distribution_exists(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        
        # Mock distribution that exists
        def mock_distribution(name):
            mock_dist = mock.Mock()
            mock_dist.read_text.return_value = '{"dir_info": {"editable": false}}'
            return mock_dist
        
        with mock.patch("simplicio_loop.distribution.metadata.distribution", side_effect=mock_distribution):
            with mock.patch("pathlib.Path.exists", return_value=False):
                result = distribution.kind()
                assert result == distribution.PIP

    def test_source_fallback(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        
        # Mock distribution not found - simulate PackageNotFoundError on second call
        from importlib import metadata
        
        call_count = [0]
        
        def mock_distribution(name):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (in editable detection) - raise exception
                raise metadata.PackageNotFoundError(name)
            else:
                # Second call (in pip detection) - also raise
                raise metadata.PackageNotFoundError(name)
        
        with mock.patch("simplicio_loop.distribution.metadata.distribution", side_effect=mock_distribution):
            with mock.patch("pathlib.Path.exists", return_value=False):
                result = distribution.kind()
                assert result == distribution.SOURCE


class TestPlatformKey:
    def test_linux_x86_64(self):
        result = distribution.platform_key(system="Linux", machine="x86_64")
        assert result == ("linux", "x86_64")

    def test_darwin_arm64(self):
        result = distribution.platform_key(system="Darwin", machine="arm64")
        assert result == ("darwin", "aarch64")

    def test_windows_amd64(self):
        result = distribution.platform_key(system="Windows", machine="amd64")
        assert result == ("windows", "x86_64")

    def test_aarch64_mapping(self):
        result = distribution.platform_key(system="Linux", machine="aarch64")
        assert result == ("linux", "aarch64")

    def test_arm64_mapping(self):
        result = distribution.platform_key(system="Darwin", machine="ARM64")
        assert result == ("darwin", "aarch64")

    def test_unsupported_system(self):
        with pytest.raises(distribution.UnsupportedPlatform):
            distribution.platform_key(system="Plan9", machine="x86_64")

    def test_unsupported_arch(self):
        with pytest.raises(distribution.UnsupportedPlatform):
            distribution.platform_key(system="Linux", machine="riscv64")


class TestBinaryAssetName:
    def test_linux_x86_64(self):
        result = distribution.binary_asset_name("3.49.0", "linux", "x86_64")
        assert result == "simplicio-loop-v3.49.0-linux-x86_64"

    def test_darwin_aarch64(self):
        result = distribution.binary_asset_name("1.0.0", "darwin", "aarch64")
        assert result == "simplicio-loop-v1.0.0-darwin-aarch64"

    def test_windows_with_exe(self):
        result = distribution.binary_asset_name("2.5.0", "windows", "x86_64")
        assert result == "simplicio-loop-v2.5.0-windows-x86_64.exe"

    def test_version_with_leading_v(self):
        result = distribution.binary_asset_name("v3.49.0", "linux", "x86_64")
        assert result == "simplicio-loop-v3.49.0-linux-x86_64"

    def test_version_without_leading_v(self):
        result = distribution.binary_asset_name("3.49.0", "linux", "x86_64")
        assert result == "simplicio-loop-v3.49.0-linux-x86_64"

    def test_invalid_os(self):
        with pytest.raises(distribution.UnsupportedPlatform):
            distribution.binary_asset_name("1.0.0", "invalid_os", "x86_64")

    def test_invalid_arch(self):
        with pytest.raises(distribution.UnsupportedPlatform):
            distribution.binary_asset_name("1.0.0", "linux", "invalid_arch")


class TestBundleRoot:
    def test_bundle_root_is_traversable(self):
        bundle = distribution.bundle_root()
        # Check it has joinpath method (Traversable interface)
        assert hasattr(bundle, "joinpath")

    def test_bundle_skills_exists(self):
        bundle = distribution.bundle_root()
        skills = bundle.joinpath("skills")
        assert skills.is_dir()
