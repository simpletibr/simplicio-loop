import pytest

from simplicio_fast.resident_daemon import DaemonError, DaemonRequest, make_request


def test_resident_transport_rejects_coercion_and_invalid_scalar_types() -> None:
    request = make_request("request", "slot")
    for field, value in (("request_id", 1), ("slot_id", 1), ("operation", 1), ("generation", True), ("deadline_ns", True)):
        with pytest.raises(DaemonError, match="protocol_field_invalid"):
            DaemonRequest.parse({**request, field: value})


def test_resident_transport_rejects_nested_offsets_and_oversized_payloads() -> None:
    request = make_request("request", "slot")
    with pytest.raises(DaemonError, match="protocol_exposes_offset"):
        DaemonRequest.parse({**request, "payload": {"nested": [{"pointer": 7}]}})
    with pytest.raises(DaemonError, match="protocol_payload_too_large"):
        DaemonRequest.parse({**request, "payload": {"content": "x" * (256 * 1024)}})


def test_resident_transport_rejects_non_json_payloads() -> None:
    request = make_request("request", "slot")
    with pytest.raises(DaemonError, match="protocol_payload_invalid"):
        DaemonRequest.parse({**request, "payload": {"content": object()}})


def test_resident_transport_rejects_non_finite_json_numbers() -> None:
    request = make_request("request", "slot")
    with pytest.raises(DaemonError, match="protocol_payload_invalid"):
        DaemonRequest.parse({**request, "payload": {"content": float("nan")}})
