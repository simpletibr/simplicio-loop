from __future__ import annotations

from simplicio import release_train as rt
from simplicio.release_train_adapters import (
    build_github_bump_request,
    build_loop_dispatch_request,
    reconcile_adapter_receipt,
)

from test_release_train import _manifest, _proof


def test_adapter_requests_are_receipt_bound_and_deduplicated() -> None:
    manifest = _manifest()
    event = rt.build_release_event(manifest, channel="stable")
    decision = rt.evaluate_release_event(
        event,
        declared_range=">=0.26.27,<0.27",
        conformance=_proof(manifest),
    )
    request = build_github_bump_request(decision)
    assert request["status"] == "ready_for_authenticated_dispatch"
    assert request["dedupe_key"] == event["event_id"]
    assert request["receipt"] is None
    assert reconcile_adapter_receipt(request, None)["status"] == "pending"


def test_loop_adapter_waits_for_pypi_receipt() -> None:
    manifest = _manifest()
    event = rt.build_release_event(manifest, channel="stable")
    decision = rt.evaluate_release_event(
        event,
        declared_range=">=0.26.27,<0.27",
        conformance=_proof(manifest),
    )
    blocked = build_loop_dispatch_request(decision, dev_cli_release=None)
    assert blocked["reason_code"] == "pypi_not_published"
    ready = build_loop_dispatch_request(
        decision,
        dev_cli_release={"status": "pypi_published", "release_id": "v0.18.13", "artifact_digest": "sha256:x"},
    )
    assert ready["status"] == "ready_for_authenticated_dispatch"

