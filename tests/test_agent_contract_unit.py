import pytest

from simplicio_loop.agent_contract import (
    AgentContractError,
    bind_receipt,
    build_context_pack,
    validate_context_pack,
    validate_identity,
)


IDENTITY = {"agent_id": "codex-a", "runtime": "codex", "device_id": "laptop-a", "session_id": "s1",
            "capabilities": ["claim", "heartbeat", "fencing", "receipts"]}


def test_context_pack_is_allow_listed_and_receipt_is_agent_bound():
    pack = build_context_pack(task_id="T1", goal="fix docs", identity=IDENTITY,
                              acs=["tests pass"], source_refs=["README.md", "secret.txt"],
                              allowed_paths=["README.md"],
                              issue_ref="wesleysimplicio/simplicio-loop#183")
    assert pack["source_refs"] == ["README.md"]
    assert pack["issue_ref"] == "wesleysimplicio/simplicio-loop#183"
    assert pack["issue_url"] == "https://github.com/wesleysimplicio/simplicio-loop/issues/183"
    assert "prompt" not in pack and "transcript" not in pack
    receipt = bind_receipt({"status": "VERIFIED"}, IDENTITY, context_pack=pack)
    assert receipt["agent"] == validate_identity(IDENTITY)
    assert receipt["issue_ref"] == pack["issue_ref"]
    assert receipt["issue_url"] == pack["issue_url"]
    with pytest.raises(AgentContractError, match="duplicate capabilities"):
        validate_identity({**IDENTITY, "capabilities": ["claim", "claim"]})


def test_context_pack_rejects_non_allow_listed_fields_and_capability_drift():
    pack = build_context_pack(task_id="T1", goal="fix docs", identity=IDENTITY, allowed_paths=["README.md"])
    with pytest.raises(AgentContractError, match="non-allow-listed fields"):
        bind_receipt({"status": "VERIFIED"}, IDENTITY, context_pack={**pack, "prompt": "secret"})
    with pytest.raises(AgentContractError, match="capabilities do not match"):
        validate_context_pack({**pack, "capabilities": ["claim"]}, IDENTITY)


def test_context_pack_canonicalizes_issue_url_and_rejects_mismatched_issue_identity():
    pack = build_context_pack(task_id="T183", goal="ship distributed claims", identity=IDENTITY,
                              issue_url="https://github.com/wesleysimplicio/simplicio-loop/issues/183")
    assert pack["issue_ref"] == "wesleysimplicio/simplicio-loop#183"
    assert pack["issue_url"] == "https://github.com/wesleysimplicio/simplicio-loop/issues/183"
    with pytest.raises(AgentContractError, match="different issues"):
        validate_context_pack({**pack, "issue_ref": "wesleysimplicio/simplicio-loop#184"}, IDENTITY)
    with pytest.raises(AgentContractError, match="canonical owner/repo#123"):
        validate_context_pack({**pack, "issue_ref": "issue #183"}, IDENTITY)


def test_stage_identity_fields_round_trip_and_legacy_receipt_is_unbound():
    identity = {
        **IDENTITY,
        "role_id": "reviewer",
        "role_version": "1.0.0",
        "stage_id": "review",
        "stage_version": "1.0.0",
        "run_id": "run-1",
        "work_item_id": "wi-1",
        "attempt_id": "attempt-1",
        "fence": "fence-1",
        "plan_revision": 0,
        "coordinator_agent_id": "coord",
        "parent_instance_id": "parent",
        "idempotency_key": "idem-1",
    }
    pack = build_context_pack(task_id="T1", goal="review", identity=identity,
                              allowed_paths=["README.md"], source_refs=["README.md"])
    assert pack["role_id"] == "reviewer"
    assert pack["attempt_id"] == "attempt-1"
    receipt = bind_receipt({"status": "VERIFIED"}, identity, context_pack=pack)
    assert receipt["stage_id"] == "review"
    assert receipt["idempotency_key"] == "idem-1"
    assert receipt["legacy_unbound"] is True
    with pytest.raises(AgentContractError, match="fence"):
        bind_receipt({"status": "VERIFIED", "fence": "other"}, identity, context_pack=pack)
