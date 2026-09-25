import hashlib
import json

from scripts.manual_native_release import TARGETS, _tar_bytes, archive


def test_manual_runner_declares_workflow_targets():
    assert set(TARGETS) == {
        "linux-x86_64",
        "linux-aarch64",
        "macos-aarch64",
        "windows-x86_64",
    }
    assert TARGETS["windows-x86_64"].compatibility_filename.endswith(".exe")


def test_deterministic_archive_and_verified_platforms(tmp_path):
    root = tmp_path
    output = root / "dist"
    platform = output / "linux-x86_64"
    native = platform / "simplicio.fast-native_v1"
    core = platform / "simplicio.fast-core_v1"
    native.mkdir(parents=True)
    core.mkdir(parents=True)
    binary = native / "simplicio-fast-native"
    binary.write_bytes(b"native")
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    (native / "manifest.json").write_text(
        json.dumps(
            {
                "abi": "simplicio.fast-native/v1",
                "platform": "linux-x86_64",
                "filename": binary.name,
                "version": "2.0.20",
                "source_commit": "a" * 40,
                "toolchain": "fixture",
                "size": 6,
                "sha256": digest,
            }
        ),
        encoding="utf-8",
    )
    core_binary = core / "simplicio-fast-rs"
    core_binary.write_bytes(b"core")
    (core / "engine-manifest.json").write_text(
        json.dumps(
            {
                "schema": "simplicio.fast.engine-manifest/v1",
                "engine": "rust",
                "status": "available",
                "version": "2.0.20",
                "capabilities": ["stats", "query", "context"],
                "conformance": {"passed": True, "digest": "sha256:fixture"},
            }
        ),
        encoding="utf-8",
    )
    first = _tar_bytes(platform)
    second = _tar_bytes(platform)
    assert first == second
    receipt = archive(root, output, version="2.0.20", platforms=["linux-x86_64"])
    assert receipt["archives"][0]["deterministic"] is True
    assert (
        receipt["archives"][0]["sha256"]
        == hashlib.sha256(
            (output / "simplicio-fast-engines-linux-x86_64.tar.gz").read_bytes()
        ).hexdigest()
    )
