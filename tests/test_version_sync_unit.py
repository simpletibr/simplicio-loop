import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from scripts.version_sync import (
    ADAPTER_VERSION_FILES,
    CLAUDE_DESCRIPTOR_FILES,
    VersionSyncError,
    _claude_descriptor_digest,
    apply_version,
    check_version,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_repo(tmp_path, version="1.2.3", plugin_version="1.2.3",
                fallback_version="1.2.3"):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{version}"\nrequires-python = ">=3.8"\n',
        encoding="utf-8",
    )
    plugin_dir = repo / ".cursor-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": plugin_version, "note": "café"}, indent=2) + "\n",
        encoding="utf-8",
    )
    pkg_dir = repo / "simplicio_loop"
    pkg_dir.mkdir()
    # Mirrors the real simplicio_loop/__init__.py shape: a dynamic lookup (not a string literal,
    # so the regex-based fallback scan does not match it) followed by two literal fallback
    # assignments that must agree with each other and with the canonical version.
    (pkg_dir / "__init__.py").write_text(
        "try:\n"
        "    from importlib.metadata import version as _v\n"
        "    __version__ = _v(\"demo\")\n"
        "except Exception:\n"
        f'    __version__ = "{fallback_version}"\n'
        "else:\n"
        f'    __version__ = "{fallback_version}"\n',
        encoding="utf-8",
    )
    (pkg_dir / "stack_manifest.py").write_text(
        '_FALLBACK_FLOORS = {\n    "simplicio-loop": "' + fallback_version + '",\n}\n',
        encoding="utf-8",
    )
    release_train = repo / "docs" / "release-train"
    release_train.mkdir(parents=True)
    (release_train / "compatibility-contract.json").write_text(
        json.dumps({"release_train_version": f"v{version}"}, indent=2) + "\n",
        encoding="utf-8",
    )
    return repo


# ---------------------------------------------------------------------------
# check — thin wrapper over release_manifest.build_manifest()
# ---------------------------------------------------------------------------

def test_check_reports_ready_when_every_surface_agrees(tmp_path):
    repo = _make_repo(tmp_path)
    result = check_version(repo)
    assert result["ok"] is True
    assert result["manifest"]["canonical_version"] == "1.2.3"
    assert result["manifest"]["mismatches"] == []


def test_check_reports_blocked_on_drift(tmp_path):
    repo = _make_repo(tmp_path, plugin_version="1.2.4")
    result = check_version(repo)
    assert result["ok"] is False
    assert "cursor_plugin" in result["manifest"]["mismatches"]


# ---------------------------------------------------------------------------
# apply — mechanical, one-shot rewrite of every derived surface
# ---------------------------------------------------------------------------

def test_apply_rewrites_every_surface_and_leaves_manifest_ready(tmp_path):
    repo = _make_repo(tmp_path, version="1.2.3",
                       plugin_version="1.2.3", fallback_version="1.2.3")
    result = apply_version(repo, "9.9.9")
    assert result["ok"] is True
    assert result["manifest"]["canonical_version"] == "9.9.9"
    assert set(result["changed_files"]) == {
        "pyproject.toml",
        os.path.join(".cursor-plugin", "plugin.json"),
        os.path.join("simplicio_loop", "__init__.py"),
        os.path.join("simplicio_loop", "stack_manifest.py"),
        os.path.join("docs", "release-train", "compatibility-contract.json"),
    }
    assert 'version = "9.9.9"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert json.loads((repo / ".cursor-plugin" / "plugin.json").read_text())["version"] == "9.9.9"
    assert '__version__ = "9.9.9"' in (repo / "simplicio_loop" / "__init__.py").read_text(encoding="utf-8")
    assert '"simplicio-loop": "9.9.9"' in (
        repo / "simplicio_loop" / "stack_manifest.py"
    ).read_text(encoding="utf-8")
    release_train = json.loads(
        (repo / "docs" / "release-train" / "compatibility-contract.json").read_text()
    )
    assert release_train["release_train_version"] == "v9.9.9"


def test_apply_preserves_unrelated_json_formatting_and_unicode_escapes(tmp_path):
    # Rewriting via json.dumps would silently re-escape/reflow the whole file (e.g. turn a
    # \uXXXX-escaped character into a literal UTF-8 byte) even though only the version changed.
    repo = _make_repo(tmp_path)
    plugin_path = repo / ".cursor-plugin" / "plugin.json"
    plugin_path.write_text(
        '{\n  "name": "demo",\n  "version": "1.2.3",\n  "note": "caf\\u00e9"\n}\n',
        encoding="utf-8",
    )
    apply_version(repo, "2.0.0")
    text = plugin_path.read_text(encoding="utf-8")
    assert '"version": "2.0.0"' in text
    assert '\\u00e9' in text  # unicode escape preserved byte-for-byte, not reflowed


def test_apply_is_idempotent_when_already_at_target_version(tmp_path):
    repo = _make_repo(tmp_path)
    apply_version(repo, "9.9.9")
    result = apply_version(repo, "9.9.9")
    assert result["changed_files"] == []
    assert result["ok"] is True


def test_apply_updates_host_adapters_and_claude_descriptor_digests(tmp_path):
    repo = _make_repo(tmp_path)
    for relative in ADAPTER_VERSION_FILES:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('ADAPTER_VERSION = "1.2.3"\n', encoding="utf-8")

    descriptor = {
        "schema": "simplicio.plugin-descriptor/v1",
        "name": "simplicio-loop",
        "host": "claude",
        "version": "1.2.3",
        "digest": _claude_descriptor_digest("1.2.3"),
    }
    for relative in CLAUDE_DESCRIPTOR_FILES:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")

    result = apply_version(repo, "2.0.0")
    assert result["ok"] is True
    for relative in ADAPTER_VERSION_FILES:
        assert 'ADAPTER_VERSION = "2.0.0"' in (repo / relative).read_text(encoding="utf-8")
    for relative in CLAUDE_DESCRIPTOR_FILES:
        value = json.loads((repo / relative).read_text(encoding="utf-8"))
        assert value["version"] == "2.0.0"
        assert value["digest"] == _claude_descriptor_digest("2.0.0")


def test_apply_rejects_malformed_version(tmp_path):
    repo = _make_repo(tmp_path)
    with pytest.raises(VersionSyncError):
        apply_version(repo, "not-a-version")


def test_apply_rejects_partial_semver(tmp_path):
    repo = _make_repo(tmp_path)
    with pytest.raises(VersionSyncError):
        apply_version(repo, "1.2")


# ---------------------------------------------------------------------------
# real repo — exercise the actual committed surfaces, not just a synthetic fixture
# ---------------------------------------------------------------------------

def test_check_on_the_real_repo_is_ready():
    result = check_version(REPO_ROOT)
    assert result["ok"] is True, result["manifest"]
