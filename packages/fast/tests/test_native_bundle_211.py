import hashlib
import json

from scripts.build_native_manifest import ABI
from scripts.verify_native_bundle import SCHEMA, verify


def _bundle(tmp_path, **overrides):
    directory = tmp_path / ABI.replace("/", "_")
    directory.mkdir(exist_ok=True)
    artifact = directory / "simplicio-fast-native"
    artifact.write_bytes(b"precompiled-native-fixture")
    manifest = {
        "abi": ABI,
        "platform": "linux-x86_64",
        "filename": artifact.name,
        "version": "2.0.14",
        "source_commit": "a" * 40,
        "toolchain": "rustc fixture",
        "size": artifact.stat().st_size,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        **overrides,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return artifact


def test_verified_precompiled_bundle_passes_without_toolchain(tmp_path):
    _bundle(tmp_path)
    receipt = verify(
        tmp_path,
        expected_platform="linux-x86_64",
        expected_version="2.0.14",
    )
    assert receipt["schema"] == SCHEMA
    assert receipt["status"] == "pass"


def test_tamper_and_version_drift_fail_closed(tmp_path):
    artifact = _bundle(tmp_path)
    artifact.write_bytes(b"tampered")
    receipt = verify(
        tmp_path,
        expected_platform="linux-x86_64",
        expected_version="2.0.14",
    )
    assert receipt["status"] == "fail"
    assert {"SHA256_MISMATCH", "SIZE_MISMATCH"} <= set(receipt["failures"])
    _bundle(tmp_path, version="1.0.0")
    receipt = verify(
        tmp_path,
        expected_platform="linux-x86_64",
        expected_version="2.0.14",
    )
    assert "VERSION_MISMATCH" in receipt["failures"]


def test_path_traversal_and_platform_mismatch_fail_closed(tmp_path):
    _bundle(tmp_path, filename="../escape", platform="macos-aarch64")
    receipt = verify(
        tmp_path,
        expected_platform="linux-x86_64",
        expected_version="2.0.14",
    )
    assert {"FILENAME_INVALID", "PLATFORM_MISMATCH"} <= set(receipt["failures"])
