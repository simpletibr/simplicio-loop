from __future__ import annotations

from simplicio import release_train as rt
from simplicio.component_manifest import tested_dependency_artifacts as read_tested_dependency_artifacts
from simplicio.release_train_adapters import build_loop_dispatch_request, reconcile_adapter_receipt


def _manifest(version: str = "0.26.28") -> dict:
    wheel = "sha256:" + "1" * 64
    source = "sha256:" + "2" * 64
    return {
        "schema": rt.MANIFEST_SCHEMA,
        "component": "simplicio-mapper",
        "version": version,
        "commit_sha": "b" * 40,
        "commit_sha_source": "immutable tag",
        "generated_at": "2026-09-06T00:00:00Z",
        "distribution": {"pypi_package": "simplicio-mapper"},
        "schema_versions": {"component-release": "v1"},
        "protocols": ["simplicio.component-release/v1"],
        "capabilities": ["simplicio.mapper-artifacts/v1"],
        "compatibility": {"simplicio-dev-cli": {"mapper-artifacts": "v1"}},
        "artifact_digest": wheel,
        "artifact_digests": {
            "whl": {"filename": "mapper.whl", "digest": wheel},
            "sdist": {"filename": "mapper.tar.gz", "digest": source},
        },
        "signing": {"status": "not-implemented"},
        "downstream_events": {"deduplication": "event_id"},
    }


def _proof(manifest: dict) -> dict:
    return {
        "status": "passed",
        "version": manifest["version"],
        "commit_sha": manifest["commit_sha"],
        "entrypoint_owner": "simplicio-mapper",
        "lockfile": {"version": manifest["version"]},
        "n": "passed",
        "n_minus_1": "passed",
        "artifact_digests": manifest["artifact_digests"],
        "capabilities": manifest["capabilities"],
        "schema_versions": manifest["schema_versions"],
        "smoke": {
            "status": "passed",
            "map": {"status": "passed"},
            "retrieve": {"status": "passed"},
            "edit": {"status": "passed"},
            "test": {"status": "passed"},
            "receipt_digest": "sha256:" + "5" * 64,
        },
    }


def test_canary_transport_event_is_accepted_after_conformance() -> None:
    manifest = _manifest()
    event = rt.build_release_event(manifest, channel="canary")
    decision = rt.evaluate_release_event(
        {"client_payload": event},
        declared_range=">=0.26.28,<0.27",
        conformance=_proof(manifest),
    )
    assert decision.status == "accepted"


def test_loop_dispatch_contains_the_full_manifest_and_correct_event_type() -> None:
    manifest = _manifest()
    event = rt.build_release_event(manifest, channel="canary")
    decision = rt.evaluate_release_event(
        event,
        declared_range=">=0.26.28,<0.27",
        conformance={**_proof(manifest), "status": "passed"},
    )
    dev_manifest = {
        "schema": "simplicio.component-release/v1",
        "component": "simplicio-dev-cli",
        "package": "simplicio-cli",
        "version": "0.18.12",
        "artifacts": [{"digest": "sha256:" + "c" * 64}],
    }
    request = build_loop_dispatch_request(
        decision,
        dev_cli_release={
            "status": "pypi_published",
            "release_id": "v0.18.12",
            "version": "0.18.12",
            "artifact_digest": "sha256:" + "c" * 64,
            "manifest": dev_manifest,
        },
    )
    assert request["event_type"] == rt.EVENT_SCHEMA
    assert request["payload"]["manifests"] == [dev_manifest]


def test_adapter_receipt_rejects_wrong_idempotency_and_release_identity() -> None:
    manifest = _manifest()
    event = rt.build_release_event(manifest, channel="canary")
    decision = rt.evaluate_release_event(
        event,
        declared_range=">=0.26.28,<0.27",
        conformance=_proof(manifest),
    )
    from simplicio.release_train_adapters import build_github_bump_request

    request = build_github_bump_request(decision)
    wrong = {
        "status": "merged",
        "dedupe_key": request["dedupe_key"],
        "idempotency_key": "github-bump:wrong",
        "version": request["evidence"]["version"],
        "artifact_digest": request["evidence"]["artifact_digest"],
    }
    assert reconcile_adapter_receipt(request, wrong)["reason_code"] == "receipt_idempotency_mismatch"


def test_real_lock_exposes_mapper_artifact_digests() -> None:
    version, artifacts, reason = read_tested_dependency_artifacts("simplicio-mapper")
    assert version == "0.26.31"
    assert reason == "locked_in_uv.lock"
    assert artifacts["sdist"]["digest"].startswith("sha256:")
    assert artifacts["wheels"][0]["digest"].startswith("sha256:")
