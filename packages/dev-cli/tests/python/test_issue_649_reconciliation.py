from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplicio.commands import reconcile as reconcile_cmd
from simplicio.dev_cli_contracts import reconcile as contract_reconcile
from simplicio.standalone_migration import (
    effect_unknown_details,
    effect_unknown_pending,
    record_effect_unknown,
)

KEY = "issue-649-key"
EVIDENCE_LOCATOR = ".simplicio/runtime-effects/reconciliation/issue-649-key.json"


def _args(root: Path, *, evidence_file: str = EVIDENCE_LOCATOR) -> argparse.Namespace:
    evidence = root / evidence_file
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("{}\n", encoding="utf-8")
    return argparse.Namespace(
        root=str(root),
        idempotency_key=KEY,
        evidence_file=evidence_file,
        json=True,
    )


def _record_lock(root: Path) -> argparse.Namespace:
    args = _args(root)
    record_effect_unknown(
        str(root),
        {
            "idempotency_key": KEY,
            "repo": str(root.resolve()),
            "evidence_file": EVIDENCE_LOCATOR,
        },
    )
    return args


def _runtime_payload(
    *,
    verdict: str,
    safe: bool,
    status: str,
    effect_state: str,
    evidence: dict[str, object] | None = None,
    observed_files: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "schema": "simplicio.effect-reconciliation/v1",
        "idempotency_key": KEY,
        "status": status,
        "effect_state": effect_state,
        "safe_to_clear_pending": safe,
        "fail_closed": True,
        "verdict": verdict,
        "evidence": evidence or {"files": []},
        "observed_files": observed_files or [],
        "durability": {
            "schema": "simplicio.receipt-durability/v1",
            "status": "durable",
            "verification": "verified_read_back",
        },
    }


def _completed(payload: dict[str, object], *, returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(payload), stderr="")


def test_retry_after_crash_after_effect_replays_durable_applied_receipt(tmp_path, monkeypatch, capsys):
    args = _record_lock(tmp_path)
    calls: list[list[str]] = []
    payload = _runtime_payload(
        verdict="proven-after",
        safe=True,
        status="reconciled",
        effect_state="proven",
    )

    def fake_call(argv, **_kwargs):
        calls.append(argv)
        return _completed(payload)

    monkeypatch.setattr(reconcile_cmd, "call_simplicio", fake_call)

    assert reconcile_cmd.run(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["outcome"] == "applied"
    assert first["safe_to_clear_pending"] is True
    assert first["replayed"] is False
    assert effect_unknown_pending(str(tmp_path)) is False
    receipt = tmp_path / first["durable_receipt"]["locator"]
    assert receipt.is_file()

    assert reconcile_cmd.run(args) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["outcome"] == "applied"
    assert replay["replayed"] is True
    assert replay["durable_receipt"]["sha256"] == first["durable_receipt"]["sha256"]
    assert len(calls) == 1


def test_retry_after_crash_before_effect_is_not_applied_and_safe_to_retry(tmp_path, monkeypatch, capsys):
    args = _record_lock(tmp_path)
    payload = _runtime_payload(
        verdict="unchanged-before",
        safe=True,
        status="not-applied",
        effect_state="not-applied",
    )
    monkeypatch.setattr(reconcile_cmd, "call_simplicio", lambda *_a, **_k: _completed(payload))

    assert reconcile_cmd.run(args) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["outcome"] == "not-applied"
    assert result["status"] == "reconciled"
    assert effect_unknown_pending(str(tmp_path)) is False


def test_concurrent_duplicate_observations_call_runtime_once(tmp_path, monkeypatch):
    args = _record_lock(tmp_path)
    payload = _runtime_payload(
        verdict="proven-after",
        safe=True,
        status="reconciled",
        effect_state="proven",
    )
    calls = 0
    guard = threading.Lock()

    def fake_call(*_args, **_kwargs):
        nonlocal calls
        with guard:
            calls += 1
        time.sleep(0.05)
        return _completed(payload)

    monkeypatch.setattr(reconcile_cmd, "call_simplicio", fake_call)
    monkeypatch.setattr(
        reconcile_cmd,
        "_emit",
        lambda result, _args: 0 if result.get("safe_to_clear_pending") is True else 1,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        codes = list(executor.map(lambda _index: reconcile_cmd.run(args), range(2)))

    assert codes == [0, 0]
    assert calls == 1
    assert effect_unknown_pending(str(tmp_path)) is False


@pytest.mark.parametrize(
    ("observed", "expected_outcome"),
    [
        (["b" * 64, "c" * 64], "partial"),
        (["d" * 64, "e" * 64], "blocked"),
    ],
)
def test_ambiguous_effects_are_durable_and_never_reported_as_success_or_failure(
    tmp_path, monkeypatch, capsys, observed, expected_outcome
):
    args = _record_lock(tmp_path)
    files = [
        {"path": "a.txt", "before_sha256": "a" * 64, "after_sha256": "b" * 64},
        {"path": "b.txt", "before_sha256": "c" * 64, "after_sha256": "f" * 64},
    ]
    payload = _runtime_payload(
        verdict="ambiguous-or-diverged",
        safe=False,
        status="unresolved",
        effect_state="applied-but-unproven",
        evidence={"files": files},
        observed_files=[
            {"path": "a.txt", "observed_sha256": observed[0]},
            {"path": "b.txt", "observed_sha256": observed[1]},
        ],
    )
    calls = 0

    def fake_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _completed(payload, returncode=1)

    monkeypatch.setattr(reconcile_cmd, "call_simplicio", fake_call)

    assert reconcile_cmd.run(args) == 1
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "unresolved"
    assert first["outcome"] == expected_outcome
    assert first["safe_to_clear_pending"] is False
    assert effect_unknown_pending(str(tmp_path)) is True

    assert reconcile_cmd.run(args) == 1
    replay = json.loads(capsys.readouterr().out)
    assert replay["outcome"] == expected_outcome
    assert replay["replayed"] is True
    assert calls == 1


def test_same_key_cannot_switch_evidence_locator(tmp_path, monkeypatch, capsys):
    args = _record_lock(tmp_path)
    alternate = tmp_path / "alternate.json"
    alternate.write_text("{}\n", encoding="utf-8")
    args.evidence_file = str(alternate)
    monkeypatch.setattr(
        reconcile_cmd,
        "call_simplicio",
        lambda *_a, **_k: pytest.fail("Runtime must not observe a second locator for the same key"),
    )

    assert reconcile_cmd.run(args) == 1
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == "refused"
    assert result["error"]["code"] == "EVIDENCE_LOCATOR_MISMATCH"
    assert effect_unknown_pending(str(tmp_path)) is True


def test_missing_observation_is_not_found_not_success_or_failure(tmp_path, monkeypatch, capsys):
    args = _args(tmp_path)
    monkeypatch.setattr(
        reconcile_cmd,
        "call_simplicio",
        lambda *_a, **_k: pytest.fail("Runtime must not run without a causal lock or durable receipt"),
    )

    assert reconcile_cmd.run(args) == 1
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == "not-found"
    assert result["outcome"] == "not-found"
    assert result["safe_to_clear_pending"] is False
    assert contract_reconcile(root=tmp_path, idempotency_key=KEY)["status"] == "not-found"


def test_recovery_commands_are_argv_and_do_not_capture_environment_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-that-must-not-be-recorded")

    details = effect_unknown_details(str(tmp_path), idempotency_key="key with spaces")

    assert isinstance(details["recovery_command"], list)
    assert details["recovery_command"][:2] == ["simplicio-py", "reconcile"]
    assert details["recovery_command"][details["recovery_command"].index("--idempotency-key") + 1] == (
        "key with spaces"
    )
    assert isinstance(details["receipt_locator"]["runtime_status_command"], list)
    assert "secret-that-must-not-be-recorded" not in json.dumps(details)


@pytest.mark.parametrize(
    ("runtime_result", "expected_code"),
    [
        (RuntimeError("offline"), "RUNTIME_RECONCILIATION_UNAVAILABLE"),
        (SimpleNamespace(returncode=1, stdout="not-json", stderr=""), "RUNTIME_RECONCILIATION_MALFORMED"),
        (SimpleNamespace(returncode=1, stdout="[]", stderr=""), "RUNTIME_RECONCILIATION_MALFORMED"),
        (
            _completed(
                {
                    "schema": "wrong",
                    "idempotency_key": KEY,
                    "fail_closed": True,
                    "durability": {"status": "durable", "verification": "verified_read_back"},
                },
                returncode=1,
            ),
            "RUNTIME_RECONCILIATION_MALFORMED",
        ),
        (
            _completed(
                {
                    "schema": "simplicio.effect-reconciliation/v1",
                    "idempotency_key": KEY,
                    "fail_closed": True,
                },
                returncode=1,
            ),
            "RUNTIME_RECONCILIATION_NOT_DURABLE",
        ),
        (
            _completed(
                _runtime_payload(
                    verdict="proven-after",
                    safe=True,
                    status="reconciled",
                    effect_state="proven",
                ),
                returncode=1,
            ),
            "RUNTIME_RECONCILIATION_NOT_SAFE_TO_CLEAR",
        ),
    ],
)
def test_runtime_failures_never_clear_the_causal_lock(
    tmp_path, monkeypatch, capsys, runtime_result, expected_code
):
    args = _record_lock(tmp_path)

    def fake_call(*_args, **_kwargs):
        if isinstance(runtime_result, Exception):
            raise runtime_result
        return runtime_result

    monkeypatch.setattr(reconcile_cmd, "call_simplicio", fake_call)

    assert reconcile_cmd.run(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "blocked"
    assert result["error"]["code"] == expected_code
    assert effect_unknown_pending(str(tmp_path)) is True


def test_key_repo_and_store_mismatches_fail_closed(tmp_path, monkeypatch, capsys):
    args = _record_lock(tmp_path)
    args.idempotency_key = "different-key"
    assert reconcile_cmd.run(args) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "EFFECT_UNKNOWN_LOCK_KEY_MISMATCH"

    args = _record_lock(tmp_path / "repo-mismatch")
    lock_path = Path(args.root) / ".simplicio" / "effect-unknown.lock"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["repo"] = str(tmp_path / "another-repo")
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    assert reconcile_cmd.run(args) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "EFFECT_UNKNOWN_LOCK_REPO_MISMATCH"

    args = _record_lock(tmp_path / "store-unavailable")
    monkeypatch.setattr(
        reconcile_cmd,
        "MapperStoreAdapter",
        lambda *_a, **_k: (_ for _ in ()).throw(reconcile_cmd.StoreAdapterError("unavailable")),
    )
    assert reconcile_cmd.run(args) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "RECONCILIATION_STORE_UNAVAILABLE"


def test_corrupt_or_unwritable_receipt_never_clears_pending(tmp_path, monkeypatch, capsys):
    args = _record_lock(tmp_path / "corrupt")
    payload = _runtime_payload(
        verdict="ambiguous-or-diverged",
        safe=False,
        status="unresolved",
        effect_state="applied-but-unproven",
    )
    monkeypatch.setattr(reconcile_cmd, "call_simplicio", lambda *_a, **_k: _completed(payload, returncode=1))
    assert reconcile_cmd.run(args) == 1
    first = json.loads(capsys.readouterr().out)
    receipt_path = Path(args.root) / first["durable_receipt"]["locator"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["receipt_sha256"] = "corrupt"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert reconcile_cmd.run(args) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "RECONCILIATION_RECEIPT_CORRUPT"

    args = _record_lock(tmp_path / "unwritable")
    monkeypatch.setattr(
        reconcile_cmd.MapperStoreAdapter,
        "write",
        lambda *_a, **_k: (_ for _ in ()).throw(reconcile_cmd.StoreAdapterError("write failed")),
    )
    assert reconcile_cmd.run(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "RECONCILIATION_RECEIPT_PERSISTENCE_FAILED"
    assert effect_unknown_pending(args.root) is True
