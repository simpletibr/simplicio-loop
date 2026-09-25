from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from simplicio_mapper.cli import main
from simplicio_mapper.release_governance import (
    attach_sbom,
    build_cyclonedx_sbom,
    build_rollback_plan,
    check_registry_parity,
    classify_release_change,
    evaluate_stable_promotion,
    reconcile_release_events,
    run_release_governance_cli,
    sign_release_manifest,
    verify_release_manifest_signature,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts" / "component-release" / "v1" / "fixtures"


def _manifest(version: str = "0.26.26") -> dict:
    return {
        "schema": "simplicio.component-release/v1",
        "component": "simplicio-mapper",
        "version": version,
        "commit_sha": "a" * 40,
        "commit_sha_source": "fixture",
        "generated_at": "2026-09-03T00:00:00Z",
        "distribution": {
            "pypi_package": "simplicio-mapper",
            "npm_package": "@wesleysimplicio/llm-project-mapper",
        },
        "schema_versions": {"project-map": "v1", "context-handle": "v2"},
        "protocols": ["simplicio.component-release/v1"],
        "capabilities": ["context-handle/v1", "context-handle/v2"],
        "compatibility": {"simplicio-dev-cli": {"context-handle": "v1|v2"}},
        "artifact_digest": "sha256:" + "b" * 64,
        "artifact_digests": {
            "whl": {"filename": f"simplicio_mapper-{version}-py3-none-any.whl", "digest": "sha256:" + "c" * 64},
            "sdist": {"filename": f"simplicio_mapper-{version}.tar.gz", "digest": "sha256:" + "d" * 64},
        },
        "signing": {
            "status": "not-implemented",
            "digest": None,
            "signature": None,
            "sbom": None,
            "note": "unsigned fixture",
        },
        "downstream_events": {"status": "dispatch-ready", "note": "fixture"},
    }


def _private_key_pem() -> bytes:
    return Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )


class ReleaseChangeClassificationTest(unittest.TestCase):
    def test_additive_capability_is_compatible(self) -> None:
        previous = _manifest("0.26.25")
        current = _manifest()
        current["capabilities"].append("new-capability/v1")

        report = classify_release_change(previous, current)

        self.assertEqual(report["classification"], "compatible")
        self.assertIn("new-capability/v1", report["capabilities"]["added"])

    def test_removed_capability_and_changed_schema_are_breaking(self) -> None:
        previous = _manifest("0.26.25")
        current = _manifest()
        current["capabilities"].remove("context-handle/v1")
        current["schema_versions"]["project-map"] = "v2"

        report = classify_release_change(previous, current)

        self.assertEqual(report["classification"], "breaking")
        self.assertIn("context-handle/v1", report["capabilities"]["removed"])
        self.assertIn("project-map", report["schema_versions"]["changed"])


class RegistryParityTest(unittest.TestCase):
    def test_exact_pypi_and_npm_versions_pass(self) -> None:
        result = check_registry_parity(_manifest(), pypi_version="0.26.26", npm_version="0.26.26")
        self.assertEqual(result["status"], "passed")

    def test_partial_registry_release_blocks_stable(self) -> None:
        result = check_registry_parity(_manifest(), pypi_version="0.26.26", npm_version=None)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("npm", result["failures"])

    def test_divergent_registry_release_blocks_stable(self) -> None:
        result = check_registry_parity(_manifest(), pypi_version="0.26.26", npm_version="0.26.25")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("npm", result["failures"])


class SigningAndSbomTest(unittest.TestCase):
    def test_real_ed25519_signature_detects_tampering(self) -> None:
        signed = sign_release_manifest(_manifest(), _private_key_pem())
        self.assertEqual(signed["signing"]["status"], "signed")
        self.assertTrue(verify_release_manifest_signature(signed))

        tampered = copy.deepcopy(signed)
        tampered["commit_sha"] = "f" * 40
        self.assertFalse(verify_release_manifest_signature(tampered))

    def test_sbom_digest_is_covered_by_signature(self) -> None:
        manifest = _manifest()
        sbom = build_cyclonedx_sbom(manifest)
        with_sbom = attach_sbom(manifest, sbom)
        signed = sign_release_manifest(with_sbom, _private_key_pem())

        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertIsInstance(sbom["properties"][0]["value"], str)
        self.assertRegex(signed["signing"]["sbom"], r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(verify_release_manifest_signature(signed))


class ReleaseReconciliationTest(unittest.TestCase):
    def test_missed_and_duplicate_events_are_reconciled_once_in_version_order(self) -> None:
        manifests = [_manifest("0.26.26"), _manifest("0.26.25"), _manifest("0.26.26")]
        result = reconcile_release_events(manifests, processed_event_ids=set())

        self.assertEqual([event["version"] for event in result["pending"]], ["0.26.25", "0.26.26"])
        self.assertEqual(result["duplicates_skipped"], 1)

        processed = {result["pending"][0]["event_id"]}
        second = reconcile_release_events(manifests, processed_event_ids=processed)
        self.assertEqual([event["version"] for event in second["pending"]], ["0.26.26"])

    def test_rollback_plan_is_deterministic_and_revokes_current_release(self) -> None:
        first = build_rollback_plan(_manifest(), _manifest("0.26.25"), reason="consumer regression")
        second = build_rollback_plan(_manifest(), _manifest("0.26.25"), reason="consumer regression")

        self.assertEqual(first, second)
        self.assertEqual(first["revoke"]["version"], "0.26.26")
        self.assertEqual(first["restore"]["version"], "0.26.25")


class StablePromotionTest(unittest.TestCase):
    def test_all_gates_allow_stable(self) -> None:
        previous = _manifest("0.26.25")
        current = attach_sbom(_manifest(), build_cyclonedx_sbom(_manifest()))
        current = sign_release_manifest(current, _private_key_pem())

        result = evaluate_stable_promotion(
            current,
            previous_manifest=previous,
            pypi_version="0.26.26",
            npm_version="0.26.26",
            downstream_ack_minutes=8,
            benchmark_regressions=[],
        )

        self.assertEqual(result["decision"], "promote-stable")

    def test_unsigned_partial_release_and_regression_remain_canary(self) -> None:
        result = evaluate_stable_promotion(
            _manifest(),
            previous_manifest=_manifest("0.26.25"),
            pypi_version="0.26.26",
            npm_version=None,
            downstream_ack_minutes=None,
            benchmark_regressions=["rss"],
        )

        self.assertEqual(result["decision"], "hold-canary")
        self.assertIn("registry-parity", result["failed_gates"])
        self.assertIn("signature", result["failed_gates"])
        self.assertIn("benchmark", result["failed_gates"])


class ReleaseGovernanceCliTest(unittest.TestCase):
    def test_parity_cli_fails_closed_when_npm_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                status = run_release_governance_cli(
                    [
                        "parity",
                        "--manifest",
                        str(manifest_path),
                        "--pypi-version",
                        "0.26.26",
                    ]
                )
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "blocked")

    def test_public_cli_dispatches_release_governance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "release-governance",
                        "parity",
                        "--manifest",
                        str(manifest_path),
                        "--pypi-version",
                        "0.26.26",
                    ]
                )
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "blocked")

    def test_sign_and_verify_cli_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            key_path = root / "release-key.pem"
            signed_path = root / "signed.json"
            sbom_path = root / "sbom.cdx.json"
            manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
            key_path.write_bytes(_private_key_pem())

            output = StringIO()
            with redirect_stdout(output):
                sign_status = run_release_governance_cli(
                    [
                        "sign",
                        "--manifest",
                        str(manifest_path),
                        "--key",
                        str(key_path),
                        "--output",
                        str(signed_path),
                        "--sbom-output",
                        str(sbom_path),
                    ]
                )
            self.assertEqual(sign_status, 0)
            self.assertTrue(sbom_path.is_file())

            output = StringIO()
            with redirect_stdout(output):
                verify_status = run_release_governance_cli(
                    ["verify", "--manifest", str(signed_path)]
                )
            self.assertEqual(verify_status, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "passed")


class InstalledConformanceFixturesTest(unittest.TestCase):
    def test_current_and_previous_release_fixtures_are_present(self) -> None:
        fixtures = [
            json.loads((FIXTURES / "0.26.25.json").read_text(encoding="utf-8")),
            json.loads((FIXTURES / "0.26.26.json").read_text(encoding="utf-8")),
        ]
        self.assertEqual([fixture["version"] for fixture in fixtures], ["0.26.25", "0.26.26"])
        self.assertTrue(all(fixture["schema"] == "simplicio.component-release/v1" for fixture in fixtures))


if __name__ == "__main__":
    unittest.main()
