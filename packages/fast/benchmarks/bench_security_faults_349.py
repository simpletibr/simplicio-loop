"""Deterministic fault-injection receipt for issue #349."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Any, Callable

from simplicio_fast.context_security import ContextSecurityError, validate_context_packet
from simplicio_fast.knowledge_projection import KnowledgeFact, KnowledgeProjection
from simplicio_fast.projection import ProjectionEnvelope, ProjectionError
from simplicio_fast.rollout import RolloutController, RolloutError
from simplicio_fast.universal_context import UniversalContextError, compile_context


SCHEMA = "simplicio.fast.security-fault-receipt/v1"


def _packet() -> dict[str, Any]:
    envelope = ProjectionEnvelope.create(
        "code",
        producer="mapper",
        producer_schema="mapper/v1",
        generation="g1",
        stable_handle="code:symbol",
        repository_scope="repo-a",
        tenant_scope="tenant-a",
        payload={"repository": "repo-a", "tenant": "tenant-a", "name": "Symbol"},
    )
    return compile_context([envelope], repository_scope="repo-a", tenant_scope="tenant-a")


def _revoked_handles() -> list[str]:
    projection = KnowledgeProjection("repo-a", "tenant-a", "g1")
    fact = KnowledgeFact(
        "adr", "mapper", "knowledge:revoked", "v1", ("fixture:adr",),
        "verified", "sha256:revoked", "secret contract", "repo-a", "tenant-a",
    )
    projection.apply_delta([fact])
    projection.apply_delta([KnowledgeFact(
        fact.source_type, fact.producer, fact.stable_handle, fact.version,
        fact.provenance, fact.trust, fact.digest, fact.text, fact.repository,
        fact.scope, state="revoked",
    )])
    return projection.query("secret contract")["handles"]


def run() -> dict[str, Any]:
    cases: list[tuple[str, str, Callable[[], object]]] = []
    cases.append(("baseline_packet", "accepted", lambda: validate_context_packet(_packet())))

    def forged_authority() -> object:
        packet = _packet()
        packet["authority"] = "runtime"
        return validate_context_packet(packet)

    cases.append(("forged_authority", "context_authority_invalid", forged_authority))

    def instruction_boundary() -> object:
        packet = _packet()
        packet["instructions"] = True
        return validate_context_packet(packet)

    cases.append(("instruction_boundary", "context_instruction_boundary_invalid", instruction_boundary))

    def private_layout() -> object:
        packet = _packet()
        packet["projections"][0]["payload"]["offset"] = 7
        return validate_context_packet(packet)

    cases.append(("private_layout_field", "context_private_layout_field", private_layout))

    def cross_scope() -> object:
        envelope = ProjectionEnvelope.create(
            "code", producer="mapper", producer_schema="mapper/v1", generation="g1",
            stable_handle="code:symbol", repository_scope="repo-a", tenant_scope="tenant-a",
            payload={"repository": "repo-a", "tenant": "tenant-a"},
        )
        return compile_context([envelope], repository_scope="repo-b", tenant_scope="tenant-a")

    cases.append(("cross_scope", "context_scope_mismatch", cross_scope))

    def digest_tamper() -> object:
        envelope = ProjectionEnvelope.create(
            "code", producer="mapper", producer_schema="mapper/v1", generation="g1",
            stable_handle="code:symbol", payload={"repository": "repo-a", "name": "Symbol"},
        )
        return ProjectionEnvelope.decode(envelope.encode().replace(b'"name":"Symbol"', b'"name":"Tampered"'))

    cases.append(("digest_tamper", "payload_digest_mismatch", digest_tamper))
    cases.append(("revoked_fact", "empty_result", _revoked_handles))

    def corrupt_rollout() -> object:
        with tempfile.TemporaryDirectory(prefix="simplicio-fast-349-") as directory:
            path = Path(directory) / "rollout.json"
            path.write_text("{not-json", encoding="utf-8")
            return RolloutController(path).transition("shadow")

    cases.append(("corrupt_rollout_state", "rollout_state_invalid", corrupt_rollout))

    rows: list[dict[str, Any]] = []
    for name, expected, operation in cases:
        try:
            value = operation()
        except (ContextSecurityError, ProjectionError, UniversalContextError, RolloutError) as error:
            observed = error.reason_code
            passed = observed == expected
            value = None
        else:
            observed = "accepted" if name == "baseline_packet" else ("empty_result" if value == [] else "unexpected_accept")
            passed = observed == expected
        rows.append({"case": name, "expected": expected, "observed": observed, "passed": passed, "value_present": value is not None})
    return {
        "schema": SCHEMA,
        "status": "pass" if all(row["passed"] for row in rows) else "fail",
        "cases": rows,
        "summary": {"total": len(rows), "passed": sum(row["passed"] for row in rows), "failed": sum(not row["passed"] for row in rows)},
        "scope": {"repository": "repo-a", "tenant": "tenant-a", "generation": "g1"},
        "residuals": ["installed_consumer_e2e", "rust_parity", "resource_benchmark", "rollout_receipt"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run()
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    if receipt["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
