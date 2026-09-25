from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop.fast_integration import (
    FAST_CHANGESET_SCHEMA,
    FastConfig,
    FastLoopIntegration,
    FastStaleChangeset,
    validate_changeset,
)


class FakeFast:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[list[str]] = []

    def __call__(self, command, **kwargs):
        command = list(command)
        self.calls.append(command)
        args = command[1:]
        if args == ["--version"]:
            return subprocess.CompletedProcess(command, 0, "simplicio-fast 2.0.14\n", "")
        if args == ["doctor", "--json"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"integrated_ready": True}), "")
        if command[0] == "git":
            return subprocess.CompletedProcess(command, 0, "abc123\n", "")
        if command[0] == "simplicio-mapper" and args and args[0] == "handoff":
            envelope = {
                "schema": "simplicio.map-handoff/v1",
                "ready": True,
                "context_pack": {},
                "targets": [],
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(envelope), "")
        if args and args[0] == "ingest":
            output = Path(args[args.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"snapshot")
            return subprocess.CompletedProcess(command, 0, json.dumps({"schema": "simplicio.fast.ingest/v2", "generation": "g1", "metrics": {}}), "")
        if args and args[0] == "understand":
            return subprocess.CompletedProcess(command, 0, json.dumps({"schema": "simplicio.fast.understanding/v2", "context": [{"file": "app.py", "content": "x"}]}), "")
        if args and args[0] == "plan":
            return subprocess.CompletedProcess(command, 0, json.dumps({"schema": "simplicio.fast.plandag/v2", "nodes": []}), "")
        if args and args[0] == "refresh":
            return subprocess.CompletedProcess(command, 0, json.dumps({"schema": "simplicio.fast.ingest/v2", "generation": "g2", "metrics": {}}), "")
        if args and args[0] == "rollout":
            return subprocess.CompletedProcess(
                command, 0,
                json.dumps({"schema": "simplicio.fast.rollout-receipt/v1", "status": "accepted", "mode": args[1]}),
                "",
            )
        if args and args[0] == "apply":
            return subprocess.CompletedProcess(command, 0, json.dumps({"schema": "simplicio.fast.apply-receipt/v2", "outcome": "applied"}), "")
        raise AssertionError(command)


def test_prepare_ingests_once_and_pins_receipts(tmp_path: Path) -> None:
    fake = FakeFast(tmp_path)
    config = FastConfig(command=("fast",), snapshot=".fast/project.sfast", state=".fast/state.json")
    integration = FastLoopIntegration(tmp_path, config=config, runner=fake)
    first = integration.prepare("change app")
    second = integration.prepare("change app")
    assert first["status"] == "READY"
    assert first["generation"] == "g1"
    assert first["ingest"]["source_commit"] == "abc123"
    assert first["context_hash"].startswith("sha256:")
    assert first["plan"]["loop_receipt"]["plan_hash"].startswith("sha256:")
    assert first["plan_hash"] == first["plan"]["plan_hash"]
    assert first["plan_hash"] == first["loop_receipt"]["plan_hash"]
    assert first["loop_receipt"]["stage"] == "prepare"
    assert first["loop_receipt"]["receipt_hash"].startswith("sha256:")
    assert second["generation"] == first["generation"]
    assert second["plan_hash"] == first["plan_hash"]
    assert second["loop_receipt"] == first["loop_receipt"]
    assert sum(call[1] == "ingest" for call in fake.calls) == 1
    assert [call[1] for call in fake.calls].count("understand") == 4
    assert [call[1] for call in fake.calls].count("plan") == 2
    ingest_call = next(call for call in fake.calls if call[1] == "ingest")
    assert "--mapper-mode" in ingest_call and "integrated" in ingest_call
    assert "--mapper-handoff" in ingest_call
    # issue #1288: ingest must obtain and pass a real Mapper handoff, not skip it.
    assert any(call[0] == "simplicio-mapper" and call[1] == "handoff" for call in fake.calls)


def test_ingest_falls_back_with_distinct_reason_when_mapper_handoff_is_missing(tmp_path: Path) -> None:
    """issue #1288: a missing/failed Mapper handoff must not be reported as
    ``fast_disabled_or_unavailable`` — Fast itself is ready, only the handoff
    step failed, and the fallback reason must say so distinctly."""

    def runner(command, **kwargs):
        command = list(command)
        args = command[1:]
        if args == ["--version"]:
            return subprocess.CompletedProcess(command, 0, "simplicio-fast 2.0.14\n", "")
        if args == ["doctor", "--json"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"integrated_ready": True}), "")
        if command[0] == "git":
            return subprocess.CompletedProcess(command, 0, "abc123\n", "")
        if command[0] == "simplicio-mapper" and args and args[0] == "handoff":
            return subprocess.CompletedProcess(command, 1, "", "mapper crashed")
        raise AssertionError(command)

    config = FastConfig(command=("fast",), snapshot=".fast/project.sfast", state=".fast/state.json")
    integration = FastLoopIntegration(tmp_path, config=config, runner=runner)
    result = integration.ingest()
    assert result["fallback"] is True
    assert result["reason"] != "fast_disabled_or_unavailable"
    assert "mapper_handoff_unavailable" in result["reason"]
    assert result["probe"]["integrated_ready"] is True


def _handoff_runner(ready_after_scan: bool):
    calls: list[list[str]] = []
    scanned = {"done": False}

    def runner(command, **kwargs):
        command = list(command)
        calls.append(command)
        args = command[1:]
        if args == ["--version"]:
            return subprocess.CompletedProcess(command, 0, "simplicio-fast 2.0.14\n", "")
        if args == ["doctor", "--json"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"integrated_ready": True}), "")
        if command[0] == "git":
            return subprocess.CompletedProcess(command, 0, "abc123\n", "")
        if command[0] == "simplicio-mapper" and args[0] == "scan":
            scanned["done"] = True
            return subprocess.CompletedProcess(command, 0, json.dumps({"phase": "complete"}), "")
        if command[0] == "simplicio-mapper" and args[0] == "handoff":
            ready = scanned["done"] and ready_after_scan
            envelope = {
                "schema": "simplicio.map-handoff/v1",
                "ready": ready,
                "reason": "" if ready else "artifacts_not_fresh",
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(envelope), "")
        if args and args[0] == "ingest":
            output = Path(args[args.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"snapshot")
            return subprocess.CompletedProcess(command, 0, json.dumps({"schema": "simplicio.fast.ingest/v2", "generation": "g1", "metrics": {}}), "")
        raise AssertionError(command)

    return runner, calls


def test_ingest_refreshes_stale_mapper_artifacts_before_handoff(tmp_path: Path) -> None:
    """A stale Mapper map must be refreshed (scan --sync) and the handoff retried,
    so `orient` works on a repo that was never scanned instead of falling back."""
    runner, calls = _handoff_runner(ready_after_scan=True)
    config = FastConfig(command=("fast",), snapshot=".fast/project.sfast", state=".fast/state.json")
    result = FastLoopIntegration(tmp_path, config=config, runner=runner).ingest()
    assert result.get("fallback") is not True, result
    scan = [c for c in calls if c[0] == "simplicio-mapper" and c[1] == "scan"]
    assert scan and "--sync" in scan[0]
    handoffs = [c for c in calls if c[0] == "simplicio-mapper" and c[1] == "handoff"]
    assert len(handoffs) == 2


def test_ingest_requests_full_unscoped_mapper_handoff(tmp_path: Path) -> None:
    """Fast indexes the whole repo, so the ingest handoff must not be task-scoped:
    a --goal handoff prunes the context snapshot to a small file-only prefix (no
    symbol nodes) and Fast then fails with mapper_id_missing."""
    fake = FakeFast(tmp_path)
    config = FastConfig(command=("fast",), snapshot=".fast/project.sfast", state=".fast/state.json")
    FastLoopIntegration(tmp_path, config=config, runner=fake).prepare("change app")
    handoff = next(c for c in fake.calls if c[0] == "simplicio-mapper" and c[1] == "handoff")
    assert "--goal" not in handoff
    assert int(handoff[handoff.index("--token-budget") + 1]) >= 1_000_000


def test_ingest_reports_not_ready_when_scan_does_not_help(tmp_path: Path) -> None:
    runner, calls = _handoff_runner(ready_after_scan=False)
    config = FastConfig(command=("fast",), snapshot=".fast/project.sfast", state=".fast/state.json")
    result = FastLoopIntegration(tmp_path, config=config, runner=runner).ingest()
    assert result["fallback"] is True
    assert "mapper_handoff_not_ready: artifacts_not_fresh" in result["reason"]
    assert len([c for c in calls if c[0] == "simplicio-mapper" and c[1] == "scan"]) == 1


def test_stale_candidate_and_loser_are_fail_closed(tmp_path: Path) -> None:
    candidate = {
        "schema": FAST_CHANGESET_SCHEMA,
        "changes": [{"path": "app.py", "expected_sha256": "a" * 64, "replacements": [{"start_line": 1, "end_line": 1, "content": "x"}]}],
        "generation": "old",
        "context_hash": "ctx",
    }
    with pytest.raises(FastStaleChangeset):
        validate_changeset(candidate, generation="new", context_hash="ctx")
    integration = FastLoopIntegration(tmp_path, config=FastConfig(mode="standalone"))
    receipt = integration.apply(candidate, winner=False)
    assert receipt["status"] == "SKIPPED"
    assert receipt["applied"] is False


def test_fallback_is_visible_and_configurable(tmp_path: Path) -> None:
    integration = FastLoopIntegration(tmp_path, config=FastConfig(mode="standalone"))
    receipt = integration.prepare("change app")
    assert receipt["status"] == "FALLBACK"
    assert receipt["ingest"]["fallback"] is True
    assert receipt["ingest"]["fallback_mode"] == "mapper-dev-cli"
    required = FastLoopIntegration(tmp_path, config=FastConfig(mode="required"), runner=lambda *a, **k: (_ for _ in ()).throw(OSError("missing")))
    with pytest.raises(Exception):
        required.probe()


def test_explicit_rust_requires_doctor_selection(tmp_path: Path) -> None:
    fake = FakeFast(tmp_path)
    integration = FastLoopIntegration(
        tmp_path, config=FastConfig(command=("fast",), engine="rust"), runner=fake
    )
    probe = integration.probe()
    assert probe["integrated_ready"] is False
    assert probe["reason"] == "rust_not_verified"
    assert probe["requested_engine"] == "rust"


def test_explicit_python_is_reported_without_loading_rust(tmp_path: Path) -> None:
    fake = FakeFast(tmp_path)
    integration = FastLoopIntegration(
        tmp_path, config=FastConfig(command=("fast",), engine="python"), runner=fake
    )
    probe = integration.probe()
    assert probe["integrated_ready"] is True
    assert probe["selected_engine"] == "python"


def test_real_fast_prepare_on_small_repository(tmp_path: Path) -> None:
    command = (sys.executable, "-m", "simplicio_fast.cli")
    try:
        version = subprocess.run([*command, "--version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("simplicio-fast is unavailable")
    if version.returncode != 0:
        pytest.skip("simplicio-fast is unavailable")
    (tmp_path / "app.py").write_text("class App:\n    pass\n", encoding="utf-8")
    integration = FastLoopIntegration(tmp_path, config=FastConfig(command=command, timeout_seconds=60))
    result = integration.prepare("change App")
    assert result["status"] in {"READY", "FALLBACK"}
    if result["status"] == "READY":
        assert result["plan"]["schema"] == "simplicio.fast.plandag/v2"
        assert result["generation"]

def test_apply_runtime_gate_and_incremental_refresh(tmp_path: Path) -> None:
    fake = FakeFast(tmp_path)
    runtime_calls: list[dict[str, object]] = []

    def runtime_apply(operation):
        runtime_calls.append(dict(operation))
        return {"status": "APPLIED", "receipt": "runtime-1"}

    integration = FastLoopIntegration(
        tmp_path, config=FastConfig(command=("fast",), snapshot=".fast/project.sfast", state=".fast/state.json"),
        runtime_apply=runtime_apply,
        runner=fake,
    )
    prepared = integration.prepare("change app")
    candidate = {
        "schema": FAST_CHANGESET_SCHEMA,
        "changes": [{"path": "app.py", "expected_sha256": "a" * 64, "replacements": []}],
        "generation": prepared["generation"],
        "context_hash": prepared["context_hash"],
    }
    applied = integration.apply(candidate)
    assert applied["status"] == "READY"
    assert applied["applied"] is True
    assert applied["runtime"]["status"] == "APPLIED"
    assert runtime_calls[0]["generation"] == prepared["generation"]
    refreshed = integration.refresh()
    assert refreshed["status"] == "MEASURED"
    assert refreshed["no_full_remap"] is True
    assert refreshed["generation"] == "g2"


def test_rollout_transition_is_delegated_to_fast(tmp_path: Path) -> None:
    fake = FakeFast(tmp_path)
    integration = FastLoopIntegration(
        tmp_path, config=FastConfig(command=("fast",), snapshot=".fast/project.sfast", state=".fast/state.json"),
        runner=fake,
    )
    receipt = integration.rollout("canary", generation="g1", reason="bounded-test")
    assert receipt["schema"] == "simplicio.fast.rollout-receipt/v1"
    assert receipt["mode"] == "canary"
    assert [call[1] for call in fake.calls].count("rollout") == 1

def test_read_only_qdot_i8_orientation_blocks_mutable_plan_and_redacts_nodes(
    tmp_path: Path,
) -> None:
    class PolicyFast(FakeFast):
        def __call__(self, command, **kwargs):
            args = list(command[1:])
            if args and args[0] == "understand":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {
                            "schema": "simplicio.fast.understanding/v2",
                            "context": [{"file": "runtime/src/other.rs"}],
                            "files": ["runtime/src/other.rs"],
                        }
                    ),
                    "",
                )
            if args and args[0] == "plan":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {
                            "schema": "simplicio.fast.plandag/v2",
                            "nodes": [
                                {"id": "orient", "kind": "context"},
                                {
                                    "id": "modify",
                                    "kind": "structured_patch",
                                    "inputs": {
                                        "format": FAST_CHANGESET_SCHEMA,
                                        "allowed_files": ["runtime/src/other.rs"],
                                    },
                                },
                                {
                                    "id": "validate",
                                    "kind": "command",
                                    "depends_on": ["modify"],
                                },
                                {
                                    "id": "refresh",
                                    "kind": "refresh",
                                    "depends_on": ["validate"],
                                },
                            ],
                        }
                    ),
                    "",
                )
            return super().__call__(command, **kwargs)

    (tmp_path / "benchmarks").mkdir()
    target = tmp_path / "crates" / "tesser_std" / "src" / "test" / "bench.rs"
    target.parent.mkdir(parents=True)
    target.write_text("fn QuantizedI8() {}\n", encoding="utf-8")
    task = (
        "Read-only orientation, sem editar arquivos: qdot_i8 is missing while QuantizedI8 is positive. "
        "Use explicit targets benchmarks/ and crates/tesser_std/src/test/bench.rs; do not modify source files."
    )
    integration = FastLoopIntegration(
        tmp_path,
        config=FastConfig(command=("fast",), mode="required"),
        runner=PolicyFast(tmp_path),
    )
    result = integration.prepare(task)
    repeated = integration.prepare(task)

    reasons = {item["reason"] for item in result["blocked_preconditions"]}
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "READ_ONLY_MUTATION_AUTHORITY"
    assert {"READ_ONLY_MUTATION_AUTHORITY", "TARGET_CORRIDOR_MISMATCH"} <= reasons
    assert result["intent_policy"]["schema"] == "simplicio.loop-fast-intent-policy/v1"
    assert result["intent_policy"]["mutable_authority"] is False
    assert result["plan"]["status"] == "BLOCKED"
    assert [node["id"] for node in result["plan"]["nodes"]] == ["orient"]
    assert result["plan"]["redacted_node_ids"] == ["modify", "refresh", "validate"]
    assert result["plan_hash"] == result["plan"]["plan_hash"]
    assert result["plan_hash"] == result["plan"]["loop_receipt"]["plan_hash"]
    assert result["loop_receipt"]["stage"] == "prepare"
    assert repeated["plan_hash"] == result["plan_hash"]
    assert repeated["loop_receipt"] == result["loop_receipt"]
    assert "structured_patch" not in json.dumps(result["plan"])


def test_plan_policy_rejects_unresolved_targets_and_missing_mutation_policy(tmp_path):
    from simplicio_loop.fast_integration import FAST_PLAN_SCHEMA, _validate_plan_policy

    policy, blockers = _validate_plan_policy(
        tmp_path,
        "update missing/path.py",
        {"context": [], "files": []},
        {
            "schema": FAST_PLAN_SCHEMA,
            "nodes": [{"id": "modify", "kind": "structured_patch", "inputs": {}}],
        },
    )

    reasons = {item["reason"] for item in blockers}
    assert policy["validated"] is False
    assert {
        "MUTATION_POLICY_MISSING",
        "TARGET_PATH_UNRESOLVED",
        "TARGET_CORRIDOR_MISSING",
    } <= reasons


def test_plan_policy_rejects_wrong_format_and_zero_context(tmp_path):
    from simplicio_loop.fast_integration import (
        FAST_CHANGESET_SCHEMA,
        FAST_PLAN_SCHEMA,
        _validate_plan_policy,
    )

    policy, blockers = _validate_plan_policy(
        tmp_path,
        "update app",
        {"context": [], "files": []},
        {
            "schema": FAST_PLAN_SCHEMA,
            "nodes": [
                {
                    "id": "modify",
                    "kind": "structured_patch",
                    "inputs": {
                        "format": "wrong",
                        "allowed_files": ["app.py"],
                    },
                }
            ],
        },
    )

    reasons = {item["reason"] for item in blockers}
    assert policy["validated"] is False
    assert "MUTATION_POLICY_MISSING" in reasons
    assert "CONTEXT_RELEVANCE_INSUFFICIENT" in reasons
    assert FAST_CHANGESET_SCHEMA != "wrong"


def test_explicit_target_with_zero_context_cannot_authorize_mutation(tmp_path):
    from simplicio_loop.fast_integration import FAST_PLAN_SCHEMA, _validate_plan_policy

    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("pass\n", encoding="utf-8")
    policy, blockers = _validate_plan_policy(
        tmp_path,
        "update src/app.py",
        {"context": [], "files": []},
        {
            "schema": FAST_PLAN_SCHEMA,
            "nodes": [
                {
                    "id": "modify",
                    "kind": "structured_patch",
                    "inputs": {
                        "format": FAST_CHANGESET_SCHEMA,
                        "allowed_files": ["src/app.py"],
                    },
                }
            ],
        },
    )

    assert policy["validated"] is False
    assert policy["context_path_count"] == 0
    assert "TARGET_RELEVANCE_INSUFFICIENT" in {
        item["reason"] for item in blockers
    }


def test_plan_policy_rejects_paths_outside_repository(tmp_path):
    from simplicio_loop.fast_integration import FAST_PLAN_SCHEMA, _validate_plan_policy

    policy, blockers = _validate_plan_policy(
        tmp_path,
        "update ../outside.py",
        {"context": [{"file": "src/app.py"}]},
        {
            "schema": FAST_PLAN_SCHEMA,
            "nodes": [
                {
                    "id": "modify",
                    "kind": "structured_patch",
                    "inputs": {
                        "format": FAST_CHANGESET_SCHEMA,
                        "allowed_files": ["../outside.py"],
                    },
                }
            ],
        },
    )

    reasons = {item["reason"] for item in blockers}
    assert policy["validated"] is False
    assert "TARGET_PATH_INVALID" in reasons
    assert "MUTATION_TARGET_INVALID" in reasons


def test_every_fast_mapper_command_receives_the_handoff(tmp_path: Path) -> None:
    """Fast's understand/plan/refresh fail closed (mapper_missing) in integrated
    mode without --mapper-handoff, exactly like ingest."""
    fake = FakeFast(tmp_path)
    config = FastConfig(command=("fast",), snapshot=".fast/project.sfast", state=".fast/state.json")
    integration = FastLoopIntegration(tmp_path, config=config, runner=fake)
    integration.prepare("change app")
    integration.refresh()
    for call in fake.calls:
        if call[0] == "fast" and call[1] in {"ingest", "understand", "plan", "refresh"}:
            assert call[call.index("--mapper-mode") + 1] == "integrated", call
            assert Path(call[call.index("--mapper-handoff") + 1]).is_file(), call


def _mutation_plan(allowed):
    from simplicio_loop.fast_integration import FAST_CHANGESET_SCHEMA, FAST_PLAN_SCHEMA

    return {"schema": FAST_PLAN_SCHEMA, "nodes": [{
        "id": "modify", "kind": "structured_patch",
        "inputs": {"format": FAST_CHANGESET_SCHEMA, "allowed_files": allowed}}]}


def test_mapper_inferred_targets_are_advisory_not_a_corridor(tmp_path, monkeypatch):
    """Without a path in the task or --target, the corridor is only Mapper's guess;
    Fast choosing a related file (its test) must not block orientation."""
    from simplicio_loop import fast_integration as fi

    for name in ("app.py", "test_app.py"):
        (tmp_path / name).write_text("x = 1\n")
    monkeypatch.setattr(fi, "mapper_selected_targets", lambda root: ["app.py"])
    understanding = {"context": [{"file": "app.py"}, {"file": "test_app.py"}], "files": ["app.py", "test_app.py"]}
    policy, blockers = fi._validate_plan_policy(tmp_path, "tidy the app", understanding,
                                                _mutation_plan(["app.py", "test_app.py"]))
    assert "TARGET_CORRIDOR_MISMATCH" not in {b["reason"] for b in blockers}
    assert policy["corridor_source"] == "mapper_selected"


def test_explicit_target_corridor_still_blocks(tmp_path, monkeypatch):
    from simplicio_loop import fast_integration as fi

    for name in ("app.py", "test_app.py"):
        (tmp_path / name).write_text("x = 1\n")
    understanding = {"context": [{"file": "app.py"}], "files": ["app.py", "test_app.py"]}
    policy, blockers = fi._validate_plan_policy(tmp_path, "tidy app.py", understanding,
                                                _mutation_plan(["app.py", "test_app.py"]))
    assert "TARGET_CORRIDOR_MISMATCH" in {b["reason"] for b in blockers}
    assert policy["corridor_source"] == "explicit"


def test_stale_but_ready_handoff_is_rescanned(tmp_path):
    """Mapper can answer ready=True over a dirty tree (status.fresh=False); Fast then
    rejects the stale digests. A stale map is refreshed before ingest."""
    calls = []
    scanned = {"done": False}

    def runner(command, **kwargs):
        command = list(command)
        calls.append(command)
        args = command[1:]
        if args == ["--version"]:
            return subprocess.CompletedProcess(command, 0, "simplicio-fast 2.0.14\n", "")
        if args == ["doctor", "--json"]:
            return subprocess.CompletedProcess(command, 0, json.dumps({"integrated_ready": True}), "")
        if command[0] == "git":
            return subprocess.CompletedProcess(command, 0, "abc123\n", "")
        if command[0] == "simplicio-mapper" and args[0] == "scan":
            scanned["done"] = True
            return subprocess.CompletedProcess(command, 0, "{}", "")
        if command[0] == "simplicio-mapper" and args[0] == "handoff":
            envelope = {"schema": "simplicio.map-handoff/v1", "ready": True,
                        "status": {"fresh": scanned["done"]}}
            return subprocess.CompletedProcess(command, 0, json.dumps(envelope), "")
        if args and args[0] == "ingest":
            output = Path(args[args.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"snapshot")
            return subprocess.CompletedProcess(command, 0, json.dumps({"schema": "simplicio.fast.ingest/v2", "generation": "g1", "metrics": {}}), "")
        raise AssertionError(command)

    config = FastConfig(command=("fast",), snapshot=".fast/project.sfast", state=".fast/state.json")
    result = FastLoopIntegration(tmp_path, config=config, runner=runner).ingest()
    assert result.get("fallback") is not True, result
    assert scanned["done"] is True


def test_bare_word_matches_are_not_an_authority_corridor(tmp_path):
    from simplicio_loop import fast_integration as fi

    (tmp_path / "economy.py").write_text("x = 1\n")
    (tmp_path / "test_economy.py").write_text("x = 1\n")
    understanding = {"context": [{"file": "economy.py"}], "files": ["economy.py", "test_economy.py"]}
    policy, blockers = fi._validate_plan_policy(tmp_path, "fix economy persistence", understanding,
                                                _mutation_plan(["economy.py", "test_economy.py"]))
    assert policy["corridor_source"] == "mapper_selected"
    assert "TARGET_CORRIDOR_MISMATCH" not in {b["reason"] for b in blockers}


def test_ingest_cache_is_invalidated_by_uncommitted_edits(tmp_path):
    """Same HEAD but edited files: the cached snapshot no longer matches the Mapper
    artifacts (Fast: source_digest_mismatch), so ingest must run again."""
    fake = FakeFast(tmp_path)
    diff = {"text": ""}
    base = fake.__call__

    def runner(command, **kwargs):
        command = list(command)
        if command[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(command, 0, diff["text"], "")
        return base(command, **kwargs)

    config = FastConfig(command=("fast",), snapshot=".fast/project.sfast", state=".fast/state.json")
    FastLoopIntegration(tmp_path, config=config, runner=runner).ingest()
    FastLoopIntegration(tmp_path, config=config, runner=runner).ingest()
    assert sum(call[1] == "ingest" for call in fake.calls if call[0] == "fast") == 1
    diff["text"] = "diff --git a/app.py b/app.py\n+edit\n"
    FastLoopIntegration(tmp_path, config=config, runner=runner).ingest()
    assert sum(call[1] == "ingest" for call in fake.calls if call[0] == "fast") == 2
