from __future__ import annotations

import json
from dataclasses import replace

from simplicio.plan_compiler import EffectAuthorization, EffectPlan, OfflineRuntimeTransport
from simplicio.plan_compiler.authority import build_change_proposal
from simplicio.plan_compiler.effect_sink import EffectDispatchContext
from simplicio.plan_compiler.models import PlanDAG, PlanNode, VerificationPlan
from simplicio.plan_compiler.runtime_effect_sink import RuntimeEffectSink


def _context(effect: EffectPlan) -> EffectDispatchContext:
    node = PlanNode(
        "node-1",
        "edit.apply",
        read_set=["src/app.py"],
        write_set=["offline-created.txt"],
        risk="medium",
        acceptance_criteria_refs=["AC1"],
        requires_gate=True,
        rollback_strategy="checkpoint",
    )
    context = EffectDispatchContext(
        "plan-1",
        "goal-1",
        node,
        [VerificationPlan("verify-1", "node-1", "pytest", "pytest -q", 60, acceptance_criteria_refs=["AC1"])],
        coordinator_kind="simplicio-loop",
        coordinator_id="loop-1",
        session_id="session-1",
        turn_id="turn-1",
        attempt=1,
        subworkflow_id="issue-301",
        policy_revision="migration-v1",
        base_hash="base-sha",
        source_hash="source-sha",
        context_handle="ctx-1",
        lease_id="lease-1",
        fencing_token="fence-1",
        plan=PlanDAG(
            "plan-1",
            "goal-1",
            "snapshot-1",
            "revision-1",
            nodes=[node],
            context_handle="ctx-1",
        ),
    )
    proposal = build_change_proposal(effect, context)
    return replace(
        context,
        authorization=EffectAuthorization.issue(
            proposal,
            authority="operator-1",
            issuer="simplicio-loop",
            human_gate_receipt="human-gate-1",
        ),
    )


def _effect(artifact_ref: str) -> EffectPlan:
    return EffectPlan(
        "effect-offline-1",
        "node-1",
        "write",
        "dev-cli.edit",
        "a" * 64,
        ["source clean"],
        artifact_ref=artifact_ref,
        context_handle="ctx-1",
    )


def _write_artifact(root):
    path = root / "offline-plan.json"
    path.write_text(
        json.dumps(
            {
                "schema": "simplicio.mechanical-edit/v1",
                "operations": [{"op": "create_file", "path": "offline-created.txt", "text": "Effect API\n"}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_offline_transport_applies_authorized_artifact_and_persists_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    _write_artifact(tmp_path)
    effect = _effect("offline-plan.json")
    context = _context(effect)
    transport = OfflineRuntimeTransport(root=tmp_path)

    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)

    assert outcome.state == "completed"
    assert outcome.receipt["executor"] == "offline-local"
    assert outcome.receipt["gate_decision"] == "allow"
    assert (tmp_path / "offline-created.txt").read_text(encoding="utf-8") == "Effect API\n"
    assert transport.apply_count == 1

    second_transport = OfflineRuntimeTransport(root=tmp_path)
    repeated = RuntimeEffectSink(second_transport, root=tmp_path).submit(effect, context)
    assert repeated.state == "completed"
    assert second_transport.apply_count == 0


def test_offline_transport_reconciles_lost_response_without_duplicate_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    _write_artifact(tmp_path)
    effect = _effect("offline-plan.json")
    context = _context(effect)
    first_transport = OfflineRuntimeTransport(root=tmp_path, failure="after_apply")

    uncertain = RuntimeEffectSink(first_transport, root=tmp_path).submit(effect, context)
    assert uncertain.state == "effect_unknown"
    assert first_transport.apply_count == 1

    reconciler = OfflineRuntimeTransport(root=tmp_path)
    resolved = RuntimeEffectSink(reconciler, root=tmp_path).submit(effect, context)
    assert resolved.state == "completed"
    assert reconciler.apply_count == 0
    assert (tmp_path / "offline-created.txt").read_text(encoding="utf-8") == "Effect API\n"
