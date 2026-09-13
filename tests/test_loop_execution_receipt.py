from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from simplicio_loop import loop_execution_receipt as receipt_mod
from simplicio_loop.delivery import build_delivery_receipt, write_delivery_receipt
from simplicio_loop.quality_matrix import build_quality_matrix_template
from simplicio_loop.stack_lock import StackComponent, StackLock


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    run = repo / ".simplicio" / "loop-runs" / "run-1"
    loop = run / "loop"
    loop.mkdir(parents=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_json(run / "manifest.json", {
        "run_id": "run-1", "repo": str(repo), "delivery_target": "verified",
    })
    lock = StackLock.create(
        (
            StackComponent("simplicio-mapper", "0.26.11", "mapper", "b" * 64, "a" * 64),
            StackComponent("simplicio-cli", "0.18.6", "dev-cli", "b" * 64, "a" * 64),
            StackComponent("simplicio-fast", "2.0.23", "fast", "b" * 64, "a" * 64),
            StackComponent("simplicio-runtime", "3.5.7", "runtime", "b" * 64, "a" * 64),
        ),
        "runtime-backed",
        run_id="run-1",
    )
    _write_json(run / "stack-lock.json", lock.to_dict())
    _write_json(run / "mapper-preflight.json", {
        "tool": "simplicio-mapper", "returncode": 0, "help_returncode": 0,
        "identity_ok": True, "version_ok": True, "version": "0.26.11",
        "missing_verbs": [],
    })
    _write_json(run / "operator-preflight.json", {
        "tool": "simplicio-dev-cli", "returncode": 0, "task_help_returncode": 0,
        "version_returncode": 0, "identity_ok": True, "version_ok": True,
        "version": "0.18.6", "missing_tokens": [], "missing_capabilities": [],
    })
    _write_json(run / "mapper-context.json", {
        "run_id": "run-1", "scan": {"returncode": 0},
        "inspect": {"returncode": 0}, "handoff": {"returncode": 0},
    })
    _write_json(run / "operator-receipt.json", {
        "schema": "simplicio.operator-receipt/v0", "mode": "execute",
        "tool": "simplicio-dev-cli", "run_id": "run-1", "returncode": 0,
        "execution_state": "applied", "target": "site/target", "measured_at": now,
        "source": "fixture", "repo_state_before": {"tree_hash": "tree"},
    })
    _write_json(run / "evidence-receipt.json", {
        "schema": "simplicio.evidence-receipt/v1", "run_id": "run-1",
        "status": "VERIFIED", "measured_at": now,
        "run": {"commit_sha": "a" * 40},
        "operator": {"execution_state": "applied", "receipt_path": str(run / "operator-receipt.json")},
        "criteria": [{"verification_state": "verified"}], "rules": [],
        "summary": {"criteria_total": 1, "criteria_verified": 1, "scenario_total": 1,
                     "scenario_verified": 1, "rule_total": 0, "rule_verified": 0},
    })
    delivery = build_delivery_receipt(
        str(run), "verified", current_state="verified", source_kind="local",
        source_payload={"evidence_receipt": str(run / "evidence-receipt.json"), "criteria_verified": 1},
    )
    write_delivery_receipt(str(run), delivery)
    quality = build_quality_matrix_template(run_id="run-1")
    for entry in quality["requirements"].values():
        entry.update({"status": "pass", "proof_ref": "fixture-proof"})
    quality["coverage"]["measured"] = 100.0
    _write_json(run / "quality-matrix.json", quality)
    _write_json(run / "oracle-matrix.json", {
        "schema": "simplicio.completion-oracle-matrix/v1", "parity": True,
        "adapters": [{"adapter": "fixture", "ready": True}],
        "signature": [True, "COMPLETE", "completion_verified", "MEASURED"],
    })
    _write_json(run / "state.json", {"run_id": "run-1", "phase": "done"})
    (loop / "scratchpad.md").write_text(
        "---\niteration: 1\nmax_iterations: 2\ncompletion_promise: null\n"
        "evidence_required: true\nmode: converge\nstarted_at: 2026-08-03T00:00:00Z\n---\ngoal\n",
        encoding="utf-8",
    )
    (loop / "journal.jsonl").write_text(
        '{"iteration":1,"action":"run","hypothesis":"works","gate":"pass",'
        '"fingerprint":"","note":"ok","ts":"2026-08-03T00:00:01Z"}\n',
        encoding="utf-8",
    )
    _write_json(loop / "anchor.json", {
        "item": "run-1", "goal": "works", "goal_fp": "abc", "frozen_at": "2026-08-03T00:00:00Z",
        "criteria": [{"id": "AC1", "text": "works", "status": "done"}],
    })
    _write_json(loop / "watcher_challenge.json", {
        "challenge": "nonce", "iteration": 1, "goal_fp": "abc", "written_at": now,
    })
    _write_json(loop / "watcher_state.json", {
        "match": True, "status": "MEASURED", "challenge": "nonce", "goal_fp": "abc",
        "checked_at": now,
    })
    return repo, run


def test_publish_creates_runtime_bound_snapshot(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    monkeypatch.setattr(receipt_mod, "_git_commit", lambda _repo: "a" * 40)

    result = receipt_mod.publish_loop_execution_receipt(
        repo=repo, run_dir=run, manifest={"run_id": "run-1"}
    )

    assert result["status"] == "VERIFIED"
    envelope = json.loads((repo / ".simplicio" / "loop-execution.json").read_text(encoding="utf-8"))
    assert envelope["chain"] == receipt_mod.CHAIN
    assert envelope["result"] == {"run_id": "run-1", "status": "VERIFIED", "verified": True}
    assert envelope["fast"]["version"] == "2.0.23"
    bundle = run / "runtime-loop-execution"
    for entry in envelope["artifacts"].values():
        copied = bundle / entry["path"]
        assert copied.is_file()
        assert entry["sha256"] == receipt_mod._sha256(copied)
        assert "source" not in entry
    assert json.loads((bundle / "mapper.json").read_text(encoding="utf-8"))["run_id"] == "run-1"
    assert json.loads((bundle / "dev-cli.json").read_text(encoding="utf-8"))["returncode"] == 0


def test_publish_skips_non_git_legacy_fixture(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    monkeypatch.setattr(
        receipt_mod,
        "_git_commit",
        lambda _repo: (_ for _ in ()).throw(receipt_mod.LoopExecutionReceiptError("not a git repo")),
    )

    result = receipt_mod.publish_loop_execution_receipt(
        repo=repo, run_dir=run, manifest={"run_id": "run-1"}
    )

    assert result == {
        "status": "SKIPPED",
        "reason": "repository_not_git",
        "detail": "not a git repo",
    }
    assert not (repo / ".simplicio" / "loop-execution.json").exists()


def test_publish_rejects_missing_state_artifact(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    (run / "loop" / "watcher_state.json").unlink()
    monkeypatch.setattr(receipt_mod, "_git_commit", lambda _repo: "a" * 40)

    with pytest.raises(receipt_mod.LoopExecutionReceiptError, match="watcher_state.json"):
        receipt_mod.publish_loop_execution_receipt(
            repo=repo, run_dir=run, manifest={"run_id": "run-1"}
        )


def test_publish_rejects_manifest_run_id_mismatch(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    monkeypatch.setattr(receipt_mod, "_git_commit", lambda _repo: "a" * 40)

    with pytest.raises(receipt_mod.LoopExecutionReceiptError, match="does not match"):
        receipt_mod.publish_loop_execution_receipt(
            repo=repo, run_dir=run, manifest={"run_id": "other-run"}
        )


def test_publish_rejects_run_directory_outside_workspace(tmp_path):
    repo = tmp_path / "repo"
    run = tmp_path / "outside" / "run-1"
    repo.mkdir()

    with pytest.raises(receipt_mod.LoopExecutionReceiptError, match="escapes"):
        receipt_mod.publish_loop_execution_receipt(
            repo=repo, run_dir=run, manifest={"run_id": "run-1"}
        )


def test_publish_rejects_symlinked_source_artifact(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    outside = tmp_path / "outside-watcher-state.json"
    outside.write_text("{}", encoding="utf-8")
    target = run / "loop" / "watcher_state.json"
    target.unlink()
    try:
        os.symlink(outside, target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    monkeypatch.setattr(receipt_mod, "_git_commit", lambda _repo: "a" * 40)

    with pytest.raises(receipt_mod.LoopExecutionReceiptError, match="escapes|symlink"):
        receipt_mod.publish_loop_execution_receipt(
            repo=repo, run_dir=run, manifest={"run_id": "run-1"}
        )


def test_publish_rejects_fallback_component(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    stack_lock = json.loads((run / "stack-lock.json").read_text(encoding="utf-8"))
    stack_lock["components"][0]["fallback"] = True
    _write_json(run / "stack-lock.json", stack_lock)
    monkeypatch.setattr(receipt_mod, "_git_commit", lambda _repo: "a" * 40)

    with pytest.raises(receipt_mod.LoopExecutionReceiptError, match="fallback"):
        receipt_mod.publish_loop_execution_receipt(
            repo=repo, run_dir=run, manifest={"run_id": "run-1"}
        )


def test_publish_allows_missing_optional_runtime_in_standalone_profile(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    stack_lock = StackLock.create(
        (
            StackComponent("simplicio-mapper", "0.26.11", "mapper", "b" * 64, "a" * 64),
            StackComponent("simplicio-cli", "0.18.6", "dev-cli", "b" * 64, "a" * 64),
            StackComponent("simplicio-fast", "2.0.23", "fast", "b" * 64, "a" * 64),
            StackComponent("simplicio-runtime", "", "", "", "", available=False),
        ),
        "standalone",
        run_id="run-1",
    ).to_dict()
    _write_json(run / "stack-lock.json", stack_lock)
    monkeypatch.setattr(receipt_mod, "_git_commit", lambda _repo: "a" * 40)

    result = receipt_mod.publish_loop_execution_receipt(
        repo=repo, run_dir=run, manifest={"run_id": "run-1"}
    )

    assert result["status"] == "VERIFIED"
    envelope = json.loads((repo / ".simplicio" / "loop-execution.json").read_text(encoding="utf-8"))
    assert envelope["runtime"] == {
        "version": "unavailable",
        "origin": "installed",
        "fallback": False,
        "build_sha": "",
        "available": False,
        "required": False,
        "optional": True,
    }


def test_publish_rejects_existing_bundle_without_overwrite(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    (run / "runtime-loop-execution").mkdir()
    (run / "runtime-loop-execution" / "sentinel").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(receipt_mod, "_git_commit", lambda _repo: "a" * 40)

    with pytest.raises(receipt_mod.LoopExecutionReceiptError, match="already exists"):
        receipt_mod.publish_loop_execution_receipt(
            repo=repo, run_dir=run, manifest={"run_id": "run-1"}
        )
    assert (run / "runtime-loop-execution" / "sentinel").read_text(encoding="utf-8") == "keep"


def test_publish_removes_partial_bundle_when_root_write_fails(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    monkeypatch.setattr(receipt_mod, "_git_commit", lambda _repo: "a" * 40)
    monkeypatch.setattr(
        receipt_mod,
        "_atomic_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            receipt_mod.LoopExecutionReceiptError("root write failed")
        ),
    )

    with pytest.raises(receipt_mod.LoopExecutionReceiptError, match="root write failed"):
        receipt_mod.publish_loop_execution_receipt(
            repo=repo, run_dir=run, manifest={"run_id": "run-1"}
        )
    assert not (run / "runtime-loop-execution").exists()


def test_receipt_schema_declares_stable_runtime_chain():
    schema_path = Path(__file__).parents[1] / "contracts" / "loop-execution" / "v1" / "receipt.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["schema"]["const"] == receipt_mod.SCHEMA
    assert schema["properties"]["chain"]["const"] == receipt_mod.CHAIN


def test_publish_rejects_unverified_durable_evidence(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    monkeypatch.setattr(receipt_mod, "_git_commit", lambda _repo: "a" * 40)
    _write_json(run / "evidence-receipt.json", {
        "schema": "simplicio.evidence-receipt/v1",
        "run_id": "run-1",
        "status": "UNVERIFIED",
    })

    with pytest.raises(receipt_mod.LoopExecutionReceiptError, match="evidence"):
        receipt_mod.publish_loop_execution_receipt(
            repo=repo, run_dir=run, manifest={"run_id": "run-1"}
        )


def test_publish_rejects_missing_oracle_artifact(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    monkeypatch.setattr(receipt_mod, "_git_commit", lambda _repo: "a" * 40)
    (run / "oracle-matrix.json").unlink()

    with pytest.raises(receipt_mod.LoopExecutionReceiptError, match="oracle"):
        receipt_mod.publish_loop_execution_receipt(
            repo=repo, run_dir=run, manifest={"run_id": "run-1"}
        )


@pytest.mark.parametrize("status", ["blocked", "partial", "error"])
def test_flow_publication_never_publishes_nonterminal_status(tmp_path, monkeypatch, status):
    repo, run = _fixture(tmp_path)
    published = []
    monkeypatch.setattr(
        receipt_mod,
        "publish_loop_execution_receipt",
        lambda **kwargs: published.append(kwargs),
    )

    result = receipt_mod.publish_loop_execution_for_flow(
        repo=repo, run_dir=run, flow="batch", flow_result={"status": status}
    )

    assert result["schema"] == receipt_mod.SCHEMA
    assert result["status"] in {"BLOCKED", "PARTIAL", "ERROR"}
    assert result["status"] != "COMPLETE"
    assert result["verified"] is False
    assert published == []


def test_flow_publication_calls_the_v1_publisher_once_for_terminal_status(tmp_path, monkeypatch):
    repo, run = _fixture(tmp_path)
    published = []

    def fake_publish(**kwargs):
        published.append(kwargs)
        return {"status": "VERIFIED", "receipt": str(repo / ".simplicio" / "loop-execution.json")}

    monkeypatch.setattr(receipt_mod, "publish_loop_execution_receipt", fake_publish)
    result = receipt_mod.publish_loop_execution_for_flow(
        repo=repo, run_dir=run, flow="tick", flow_result={"status": "completed"}
    )

    assert result["schema"] == receipt_mod.SCHEMA
    assert result["status"] == "VERIFIED"
    assert result["verified"] is True
    assert len(published) == 1
    assert published[0]["repo"] == repo
    assert published[0]["run_dir"] == run
