import asyncio

import pytest

from simplicio_fast.projection import ProjectionEnvelope
from simplicio_fast.sdk import ProjectionSDK, SDKError


def envelope(handle: str) -> ProjectionEnvelope:
    return ProjectionEnvelope.create("code", producer="mapper", producer_schema="mapper/v1", generation="g1", stable_handle=handle, payload={"repository": "repo", "name": handle})


def test_sdk_exposes_scoped_in_process_operations_and_context(tmp_path) -> None:
    sdk = ProjectionSDK("repo")
    sdk.publish(envelope("symbol:a"))
    assert sdk.query("symbol:a")["stable_handle"] == "symbol:a"
    assert sdk.capabilities()["authority"] == "derived_read_only"
    assert sdk.context()["projection_count"] == 1
    path = tmp_path / "projection.json"
    sdk.save(path)
    reopened = ProjectionSDK.open(path, "repo")
    assert reopened.snapshot() == sdk.snapshot()
    matrix = sdk.capabilities()["support_matrix"]
    assert {item["surface"]: item["status"] for item in matrix} == {
        "python": "supported",
        "rust": "partial",
        "session": "partial",
        "cli": "partial",
    }
    assert matrix[0]["reason"] is None
    assert "close" in matrix[0]["operations"]
    assert "close" in sdk.capabilities()["operations"]


def test_sdk_async_surface_is_read_only_and_matches_sync() -> None:
    sdk = ProjectionSDK("repo")
    sdk.publish(envelope("symbol:a"))

    async def run() -> None:
        assert await sdk.query_async("symbol:a") == sdk.query("symbol:a")
        assert await sdk.context_async() == sdk.context()

    asyncio.run(run())


def test_sdk_supports_twenty_concurrent_async_queries(tmp_path) -> None:
    sdk = ProjectionSDK("repo")
    sdk.publish(envelope("symbol:a"))

    async def run() -> None:
        results = await asyncio.gather(*(sdk.query_async("symbol:a") for _ in range(20)))
        assert results == [sdk.query("symbol:a")] * 20
        path = tmp_path / "projection.json"
        receipt = await asyncio.to_thread(sdk.save, path)
        assert receipt["records"] == 1

    asyncio.run(run())


def test_sdk_delta_and_error_contract_are_explicit() -> None:
    error = SDKError("contract_invalid")
    assert error.reason_code == "contract_invalid"
    assert str(error) == "contract_invalid"
    sdk = ProjectionSDK("repo")
    result = sdk.compile_delta("g1", changed=(envelope("symbol:a"),), closure_handles=("symbol:downstream",))
    assert result["changed_handles"] == ["symbol:a"]
    assert result["closure_handles"] == ["symbol:a", "symbol:downstream"]


def test_sdk_rejects_malformed_inputs_with_typed_reason_codes(tmp_path) -> None:
    sdk = ProjectionSDK("repo")
    with pytest.raises(SDKError, match="envelope_invalid"):
        sdk.publish(object())  # type: ignore[arg-type]
    with pytest.raises(SDKError, match="changed_invalid"):
        sdk.compile_delta("g1", changed=(object(),))  # type: ignore[tuple-item]
    with pytest.raises(SDKError, match="deleted_handles_invalid"):
        sdk.compile_delta("g1", deleted_handles="symbol:a")  # type: ignore[arg-type]
    with pytest.raises(SDKError, match="closure_handles_invalid"):
        sdk.compile_delta("g1", closure_handles=("",))
    with pytest.raises(SDKError, match="query_handle_invalid"):
        sdk.query(1)  # type: ignore[arg-type]
    with pytest.raises(SDKError, match="query_handle_invalid"):
        asyncio.run(sdk.query_async(""))
    with pytest.raises(SDKError, match="repository_invalid"):
        ProjectionSDK(1)  # type: ignore[arg-type]
    sdk.publish(envelope("symbol:a"))
    foreign = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="symbol:foreign",
        payload={"repository": "other", "name": "foreign"},
    )
    with pytest.raises(SDKError, match="projection_repository_mismatch"):
        sdk.publish(foreign)
    with pytest.raises(SDKError, match="projection_generation_stale"):
        sdk.compile_delta("g2")
    with pytest.raises(SDKError, match="context_budget_invalid"):
        sdk.context(max_tokens=0)
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{", encoding="utf-8")
    with pytest.raises(SDKError, match="projection_store_invalid"):
        ProjectionSDK.open(invalid_path, "repo")


def test_sdk_compile_delta_supports_explicit_generation_swap() -> None:
    sdk = ProjectionSDK("repo")
    sdk.publish(envelope("symbol:a"))
    replacement = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g2",
        stable_handle="symbol:b",
        payload={"repository": "repo", "name": "symbol:b"},
    )
    receipt = sdk.compile_delta(
        "g2",
        base_generation="g1",
        changed=(replacement,),
        deleted_handles=("symbol:a",),
    )
    assert receipt["base_generation"] == "g1"
    assert sdk.generation == "g2"
    assert sdk.query("symbol:a") is None
    assert sdk.query("symbol:b")["generation"] == "g2"


def test_sdk_context_manager_closes_and_rejects_use_after_close() -> None:
    with ProjectionSDK("repo") as sdk:
        assert not sdk.closed
        sdk.publish(envelope("symbol:a"))
    assert sdk.closed
    sdk.close()
    with pytest.raises(SDKError, match="sdk_closed"):
        sdk.snapshot()
    with pytest.raises(SDKError, match="sdk_closed"):
        _ = sdk.generation


def test_sdk_async_context_manager_closes() -> None:
    async def run() -> ProjectionSDK:
        async with ProjectionSDK("repo") as sdk:
            assert not sdk.closed
            return sdk

    sdk = asyncio.run(run())
    assert sdk.closed
    with pytest.raises(SDKError, match="sdk_closed"):
        asyncio.run(sdk.query_async("symbol:a"))
