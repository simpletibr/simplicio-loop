"""Focused production-runner coverage for the standalone effect boundary (Hookwall-sealed dispatch)."""

from __future__ import annotations

import json
import subprocess

import pytest

from simplicio_loop import runner
from tests._contract_only_hookwall import ContractOnlyHookwallLedger


@pytest.fixture(autouse=True)
def _contract_only_hookwall(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_hookwall_ledger",
        lambda *_args, **_kwargs: ContractOnlyHookwallLedger(),
    )
from simplicio_loop.hookwall_gate import HookwallBlocked, gate_completion


def _request(tmp_path):
    return runner._EffectRequest(
        workspace=str(tmp_path),
        idempotency_key="run-695:task-1:1",
        write_set=("repo:simplicio_loop/runner.py",),
        lease_id="lease-695",
        fencing_token=7,
        attempt_id="attempt-695",
        gate_id="gate-695",
        transaction_id="tx-695",
    )


def test_execution_profile_is_always_standalone_and_rejects_unknown(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTION_PROFILE", "auto")
    assert runner._execution_profile() == "standalone"
    monkeypatch.setenv("SIMPLICIO_EXECUTION_PROFILE", "unexpected")
    with pytest.raises(
        RuntimeError,
        match="SIMPLICIO_EXECUTION_PROFILE must be standalone",
    ):
        runner._execution_profile()


def test_standalone_fake_path_remains_functional(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON",
        json.dumps({"write_files": {"standalone.txt": "preserved"}, "stdout": {"ok": True}}),
    )
    outcome = runner._execute_operator_effect(
        request=_request(tmp_path),
        argv=["simplicio-dev-cli", "task", "compile"],
        env={},
        repo_path=tmp_path,
    )
    assert outcome["source"] == "env_override"
    assert (tmp_path / "standalone.txt").read_text(encoding="utf-8") == "preserved"
    assert gate_completion(outcome["hookwall_evidence"]) == (True, "ok")


class _RecordingHookwall:
    def __init__(self):
        self.calls = []

    def reserve(self, _envelope, _pre_decision):
        self.calls.append(("reserve",))
        return {"action": "EXECUTE", "state": "RESERVED"}

    def mark_unresolved(self, key, reason):
        self.calls.append(("mark_unresolved", key, reason))

    def reconcile_failed(self, key, receipt):
        self.calls.append(("reconcile_failed", key, receipt))
        return {"state": "FAILED", "receipt_hash": "proof"}


def test_blocked_operator_with_explicit_no_mutation_proof_reconciles_mapper_effect(
    tmp_path, monkeypatch
):
    ledger = _RecordingHookwall()
    monkeypatch.setattr(runner, "_hookwall_ledger", lambda *_args, **_kwargs: ledger)
    monkeypatch.setenv(
        "SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON",
        json.dumps({
            "returncode": 1,
            "stdout": {
                "status": "blocked",
                "applied": False,
                "blocked_preconditions": [{"code": "llm_execution_disabled"}],
                "files": None,
                "errors": None,
            },
        }),
    )
    before = runner._repo_fingerprint(tmp_path)

    outcome = runner._execute_operator_effect(
        request=_request(tmp_path),
        argv=["simplicio-dev-cli", "task"],
        env={},
        repo_path=tmp_path,
        source_hash=before["tree_hash"],
    )

    assert [call[0] for call in ledger.calls] == [
        "reserve", "mark_unresolved", "reconcile_failed"
    ]
    assert outcome["uncertain"] is False
    assert outcome["hookwall_reason"] == "effect_failed_no_mutation"
    assert outcome["hookwall_reconciliation"]["proof"]["blocked_codes"] == [
        "llm_execution_disabled"
    ]


def test_ambiguous_failed_operator_keeps_mapper_effect_unknown(tmp_path, monkeypatch):
    ledger = _RecordingHookwall()
    monkeypatch.setattr(runner, "_hookwall_ledger", lambda *_args, **_kwargs: ledger)
    monkeypatch.setenv(
        "SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON",
        json.dumps({
            "returncode": 1,
            "stdout": {
                "status": "blocked",
                "applied": False,
                "blocked_preconditions": [{"code": "operator_failed"}],
                "files": [{"path": "site/checkers.html"}],
                "errors": None,
            },
        }),
    )
    before = runner._repo_fingerprint(tmp_path)

    outcome = runner._execute_operator_effect(
        request=_request(tmp_path),
        argv=["simplicio-dev-cli", "task"],
        env={},
        repo_path=tmp_path,
        source_hash=before["tree_hash"],
    )

    assert [call[0] for call in ledger.calls] == ["reserve", "mark_unresolved"]
    assert "hookwall_reconciliation" not in outcome
    assert outcome["hookwall_reason"] == "effect_not_committed"


def test_operator_timeout_is_uncertain_and_is_not_reconciled(tmp_path, monkeypatch):
    ledger = _RecordingHookwall()
    monkeypatch.setattr(runner, "_hookwall_ledger", lambda *_args, **_kwargs: ledger)
    monkeypatch.delenv("SIMPLICIO_LOOP_FAKE_OPERATOR_EXEC_JSON", raising=False)

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["simplicio-dev-cli", "task"], 1)

    monkeypatch.setattr(runner.subprocess, "run", timeout)
    before = runner._repo_fingerprint(tmp_path)

    outcome = runner._execute_operator_effect(
        request=_request(tmp_path),
        argv=["simplicio-dev-cli", "task"],
        env={},
        repo_path=tmp_path,
        source_hash=before["tree_hash"],
    )

    assert outcome["uncertain"] is True
    assert [call[0] for call in ledger.calls] == ["reserve", "mark_unresolved"]
    assert "hookwall_reconciliation" not in outcome


def test_hookwall_pre_blocks_before_any_operator_effect(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        runner,
        "validate_pre_decision",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HookwallBlocked("hookwall_pre_blocked", "policy denied")
        ),
    )
    monkeypatch.setattr(
        runner,
        "_execute_operator_effect_unchecked",
        lambda **kwargs: called.append(kwargs),
    )
    with pytest.raises(HookwallBlocked, match="hookwall_pre_blocked"):
        runner._execute_operator_effect(
            request=_request(tmp_path),
            argv=["simplicio-dev-cli", "task", "compile"],
            env={},
            repo_path=tmp_path,
        )
    assert called == []



def test_hookwall_completion_rejects_missing_and_unverified_evidence():
    assert gate_completion(None) == (False, "hookwall_evidence_missing")
    evidence = {
        "schema": "simplicio.hookwall-evidence/v1",
        "envelope_id": "tx",
        "envelope_hash": "env",
        "receipt_hash": "receipt",
        "idempotency_key": "key",
        "fence": 1,
        "verdict": "blocked",
    }
    evidence["evidence_hash"] = runner._hookwall_digest(evidence)
    assert gate_completion(evidence) == (False, "hookwall_effect_unverified")
