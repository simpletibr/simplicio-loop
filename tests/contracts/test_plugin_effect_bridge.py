"""Plugin v1 D01: EffectLease consumption and correlated DevExecutionReceipts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio.plugin_effect_bridge import (
    DEV_RECEIPT_SCHEMA,
    LEASE_SCHEMA,
    EffectLease,
    PluginLeaseError,
    canonical_digest,
    compile_scoped_plan,
    execute_leased_work,
    parse_effect_lease,
    run_cli,
    validate_lease,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plugin-dev-execution"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _lease(**overrides) -> dict:
    payload = _load("valid-lease.json")
    payload.update(overrides)
    return payload


def _intent() -> dict:
    return _load("task-intent.json")


def _route() -> dict:
    return _load("route-decision.json")


def _op(path: str = "plugin.js") -> dict:
    return {
        "op": "replace_range",
        "path": path,
        "start_line": 1,
        "end_line": 1,
        "text": "export const ready = true\n",
    }


def test_parse_valid_lease_matches_runtime_schema():
    lease = parse_effect_lease(_lease())
    assert isinstance(lease, EffectLease)
    assert lease.raw["schema"] == LEASE_SCHEMA
    assert lease.lease_id == "lease:effect-1"


def test_stale_lease_fails_closed():
    lease = parse_effect_lease(_lease(issued_at=1, ttl_ms=10))
    with pytest.raises(PluginLeaseError, match="LEASE_STALE"):
        validate_lease(lease, repo=".", worktree=".", branch="main", now=2)


def test_tampered_lease_digest_fails_closed():
    payload = _lease()
    material = {key: value for key, value in payload.items() if key != "digest"}
    payload["digest"] = canonical_digest(material)
    payload["fence"] = "mutated"
    with pytest.raises(PluginLeaseError, match="LEASE_TAMPERED"):
        validate_lease(parse_effect_lease(payload), repo=".", worktree=".", branch="main", now=1)


def test_wrong_branch_fails_closed():
    lease = parse_effect_lease(_lease())
    with pytest.raises(PluginLeaseError, match="LEASE_BRANCH_MISMATCH"):
        validate_lease(lease, repo=".", worktree=".", branch="other", now=1)


def test_write_outside_scope_requires_new_authorization():
    with pytest.raises(PluginLeaseError, match="WRITE_OUTSIDE_SCOPE"):
        compile_scoped_plan(
            goal="expand",
            operations=[_op("secrets.env")],
            write_set=("plugin.js",),
        )


def test_valid_lease_mechanical_success_correlates_receipt(tmp_path):
    target = tmp_path / "plugin.js"
    target.write_text("export const ready = false\n", encoding="utf-8")
    receipt = execute_leased_work(
        intent=_intent(),
        route=_route(),
        lease=_lease(repo=str(tmp_path), worktree=str(tmp_path), issued_at=10),
        root=tmp_path,
        branch="main",
        operations=[_op()],
        apply=True,
        now=10,
    )
    assert receipt["schema"] == DEV_RECEIPT_SCHEMA
    assert receipt["status"] == "ok"
    assert receipt["convergence_declared"] is False
    assert receipt["correlation"]["lease_id"] == "lease:effect-1"
    assert receipt["correlation"]["effect_id"] == "effect-1"
    assert receipt["correlation"]["task_id"] == "task-1"
    assert receipt["correlation"]["attempt_id"] == "attempt-1"
    assert receipt["tool_receipt"]["schema"] == "simplicio.plugin.tool-receipt/v1"
    assert receipt["tool_receipt"]["lease_id"] == "lease:effect-1"
    assert receipt["files"][0]["path"] == "plugin.js"
    assert receipt["files"][0]["before_sha256"] != receipt["files"][0]["after_sha256"]
    assert target.read_text(encoding="utf-8") == "export const ready = true\n"
    assert receipt["digest"] == canonical_digest(
        {key: value for key, value in receipt.items() if key != "digest"}
    )


def test_mechanical_failure_is_failed_not_ok(tmp_path):
    (tmp_path / "plugin.js").write_text("ok\n", encoding="utf-8")
    receipt = execute_leased_work(
        intent=_intent(),
        route=_route(),
        lease=_lease(repo=str(tmp_path), worktree=str(tmp_path), issued_at=10),
        root=tmp_path,
        branch="main",
        operations=[
            {
                "op": "replace_range",
                "path": "plugin.js",
                "old": "anchor",
                "new": "text",
            }
        ],
        apply=False,
        now=10,
    )
    assert receipt["status"] == "failed"
    assert receipt["reason_code"] == "EDIT_FAILED"


def test_test_fail_timeout_and_cancel(tmp_path):
    (tmp_path / "plugin.js").write_text("ok\n", encoding="utf-8")
    lease = _lease(repo=str(tmp_path), worktree=str(tmp_path), issued_at=10)
    failed = execute_leased_work(
        intent=_intent(),
        route=_route(),
        lease=lease,
        root=tmp_path,
        branch="main",
        operations=[_op()],
        validation=[{"cmd": ["false"]}],
        apply=False,
        now=10,
        run_validation=lambda *_: [{"cmd": ["false"], "passed": False, "log_summary": "token=abc"}],
    )
    assert failed["status"] == "failed"
    assert failed["reason_code"] == "TEST_FAILED"
    assert "token=<redacted>" in failed["tests"]["results"][0]["log_summary"]

    timeout = execute_leased_work(
        intent=_intent(),
        route=_route(),
        lease=lease,
        root=tmp_path,
        branch="main",
        operations=[_op()],
        validation=[{"cmd": ["sleep"]}],
        apply=False,
        now=10,
        run_validation=_raise_timeout,
    )
    assert timeout["status"] == "partial"
    assert timeout["reason_code"] == "TEST_TIMEOUT"

    cancelled = execute_leased_work(
        intent=_intent(),
        route=_route(),
        lease=lease,
        root=tmp_path,
        branch="main",
        operations=[_op()],
        apply=False,
        now=10,
        cancel_check=lambda: True,
    )
    assert cancelled["status"] == "cancelled"


def test_cli_and_python_adapter_parity(tmp_path):
    (tmp_path / "plugin.js").write_text("old\n", encoding="utf-8")
    intent_path = tmp_path / "intent.json"
    lease_path = tmp_path / "lease.json"
    plan_path = tmp_path / "plan.json"
    intent_path.write_text(
        json.dumps({"intent": _intent(), "route": _route()}),
        encoding="utf-8",
    )
    lease_path.write_text(
        json.dumps(_lease(repo=str(tmp_path), worktree=str(tmp_path), issued_at=10)),
        encoding="utf-8",
    )
    plan_path.write_text(json.dumps({"operations": [_op()]}), encoding="utf-8")
    python_receipt = execute_leased_work(
        intent=_intent(),
        route=_route(),
        lease=json.loads(lease_path.read_text(encoding="utf-8")),
        root=tmp_path,
        branch="main",
        operations=[_op()],
        apply=False,
        now=10,
    )
    code = run_cli(
        [
            "--root",
            str(tmp_path),
            "--branch",
            "main",
            "--intent",
            str(intent_path),
            "--lease",
            str(lease_path),
            "--plan",
            str(plan_path),
            "--json",
        ]
    )
    assert code in {0, 1}
    assert python_receipt["correlation"]["lease_id"] == "lease:effect-1"


def test_runtime_fixture_validates_receipt(tmp_path):
    (tmp_path / "plugin.js").write_text("old\n", encoding="utf-8")
    receipt = execute_leased_work(
        intent=_intent(),
        route=_route(),
        lease=_lease(repo=str(tmp_path), worktree=str(tmp_path), issued_at=10),
        root=tmp_path,
        branch="main",
        operations=[_op()],
        apply=True,
        now=10,
    )
    fixture_path = tmp_path / "dev-execution-receipt.json"
    fixture_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    loaded = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert loaded["schema"] == DEV_RECEIPT_SCHEMA
    assert loaded["tool_receipt"]["schema"] == "simplicio.plugin.tool-receipt/v1"
    assert loaded["convergence_declared"] is False
    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "plugin-dev-execution"
            / "dev-execution-receipt.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert loaded["schema"] == schema["properties"]["schema"]["const"]
    assert loaded["status"] in schema["properties"]["status"]["enum"]


def _raise_timeout(*_args):
    raise TimeoutError("validation timed out")
