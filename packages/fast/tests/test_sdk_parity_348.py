from benchmarks.bench_sdk_parity_348 import COMMON_READ_ONLY, build_receipt


def test_sdk_parity_receipt_requires_common_read_only_operations() -> None:
    receipt = build_receipt(
        python_capabilities={"operations": ["query", "context", "save"]},
        cli_capabilities={"sdk": {"operations": ["query", "context", "save"]}},
        rust_handshake={"schema": "simplicio.fast.engine-session/v1", "status": "ready", "capabilities": ["query", "context", "stats"]},
        transport={"status": "pass"},
    )
    assert receipt["status"] == "pass"
    assert receipt["parity"]["passed"] is True
    assert set(receipt["parity"]["common_operations"]) >= COMMON_READ_ONLY
    assert "save" in receipt["parity"]["python_only"]
    assert receipt["dispatch"] is False


def test_sdk_parity_receipt_fails_when_read_only_surface_is_missing() -> None:
    receipt = build_receipt(
        python_capabilities={"operations": ["query"]},
        cli_capabilities={"sdk": {"operations": ["query", "context"]}},
        rust_handshake={"capabilities": ["query", "context"]},
        transport={"status": "pass"},
    )
    assert receipt["status"] == "fail"
    assert receipt["parity"]["passed"] is False
