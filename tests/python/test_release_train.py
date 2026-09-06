from __future__ import annotations

from simplicio import release_train as rt


def _manifest(*, version: str = "0.26.28", signed: bool = True) -> dict:
    whl = "sha256:" + "1" * 64
    sdist = "sha256:" + "2" * 64
    return {
        "schema": rt.MANIFEST_SCHEMA,
        "component": "simplicio-mapper",
        "version": version,
        "commit_sha": "a" * 40,
        "commit_sha_source": "immutable release tag",
        "generated_at": "2026-09-04T15:28:19Z",
        "distribution": {
            "pypi_package": "simplicio-mapper",
            "npm_package": "@wesleysimplicio/llm-project-mapper",
        },
        "schema_versions": {"component-release": "v1", "context-handle": "v2"},
        "protocols": ["simplicio.component-release/v1"],
        "capabilities": ["simplicio.mapper-artifacts/v1", "simplicio.plugin.context-handle/v2"],
        "compatibility": {"simplicio-dev-cli": {"plugin-context-handle": "v1|v2"}},
        "artifact_digest": whl,
        "artifact_digests": {
            "whl": {"filename": "simplicio_mapper-0.26.28-py3-none-any.whl", "digest": whl},
            "sdist": {"filename": "simplicio_mapper-0.26.28.tar.gz", "digest": sdist},
        },
        "signing": (
            {
                "status": "signed",
                "algorithm": "Ed25519",
                "digest": "sha256:" + "3" * 64,
                "signature": "base64:signature",
                "sbom": "sha256:" + "4" * 64,
            }
            if signed
            else {"status": "not-implemented", "digest": None, "signature": None, "sbom": None}
        ),
        "downstream_events": {"status": "dispatch-ready", "deduplication": "event_id"},
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


def test_manifest_requires_exact_artifact_identity():
    manifest = _manifest()
    del manifest["artifact_digests"]["whl"]
    errors = rt.validate_mapper_manifest(manifest, require_signed=True)
    assert any("artifact_digest is not present" in error for error in errors)


def test_event_round_trip_reproduces_immutable_event_id():
    event = rt.build_release_event(_manifest(), channel="stable")
    assert rt.validate_release_event(event) == []
    assert event["event_id"] == event["dedupe_key"]
    assert event["release_manifest_digest"] in {row["digest"] for row in event["artifact_digests"].values()}


def test_verified_candidate_produces_bounded_bump_plan():
    manifest = _manifest()
    event = rt.build_release_event(manifest, channel="stable")
    decision = rt.evaluate_release_event(
        event,
        declared_range=">=0.26.28,<0.27",
        tested_against="0.26.11",
        conformance=_proof(manifest),
    )
    assert decision.status == "accepted"
    assert decision.plan["dependency"]["version"] == "0.26.28"
    assert decision.plan["dependency"]["commit_sha"] == "a" * 40
    assert decision.plan["lock"]["required"] is True
    assert decision.plan["downstream"]["status"] == "pending_dev_cli_publish"


def test_range_only_claim_is_blocked():
    manifest = _manifest()
    event = rt.build_release_event(manifest, channel="stable")
    decision = rt.evaluate_release_event(
        event,
        declared_range=">=0.26.28,<0.27",
        conformance=None,
    )
    assert decision.status == "blocked"
    assert decision.reason_code == "conformance_not_proven"
    assert "conformance evidence is required" in decision.errors


def test_active_task_defers_without_recording_event():
    manifest = _manifest()
    event = rt.build_release_event(manifest, channel="stable")
    decision = rt.evaluate_release_event(
        event,
        declared_range=">=0.26.28,<0.27",
        conformance=_proof(manifest),
        active_task=True,
    )
    assert decision.status == "deferred"
    assert decision.reason_code == "active_task"
    assert decision.state["processed_event_ids"] == []


def test_duplicate_and_out_of_order_events_are_not_reapplied():
    manifest = _manifest()
    event = rt.build_release_event(manifest, channel="stable")
    duplicate = rt.evaluate_release_event(
        event,
        declared_range=">=0.26.28,<0.27",
        conformance=_proof(manifest),
        processed_event_ids=[event["event_id"]],
    )
    assert duplicate.status == "duplicate"

    older_manifest = _manifest(version="0.26.26")
    older = rt.build_release_event(older_manifest, channel="stable")
    out_of_order = rt.evaluate_release_event(
        older,
        declared_range=">=0.26.20,<0.27",
        conformance=_proof(older_manifest),
        last_processed_version="0.26.28",
    )
    assert out_of_order.reason_code == "out_of_order_event"


def test_unsigned_candidate_is_blocked_even_when_compatible():
    manifest = _manifest(signed=False)
    event = rt.build_release_event(manifest)
    event["delivery"]["channel"] = "stable"
    decision = rt.evaluate_release_event(
        event,
        declared_range=">=0.26.28,<0.27",
        conformance=_proof(manifest),
    )
    assert decision.status == "blocked"
    assert decision.reason_code == "attestation_missing"


def test_doctor_reports_release_train_workflow_boundaries(tmp_path):
    payload = rt.release_train_doctor(tmp_path)
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "dependency_not_declared"
    assert payload["automation"]["bump_pr"] == "release-train/mapper-latest"
