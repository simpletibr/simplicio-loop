"""Plugin v1 D02: partial edit/test reconcile with actionable UX."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simplicio.plugin_reconcile import (
    EVIDENCE_SCHEMA,
    FORBIDDEN_GIT,
    PluginReconcileError,
    clear_crash_marker,
    inspect_partial_attempt,
    resume_dry_run,
    write_crash_marker,
)
from simplicio.token_primitives import sha256_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plugin-dev-reconcile"


def _plan() -> dict:
    return json.loads((FIXTURES / "plan.json").read_text(encoding="utf-8"))


def test_crash_before_multi_op_is_not_applied(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"old-a\n")
    (tmp_path / "b.txt").write_bytes(b"old-b\n")
    evidence = inspect_partial_attempt(
        root=tmp_path,
        attempt_id="att-1",
        lease_id="lease-1",
        plan=_plan(),
        journal=[
            {"index": 0, "state": "not_applied", "before_sha256": sha256_text(b"old-a\n")},
            {"index": 1, "state": "not_applied", "before_sha256": sha256_text(b"old-b\n")},
        ],
        crash_before=True,
    )
    assert evidence["schema"] == EVIDENCE_SCHEMA
    assert evidence["recommended_action"] == "resume"
    assert evidence["reason_code"] == "NOT_APPLIED"
    assert [row["state"] for row in evidence["operations"]] == ["not_applied", "not_applied"]
    assert evidence["git_mutations"] == []


def test_crash_between_ops_resumes_remaining_only(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one\n")
    (tmp_path / "b.txt").write_bytes(b"old-b\n")
    before_a = sha256_text(b"old-a\n")
    after_a = sha256_text(b"one\n")
    before_b = sha256_text(b"old-b\n")
    evidence = inspect_partial_attempt(
        root=tmp_path,
        attempt_id="att-1",
        lease_id="lease-1",
        plan=_plan(),
        journal=[
            {
                "index": 0,
                "state": "applied",
                "before_sha256": before_a,
                "after_sha256": after_a,
            },
            {"index": 1, "state": "not_applied", "before_sha256": before_b},
        ],
    )
    assert evidence["recommended_action"] == "resume"
    assert evidence["applied_indexes"] == [0]
    assert len(evidence["remaining_operations"]) == 1
    assert evidence["remaining_operations"][0]["path"] == "b.txt"
    dry = resume_dry_run(evidence)
    assert dry["repeats_applied"] is False
    assert dry["operations"][0]["path"] == "b.txt"


def test_crash_after_all_ops_offers_rollback(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one\n")
    (tmp_path / "b.txt").write_bytes(b"two\n")
    evidence = inspect_partial_attempt(
        root=tmp_path,
        attempt_id="att-1",
        lease_id="lease-1",
        plan=_plan(),
        journal=[
            {
                "index": 0,
                "state": "applied",
                "before_sha256": sha256_text(b"old-a\n"),
                "after_sha256": sha256_text(b"one\n"),
            },
            {
                "index": 1,
                "state": "applied",
                "before_sha256": sha256_text(b"old-b\n"),
                "after_sha256": sha256_text(b"two\n"),
            },
        ],
    )
    assert evidence["recommended_action"] == "rollback"
    assert evidence["rollback_plan"]["safe"] is True
    assert evidence["rollback_plan"]["git_mutations"] == []


def test_user_edit_after_partial_blocks_resume(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"user-changed\n")
    (tmp_path / "b.txt").write_bytes(b"old-b\n")
    evidence = inspect_partial_attempt(
        root=tmp_path,
        attempt_id="att-1",
        lease_id="lease-1",
        plan=_plan(),
        journal=[
            {
                "index": 0,
                "state": "applied",
                "before_sha256": sha256_text(b"old-a\n"),
                "after_sha256": sha256_text(b"one\n"),
            },
            {"index": 1, "state": "not_applied", "before_sha256": sha256_text(b"old-b\n")},
        ],
    )
    assert evidence["user_changes_detected"] is True
    assert evidence["recommended_action"] == "no_retry"
    assert evidence["reason_code"] == "USER_MUTATION_DETECTED"
    with pytest.raises(PluginReconcileError, match="RESUME_UNSAFE|USER_MUTATION"):
        resume_dry_run(evidence)


def test_receipt_write_failure_after_source_change(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one\n")
    (tmp_path / "b.txt").write_bytes(b"old-b\n")
    evidence = inspect_partial_attempt(
        root=tmp_path,
        attempt_id="att-1",
        lease_id="lease-1",
        plan=_plan(),
        previous_receipt={"files": []},
        journal=[
            {
                "index": 0,
                "state": "applied",
                "before_sha256": sha256_text(b"old-a\n"),
                "after_sha256": sha256_text(b"one\n"),
            },
            {"index": 1, "state": "not_applied", "before_sha256": sha256_text(b"old-b\n")},
        ],
    )
    assert evidence["recommended_action"] == "resume"
    assert "b.txt" in evidence["residual_write_set"]


def test_test_started_timeout_killed_and_stale(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one\n")
    (tmp_path / "b.txt").write_bytes(b"two\n")
    plan = _plan()
    journal = [
        {
            "index": 0,
            "state": "applied",
            "before_sha256": sha256_text(b"old-a\n"),
            "after_sha256": sha256_text(b"one\n"),
        },
        {
            "index": 1,
            "state": "applied",
            "before_sha256": sha256_text(b"old-b\n"),
            "after_sha256": sha256_text(b"two\n"),
        },
    ]
    timeout = inspect_partial_attempt(
        root=tmp_path,
        attempt_id="att-1",
        lease_id="lease-1",
        plan=plan,
        journal=journal,
        tests={"status": "timeout", "commands": ["pytest"]},
    )
    assert timeout["reason_code"] == "TEST_TIMEOUT"
    assert timeout["validation_delta"]["unrun"] == ["pytest"]
    killed = inspect_partial_attempt(
        root=tmp_path,
        attempt_id="att-1",
        lease_id="lease-1",
        plan=plan,
        journal=journal,
        tests={"status": "killed", "commands": ["pytest"]},
    )
    assert killed["reason_code"] == "TEST_KILLED"
    stale = inspect_partial_attempt(
        root=tmp_path,
        attempt_id="att-1",
        lease_id="lease-1",
        plan=plan,
        journal=journal,
        tests={"status": "stale", "commands": ["pytest"]},
    )
    assert stale["reason_code"] == "TEST_STALE"
    assert stale["validation_delta"]["stale"] == ["pytest"]


def test_crash_marker_and_no_git_reset(tmp_path):
    marker = write_crash_marker(tmp_path, "att-1", {"phase": "between-ops"})
    assert marker.is_file()
    body = json.loads(marker.read_text(encoding="utf-8"))
    assert body["schema"] == "simplicio.plugin.dev-crash-marker/v1"
    source = Path("simplicio/plugin_reconcile.py").read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "git reset --hard" not in source
    assert all(name in source for name in FORBIDDEN_GIT)
    docs = Path("docs/plugin-reconcile.md").read_text(encoding="utf-8")
    assert "git reset" in docs
    assert "Do not run" in docs
    clear_crash_marker(tmp_path, "att-1")
    assert not marker.exists()


def test_system_fixture_killed_process_reconciles(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"one\n")
    (tmp_path / "b.txt").write_bytes(b"old-b\n")
    write_crash_marker(tmp_path, "killed-1", {"status": "killed", "phase": "between-ops"})
    evidence = inspect_partial_attempt(
        root=tmp_path,
        attempt_id="killed-1",
        lease_id="lease-1",
        plan=_plan(),
        journal=[
            {
                "index": 0,
                "state": "applied",
                "before_sha256": sha256_text(b"old-a\n"),
                "after_sha256": sha256_text(b"one\n"),
            },
            {"index": 1, "state": "not_applied", "before_sha256": sha256_text(b"old-b\n")},
        ],
        tests={"status": "killed", "commands": ["pytest -q"]},
    )
    assert evidence["recommended_action"] in {"resume", "inspect"}
    assert evidence["git_mutations"] == []
    assert "pytest -q" in evidence["validation_delta"]["unrun"]
    fixture = tmp_path / "killed-process-evidence.json"
    fixture.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    loaded = json.loads(fixture.read_text(encoding="utf-8"))
    assert loaded["schema"] == EVIDENCE_SCHEMA
