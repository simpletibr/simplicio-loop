import json

from scripts.verify_fast_core_bundle import SCHEMA, verify


def _manifest(*, version: str = "2.0.20") -> dict[str, object]:
    return {
        "schema": "simplicio.fast.engine-manifest/v1",
        "engine": "rust",
        "status": "available",
        "version": version,
        "capabilities": ["stats", "query", "context"],
        "conformance": {"passed": True, "digest": "sha256:fixture"},
    }


def test_core_bundle_receipt_requires_verified_engine_handshake(tmp_path):
    binary = tmp_path / "simplicio-fast-rs"
    binary.write_bytes(b"precompiled-rust-core")
    manifest = tmp_path / "engine-manifest.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")

    receipt = verify(binary, manifest, expected_version="2.0.20")

    assert receipt["schema"] == SCHEMA
    assert receipt["status"] == "pass"
    assert receipt["sha256"]


def test_core_bundle_rejects_missing_contract_fields(tmp_path):
    binary = tmp_path / "simplicio-fast-rs"
    binary.write_bytes(b"precompiled-rust-core")
    manifest = tmp_path / "engine-manifest.json"
    value = _manifest(version="9.9.9")
    value["capabilities"] = ["stats"]
    value["conformance"] = {"passed": False}
    manifest.write_text(json.dumps(value), encoding="utf-8")

    receipt = verify(binary, manifest, expected_version="2.0.20")

    assert receipt["status"] == "fail"
    assert {"VERSION_MISMATCH", "CAPABILITIES_MISSING", "CONFORMANCE_MISSING"} <= set(
        receipt["failures"]
    )
