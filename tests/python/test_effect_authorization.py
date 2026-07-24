from dataclasses import replace

import pytest

from simplicio.plan_compiler import (
    AuthorizationError,
    EffectAuthorization,
    EffectDispatchContext,
    EffectPlan,
    PlanNode,
    build_change_proposal,
)


def _bundle():
    effect = EffectPlan("effect-1", "node-1", "write", "runtime", "key-1", context_handle="ctx-1")
    context = EffectDispatchContext(
        "plan-1",
        "goal-1",
        PlanNode("node-1", "edit.apply", write_set=["src/app.py"], requires_gate=True),
        [],
        coordinator_id="attempt-1",
        policy_revision="policy-1",
        source_hash="source-1",
        context_handle="ctx-1",
        lease_id="lease-1",
        fencing_token="fence-1",
    )
    proposal = build_change_proposal(effect, context)
    authorization = EffectAuthorization.issue(
        proposal,
        authority="operator-1",
        issuer="simplicio-loop",
        human_gate_receipt="human-gate-1",
        now=100.0,
    )
    return effect, context, proposal, authorization


def test_authorization_is_deterministic_and_round_trips():
    _effect, _context, proposal, authorization = _bundle()

    assert proposal.to_dict()["schema"] == "simplicio.change-proposal/v1"
    assert authorization.to_dict()["schema"] == "simplicio.effect-authorization/v1"
    assert authorization.authorization_digest == authorization.digest()
    assert EffectAuthorization.from_dict(authorization.to_dict()) == authorization
    authorization.verify(proposal, now=100.5)


def test_authorization_json_rejects_unknown_or_missing_fields():
    _effect, _context, _proposal, authorization = _bundle()
    payload = authorization.to_dict()
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_FIELDS_INVALID"):
        EffectAuthorization.from_dict({**payload, "extra": True})
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_FIELDS_MISSING"):
        EffectAuthorization.from_dict({key: value for key, value in payload.items() if key != "issuer"})


@pytest.mark.parametrize("field,value", [("issuer", None), ("fencing_token", 7)])
def test_authorization_json_rejects_non_string_references(field, value):
    _effect, _context, _proposal, authorization = _bundle()
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_FIELDS_INVALID"):
        EffectAuthorization.from_dict({**authorization.to_dict(), field: value})


@pytest.mark.parametrize("field,value", [("issued_at", float("nan")), ("expires_at", float("inf"))])
def test_authorization_json_rejects_non_finite_timestamps(field, value):
    _effect, _context, _proposal, authorization = _bundle()
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_FIELDS_INVALID"):
        EffectAuthorization.from_dict({**authorization.to_dict(), field: value})


def test_authorization_issue_rejects_non_finite_ttl_and_time():
    _effect, _context, proposal, _authorization = _bundle()
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_FIELDS_INVALID"):
        EffectAuthorization.issue(
            proposal, authority="operator-1", issuer="simplicio-loop", ttl_s=float("nan")
        )
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_FIELDS_INVALID"):
        EffectAuthorization.issue(
            proposal,
            authority="operator-1",
            issuer="simplicio-loop",
            human_gate_receipt="human-gate-1",
            now=float("inf"),
        )


def test_irreversible_proposal_requires_human_gate():
    _effect, _context, proposal, _authorization = _bundle()

    with pytest.raises(AuthorizationError, match="human_gate_receipt"):
        EffectAuthorization.issue(proposal, authority="operator-1", issuer="simplicio-loop", now=100.0)


def test_llm_cannot_issue_authorization():
    _effect, _context, proposal, _authorization = _bundle()

    with pytest.raises(AuthorizationError, match="LLM_CANNOT_AUTHORIZE"):
        EffectAuthorization.issue(
            proposal,
            authority="operator-1",
            issuer="llm",
            human_gate_receipt="human-gate-1",
            now=100.0,
        )


def test_expired_authorization_fails_closed():
    _effect, _context, proposal, authorization = _bundle()

    with pytest.raises(AuthorizationError, match="AUTHORIZATION_EXPIRED"):
        authorization.verify(proposal, now=161.0)


def test_tampered_proposal_or_authorization_digest_fails_closed():
    effect, context, proposal, authorization = _bundle()
    changed = replace(effect, effect_id="effect-forged")
    changed_proposal = build_change_proposal(changed, context)

    with pytest.raises(AuthorizationError, match="AUTHORIZATION_PROPOSAL_MISMATCH"):
        authorization.verify(changed_proposal, now=100.5)

    with pytest.raises(AuthorizationError, match="AUTHORIZATION_DIGEST_INVALID"):
        replace(authorization, human_gate_receipt="forged-gate").verify(proposal, now=100.5)


def test_proposal_binds_write_set_and_causal_fence():
    effect, context, proposal, authorization = _bundle()
    forged_context = replace(context, fencing_token="fence-2")
    forged_proposal = build_change_proposal(effect, forged_context)

    assert forged_proposal.digest() != proposal.digest()
    with pytest.raises(AuthorizationError, match="AUTHORIZATION_PROPOSAL_MISMATCH"):
        authorization.verify(forged_proposal, now=100.5)
