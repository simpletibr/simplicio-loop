from __future__ import annotations

import hashlib
import json
import os
import unittest

from simplicio_mapper.context_snapshot import build_context_snapshot
from simplicio_mapper.contract import validate_instance

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONTRACT_ROOT = os.path.join(REPO_ROOT, "simplicio_mapper", "contracts", "evidence-certificate", "v1")
SCHEMA_PATH = os.path.join(CONTRACT_ROOT, "schemas", "evidence-certificate.schema.json")
FIXTURE_PATH = os.path.join(CONTRACT_ROOT, "fixtures", "runtime-shaped", "evidence-certificate.json")


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _minimal_artifacts() -> tuple[dict, dict, dict, dict]:
    project_map = {
        "schema": "simplicio.project-map/v1",
        "version": 1,
        "product": {"name": "minimum-example", "stack": "python"},
        "files": [
            {
                "path": "app.py",
                "language": "python",
                "roles": ["source"],
                "imports": ["os"],
                "exports": ["main"],
            }
        ],
    }
    symbol_index = {
        "schema": "simplicio.symbol-index/v1",
        "version": 1,
        "symbols": [
            {"name": "main", "kind": "function", "qualified_name": "main", "defined_in": "app.py", "line": 3}
        ],
    }
    call_graph = {
        "schema": "simplicio.call-graph/v1",
        "version": 1,
        "edges": [
            {
                "type": "calls",
                "source_file": "app.py",
                "source_symbol": "main",
                "target_file": "app.py",
                "target_symbol": "helper",
                "line": 4,
                "confidence": 0.5,
            }
        ],
    }
    architecture_inventory = {
        "schema": "simplicio.architecture-inventory/v1",
        "version": 1,
        "modules": [{"name": "root", "file_count": 1, "layers": ["app"]}],
        "layers": [{"name": "app", "file_count": 1, "modules": ["root"]}],
    }
    return project_map, symbol_index, call_graph, architecture_inventory


def _extract_handles(snapshot: dict) -> list[dict]:
    handles: list[dict] = []
    seen: set[str] = set()
    for node in snapshot["graph"]["nodes"]:
        handle = dict(node["source"])
        key = _stable_json(handle)
        if key not in seen:
            seen.add(key)
            handles.append(handle)
    for edge in snapshot["graph"]["edges"]:
        handle = dict(edge["source_handle"])
        key = _stable_json(handle)
        if key not in seen:
            seen.add(key)
            handles.append(handle)
    return handles


def _certificate_id(payload: dict) -> str:
    addressable = {k: v for k, v in payload.items() if k != "certificate_id"}
    return _sha256_text(_stable_json(addressable))


def _runtime_shaped_certificate(snapshot: dict) -> dict:
    payload = {
        "schema": "simplicio.evidence-certificate/v1",
        "schema_version": "v1",
        "producer": {
            "name": "simplicio-mapper",
            "version": snapshot["producer"]["version"],
        },
        "observed_context": {
            "revision": snapshot["revision"],
            "snapshot_id": snapshot["snapshot_id"],
            "fidelity": json.loads(json.dumps(snapshot["fidelity"])),
            "handles": _extract_handles(snapshot),
        },
        "runtime_execution": {
            "shape": "simplicio-runtime-certificate",
            "external_runtime": {
                "status": "UNVERIFIED",
                "reason": (
                    "external Simplicio Runtime execution was not exercised in this mapper-owned "
                    "integration test, so the certificate stays Runtime-shaped but explicitly unverified"
                ),
                "command": "simplicio runtime certify --from-context-snapshot <snapshot>",
            },
        },
    }
    payload["certificate_id"] = _certificate_id(payload)
    return payload


class EvidenceCertificateIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = _load(SCHEMA_PATH)

    def test_fixture_validates_and_stays_unverified(self) -> None:
        fixture = _load(FIXTURE_PATH)
        self.assertEqual(validate_instance(fixture, self.schema), [])
        self.assertEqual(fixture["runtime_execution"]["external_runtime"]["status"], "UNVERIFIED")
        self.assertEqual(fixture["certificate_id"], _certificate_id(fixture))

    def test_context_snapshot_fields_round_trip_without_loss(self) -> None:
        pm, si, cg, ai = _minimal_artifacts()
        snapshot = build_context_snapshot(
            "/repo",
            project_map=pm,
            symbol_index=si,
            call_graph=cg,
            architecture_inventory=ai,
            revision="rev-evidence-1",
            fidelity={"status": "complete", "gate": "ready"},
        )
        expected_handles = _extract_handles(snapshot)
        certificate = _runtime_shaped_certificate(snapshot)

        self.assertEqual(validate_instance(certificate, self.schema), [])
        self.assertEqual(certificate["observed_context"]["revision"], snapshot["revision"])
        self.assertEqual(certificate["observed_context"]["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual(certificate["observed_context"]["fidelity"], snapshot["fidelity"])
        self.assertEqual(certificate["observed_context"]["handles"], expected_handles)
        self.assertEqual(certificate["runtime_execution"]["external_runtime"]["status"], "UNVERIFIED")
        self.assertEqual(certificate["certificate_id"], _certificate_id(certificate))


if __name__ == "__main__":
    unittest.main()
