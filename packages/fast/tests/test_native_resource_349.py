from pathlib import Path

from benchmarks.bench_native_resource_349 import build_receipt


def test_native_resource_receipt_requires_resource_and_rollout_passes() -> None:
    receipt = build_receipt(
        executable=Path("native.exe"),
        handshake={
            "schema": "simplicio.fast.engine-session/v1",
            "abi": "simplicio.fast-native/v1",
            "capabilities": ["sha256", "page"],
            "transport": "stdio-lines",
        },
        resource={"status": "pass", "p95_ms": 1.2},
        rollout={"status": "pass", "corrupt_state_reason": "rollout_state_invalid"},
    )
    assert receipt["status"] == "pass"
    assert receipt["native"]["abi"] == "simplicio.fast-native/v1"
    assert receipt["authority"] == "derived_read_only"
    assert receipt["dispatch"] is False


def test_native_resource_receipt_fails_closed_on_resource_failure() -> None:
    receipt = build_receipt(
        executable=Path("native.exe"),
        handshake={"capabilities": []},
        resource={"status": "fail"},
        rollout={"status": "pass"},
    )
    assert receipt["status"] == "fail"
