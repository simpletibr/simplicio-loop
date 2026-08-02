from __future__ import annotations

import json
from time import process_time
from types import SimpleNamespace

import pytest

from simplicio import cli, execution_mode
from simplicio.atomic_execution import AttemptContext
from simplicio.execution_mode import (
    capabilities_report,
    negotiate_execution_mode,
    prepare_execution_inputs,
    requested_mode,
    require_coordinator_attempt,
)

READY = {
    "verified": True,
    "version": "3.6.0",
    "capabilities": ["simplicio.effect-transaction/v1"],
    "reason": "ok",
}
CONTEXT = {
    "schema": "simplicio.context-snapshot/v1",
    "snapshot_id": "real",
    "revision": "abc",
    "digest": "sha256:1",
}


@pytest.fixture(autouse=True)
def canonical_mapper_boundary(monkeypatch):
    def load(payload, **_kwargs):
        if payload is CONTEXT:
            return SimpleNamespace(payload_bytes=b"canonical-context")
        from simplicio.plan_compiler.mapper_context import MapperContextError

        raise MapperContextError("TEST_CONTEXT_REJECTED", "not canonical")

    monkeypatch.setattr("simplicio.execution_mode.load_mapper_context", load)
    monkeypatch.setattr("simplicio.execution_mode.RuntimeEffectSink", RuntimeEffectSink)


class RuntimeEffectSink:
    test_only = False


@pytest.mark.parametrize("coordinator", ["simplicio-agent", "codex-cloud"])
def test_auto_canary_selects_integrated_from_versioned_handshake(monkeypatch, coordinator):
    monkeypatch.setenv("SIMPLICIO_EXECUTION_ROLLOUT", "canary")
    profile = negotiate_execution_mode(
        "auto",
        runtime_handshake=READY,
        context_snapshot=CONTEXT,
        effect_sink=RuntimeEffectSink(),
        coordinator_kind=coordinator,
    )
    assert profile.effective_mode == "integrated"
    assert profile.reason_code == "AUTO_INTEGRATED"
    assert profile.coordinator["kind"] == coordinator


def test_auto_defaults_to_integrated_when_contracts_are_ready(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_EXECUTION_ROLLOUT", raising=False)
    profile = negotiate_execution_mode(
        "auto", runtime_handshake=READY, context_snapshot=CONTEXT, effect_sink=RuntimeEffectSink()
    )
    assert profile.rollout == "default"
    assert profile.effective_mode == "integrated"
    assert profile.reason_code == "AUTO_INTEGRATED"


@pytest.mark.parametrize(
    ("handshake", "context", "sink", "reason"),
    [
        ({"verified": False, "capabilities": []}, CONTEXT, RuntimeEffectSink(), "INCOMPATIBLE_RUNTIME"),
        (READY, None, RuntimeEffectSink(), "CONTEXT_REQUIRED"),
        (READY, {"schema": "shadow/v1"}, RuntimeEffectSink(), "INCOMPATIBLE_CONTEXT"),
        (READY, CONTEXT, None, "RUNTIME_SINK_REQUIRED"),
    ],
)
def test_integrated_matrix_fails_closed(handshake, context, sink, reason):
    profile = negotiate_execution_mode(
        "integrated", runtime_handshake=handshake, context_snapshot=context, effect_sink=sink
    )
    assert profile.effective_mode == "blocked"
    assert profile.reason_code == reason
    assert profile.fallback_reason is None


def test_non_object_runtime_handshake_fails_closed() -> None:
    profile = negotiate_execution_mode(
        "integrated",
        runtime_handshake=[],  # type: ignore[arg-type]
        context_snapshot=CONTEXT,
        effect_sink=RuntimeEffectSink(),
    )

    assert profile.effective_mode == "blocked"
    assert profile.reason_code == "INCOMPATIBLE_RUNTIME"
    assert profile.runtime["reason"] == "RUNTIME_HANDSHAKE_INVALID"


def test_explicit_empty_snapshot_is_not_replaced_by_environment(monkeypatch) -> None:
    monkeypatch.setattr(
        "simplicio.execution_mode._load_context_snapshot",
        lambda *_args, **_kwargs: CONTEXT,
    )

    prepared = prepare_execution_inputs("integrated", context_snapshot={})

    assert prepared.context_snapshot == {}


def test_schema_string_without_mapper_validation_is_not_canonical():
    profile = negotiate_execution_mode(
        "integrated",
        runtime_handshake=READY,
        context_snapshot={"schema": "simplicio.context-snapshot/v1"},
        effect_sink=RuntimeEffectSink(),
    )
    assert profile.effective_mode == "blocked"
    assert profile.reason_code == "INCOMPATIBLE_CONTEXT"
    assert profile.mapper["contract_error"] == "TEST_CONTEXT_REJECTED"


def test_sink_that_only_mimics_the_class_name_is_rejected():
    class RuntimeEffectSinkLookalike:
        pass

    profile = negotiate_execution_mode(
        "integrated",
        runtime_handshake=READY,
        context_snapshot=CONTEXT,
        effect_sink=RuntimeEffectSinkLookalike(),
    )

    assert profile.effective_mode == "blocked"
    assert profile.reason_code == "RUNTIME_SINK_REQUIRED"


def test_auto_policy_fallback_and_kill_switch(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTION_ROLLOUT", "default")
    monkeypatch.setenv("SIMPLICIO_ALLOW_STANDALONE_FALLBACK", "true")
    monkeypatch.setenv("SIMPLICIO_INTEGRATED_KILL_SWITCH", "1")
    profile = negotiate_execution_mode(
        "auto", runtime_handshake=READY, context_snapshot=CONTEXT, effect_sink=RuntimeEffectSink()
    )
    assert profile.effective_mode == "standalone"
    assert profile.fallback_reason == "INTEGRATED_KILLED"
    monkeypatch.setenv("SIMPLICIO_ALLOW_STANDALONE_FALLBACK", "false")
    assert (
        negotiate_execution_mode(
            "auto", runtime_handshake=READY, context_snapshot=CONTEXT, effect_sink=RuntimeEffectSink()
        ).effective_mode
        == "blocked"
    )


def test_auto_blocks_without_explicit_standalone_fallback(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTION_ROLLOUT", "default")
    monkeypatch.delenv("SIMPLICIO_ALLOW_STANDALONE_FALLBACK", raising=False)
    profile = negotiate_execution_mode(
        "auto", runtime_handshake={"verified": False, "capabilities": [], "reason": "runtime-absent"}
    )

    assert profile.effective_mode == "standalone"
    assert profile.reason_code == "AUTO_DEGRADED"
    assert profile.fallback_reason == "INCOMPATIBLE_RUNTIME"
    assert profile.runtime["runtime_absent_expected"] is True


def test_auto_distinguishes_runtime_incompatibility_from_expected_absence(monkeypatch):
    profile = negotiate_execution_mode(
        "auto", runtime_handshake={"verified": False, "capabilities": [], "reason": "bad-version"}
    )
    assert profile.effective_mode == "standalone"
    assert profile.runtime["runtime_absent_expected"] is False


def test_shadow_observes_but_never_dispatches_integrated(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTION_ROLLOUT", "shadow")
    monkeypatch.setenv("SIMPLICIO_ALLOW_STANDALONE_FALLBACK", "true")
    profile = negotiate_execution_mode(
        "auto", runtime_handshake=READY, context_snapshot=CONTEXT, effect_sink=RuntimeEffectSink()
    )
    assert profile.default_eligible is True
    assert profile.effective_mode == "standalone"
    assert profile.fallback_reason == "SHADOW_OBSERVATION"


def test_precedence_flag_env_config_default(tmp_path, monkeypatch):
    config = tmp_path / ".simplicio" / "execution.json"
    config.parent.mkdir()
    config.write_text('{"mode":"integrated"}', encoding="utf-8")
    assert requested_mode(None, tmp_path) == "integrated"
    monkeypatch.setenv("SIMPLICIO_EXECUTION_MODE", "standalone")
    assert requested_mode(None, tmp_path) == "standalone"
    assert requested_mode("auto", tmp_path) == "auto"
    with pytest.raises(ValueError):
        requested_mode("unsafe", tmp_path)


def test_capabilities_cli_json_is_clean_and_installed_entrypoint_parity(monkeypatch, capsys):
    monkeypatch.setattr(
        "simplicio.runtime_contracts.runtime_verify_contract",
        lambda: {"verified": False, "capabilities": [], "reason": "runtime-not-found"},
    )
    assert cli.main(["runtime", "capabilities", "--mode", "integrated", "--json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["execution_profile"]["requested_mode"] == "integrated"
    assert payload["execution_profile"]["effective_mode"] == "blocked"


def test_capabilities_report_exposes_mode_readiness_without_runtime_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "simplicio.runtime_contracts.runtime_verify_contract",
        lambda: (_ for _ in ()).throw(AssertionError("standalone must not probe Runtime")),
    )

    payload = capabilities_report("standalone", root=str(tmp_path))

    readiness = payload["readiness"]
    assert readiness["standalone_ready"] == {"ready": True, "reason": "ready"}
    assert readiness["runtime_ready"]["ready"] is False
    assert readiness["runtime_ready"]["reason"] == "not-probed-standalone"
    assert readiness["fast_ready"]["ready"] in {True, False}


def test_task_cli_forwards_integrated_coordinator_inputs(monkeypatch, capsys):
    captured = {}

    def fake_run_task(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "applied": False,
            "status": "blocked",
            "diff_summary": "blocked",
            "warnings": ["RUNTIME_UNAVAILABLE"],
        }

    monkeypatch.setattr("simplicio.pipeline.run_task", fake_run_task)
    result = cli.main(
        [
            "task",
            "goal",
            "--target",
            "src/app.py",
            "--mode",
            "integrated",
            "--context-snapshot",
            "snapshot.json",
            "--context-pack",
            "pack.json",
            "--effect-authorization",
            "authorization.json",
            "--attempt-id",
            "attempt-1",
            "--lease-id",
            "lease-1",
            "--fencing-token",
            "fence-1",
            "--context-handle",
            "snapshot-1",
            "--coordinator-kind",
            "simplicio-agent",
            "--coordinator-id",
            "agent-1",
            "--json",
        ]
    )

    assert result == 1
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    assert captured["context_snapshot_path"] == "snapshot.json"
    assert captured["context_pack_path"] == "pack.json"
    assert captured["authorization_path"] == "authorization.json"
    assert captured["attempt_id"] == "attempt-1"
    assert captured["lease_id"] == "lease-1"
    assert captured["fencing_token"] == "fence-1"
    assert captured["context_handle"] == "snapshot-1"
    assert captured["coordinator_kind"] == "simplicio-agent"
    assert captured["coordinator_id"] == "agent-1"


def test_task_cli_invalid_context_path_fails_as_clean_json(tmp_path, capsys):
    result = cli.main(
        [
            "task",
            "goal",
            "--root",
            str(tmp_path),
            "--target",
            "src/app.py",
            "--mode",
            "integrated",
            "--context-snapshot",
            "missing.json",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["warnings"] == ["INCOMPATIBLE_CONTEXT"]
    assert payload["execution_profile"]["effective_mode"] == "blocked"
    assert payload["execution_profile"]["reason_code"] == "INCOMPATIBLE_CONTEXT"


def test_task_feature_sprint_cli_parser_mode_parity():
    parser = cli._build_parser()
    task = parser.parse_args(
        [
            "task",
            "g",
            "--target",
            "x",
            "--mode",
            "integrated",
            "--context-snapshot",
            "snapshot.json",
            "--context-pack",
            "pack.json",
            "--attempt-id",
            "attempt-1",
            "--lease-id",
            "lease-1",
            "--fencing-token",
            "fence-1",
            "--context-handle",
            "snapshot-1",
        ]
    )
    feature = parser.parse_args(["run", "g", "--scope", "feature", "--mode", "integrated"])
    sprint = parser.parse_args(["run", "g", "--scope", "sprint", "--mode", "auto"])
    assert (task.mode, feature.mode, sprint.mode) == ("integrated", "integrated", "auto")
    assert task.context_snapshot == "snapshot.json"
    assert task.context_pack == "pack.json"
    assert task.attempt_id == "attempt-1"
    assert task.lease_id == "lease-1"
    assert task.fencing_token == "fence-1"
    assert task.context_handle == "snapshot-1"


def test_prepare_execution_inputs_loads_cli_snapshot_and_sink_handshake(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(CONTEXT), encoding="utf-8")
    pack = {"schema": "simplicio.context-pack/v1", "snapshot_digest": "sha256:1"}
    pack_path = tmp_path / "pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    sink = RuntimeEffectSink()
    sink.capability_handshake = lambda: READY
    monkeypatch.setattr(
        "simplicio.execution_mode.RuntimeEffectSink.from_environment",
        lambda **_kwargs: sink,
        raising=False,
    )
    monkeypatch.setenv("SIMPLICIO_RUNTIME_URL", "https://runtime.example")

    prepared = prepare_execution_inputs(
        "integrated",
        root=tmp_path,
        context_snapshot_path=snapshot_path,
        context_pack_path=pack_path,
        attempt_id="attempt-1",
        lease_id="lease-1",
        fencing_token="fence-1",
        context_handle="real",
    )

    assert prepared.context_snapshot == CONTEXT
    assert prepared.context_pack == pack
    assert prepared.effect_sink is sink
    assert prepared.runtime_handshake == READY
    assert prepared.attempt == AttemptContext("attempt-1", "lease-1", "fence-1", "real")


def test_prepare_execution_inputs_uses_env_and_never_probes_for_standalone(tmp_path, monkeypatch):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(CONTEXT), encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_CONTEXT_SNAPSHOT", str(snapshot_path))
    monkeypatch.setenv("SIMPLICIO_ATTEMPT_ID", "attempt-env")
    monkeypatch.setenv("SIMPLICIO_LEASE_ID", "lease-env")
    monkeypatch.setenv("SIMPLICIO_FENCING_TOKEN", "fence-env")
    monkeypatch.setenv("SIMPLICIO_CONTEXT_HANDLE", "real")
    monkeypatch.setenv("SIMPLICIO_RUNTIME_URL", "https://runtime.example")
    monkeypatch.setattr(
        "simplicio.execution_mode.RuntimeEffectSink.from_environment",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("standalone must not probe Runtime")),
        raising=False,
    )

    standalone = prepare_execution_inputs("standalone", root=tmp_path)
    assert standalone.context_snapshot is None
    assert standalone.effect_sink is None

    sink = RuntimeEffectSink()
    sink.capability_handshake = lambda: READY
    monkeypatch.setattr(
        "simplicio.execution_mode.RuntimeEffectSink.from_environment",
        lambda **_kwargs: sink,
        raising=False,
    )
    integrated = prepare_execution_inputs("integrated", root=tmp_path)
    assert integrated.context_snapshot == CONTEXT
    assert integrated.attempt == AttemptContext("attempt-env", "lease-env", "fence-env", "real")


def test_standalone_loads_explicit_context_pack_path(tmp_path):
    pack = {"schema": "simplicio.context-pack/v1", "fidelity": {"gate": "degraded_local"}}
    pack_path = tmp_path / "context-pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")

    prepared = prepare_execution_inputs(
        "standalone",
        root=tmp_path,
        context_pack_path=pack_path,
    )

    assert prepared.context_pack == pack


def test_standalone_negotiation_never_probes_runtime_or_mapper(monkeypatch):
    monkeypatch.setattr(
        "simplicio.runtime_contracts.runtime_verify_contract",
        lambda: (_ for _ in ()).throw(AssertionError("standalone must not probe Runtime")),
    )
    monkeypatch.setattr(
        "simplicio.execution_mode.load_mapper_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("standalone must not probe Mapper")),
    )

    profile = negotiate_execution_mode(
        "standalone",
        context_snapshot={"schema": "invalid"},
        effect_sink=object(),
    )

    assert profile.effective_mode == "standalone"
    assert profile.runtime["reason"] == "not-probed-standalone"


def test_prepare_execution_inputs_rejects_partial_attempt_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ATTEMPT_ID", "attempt-only")
    with pytest.raises(ValueError, match="all coordinator attempt fields"):
        prepare_execution_inputs("integrated", root=tmp_path)


def test_integrated_selection_without_attempt_fails_closed():
    profile = negotiate_execution_mode(
        "integrated",
        runtime_handshake=READY,
        context_snapshot=CONTEXT,
        effect_sink=RuntimeEffectSink(),
    )

    blocked = require_coordinator_attempt(profile, None)

    assert blocked.effective_mode == "blocked"
    assert blocked.reason_code == "COORDINATOR_CONTEXT_REQUIRED"
    assert blocked.coordinator["attempt_ready"] is False


def test_prepare_execution_inputs_bounds_snapshot_reads(tmp_path):
    snapshot_path = tmp_path / "oversized.json"
    snapshot_path.write_bytes(b"{" + b" " * (16 * 1024 * 1024) + b"}")

    with pytest.raises(ValueError, match="exceeds 16 MiB"):
        prepare_execution_inputs(
            "integrated",
            root=tmp_path,
            context_snapshot_path=snapshot_path,
        )


def test_negotiation_benchmark_hot_path_under_100_microseconds(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTION_ROLLOUT", "canary")
    start = process_time()
    for _ in range(1000):
        negotiate_execution_mode(
            "auto", runtime_handshake=READY, context_snapshot=CONTEXT, effect_sink=RuntimeEffectSink()
        )
    elapsed = process_time() - start
    assert elapsed / 1000 < 0.0001


@pytest.mark.parametrize(
    ("loader", "filename", "message"),
    [
        (execution_mode._load_context_snapshot, "context.json", "context snapshot must be a JSON object"),
        (execution_mode._load_context_pack, "pack.json", "context pack must be a JSON object"),
        (
            execution_mode._load_execution_context,
            "execution.json",
            "execution context must be a JSON object",
        ),
    ],
)
def test_execution_input_loaders_reject_non_object_json(tmp_path, loader, filename, message):
    path = tmp_path / filename
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(execution_mode.ExecutionInputError, match=message):
        loader(tmp_path, path)


def test_execution_input_loaders_resolve_relative_paths_and_reject_bad_json(tmp_path):
    (tmp_path / "context.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(execution_mode.ExecutionInputError, match="cannot read canonical context snapshot"):
        execution_mode._load_context_snapshot(tmp_path, "context.json")

    (tmp_path / "auth.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(execution_mode.ExecutionInputError, match="effect authorization"):
        execution_mode._load_authorization(tmp_path, "auth.json")


def test_standalone_read_only_and_proposal_only_profiles(monkeypatch, tmp_path):
    read_only = negotiate_execution_mode("standalone", root=tmp_path, read_only=True)
    assert read_only.effective_mode == "standalone"
    assert read_only.reason_code == "STANDALONE_READ_ONLY"

    proposal = negotiate_execution_mode("auto", root=tmp_path, context_snapshot=CONTEXT, proposal_only=True)
    assert proposal.reason_code == "PROPOSAL_ONLY_READY"
    assert proposal.effective_mode == "integrated"

    monkeypatch.setattr(
        execution_mode,
        "load_mapper_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(execution_mode.MapperContextError("bad", "bad")),
    )
    blocked = negotiate_execution_mode("auto", root=tmp_path, context_snapshot=CONTEXT, proposal_only=True)
    assert blocked.reason_code == "CONTEXT_REQUIRED"


def test_capabilities_report_returns_blocked_profile_for_invalid_input(tmp_path, monkeypatch):
    monkeypatch.setattr(
        execution_mode,
        "prepare_execution_inputs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            execution_mode.ExecutionInputError("INCOMPATIBLE_CONTEXT", "bad context")
        ),
    )
    report = execution_mode.capabilities_report("auto", root=tmp_path)
    assert report["execution_profile"]["effective_mode"] == "blocked"
    assert report["execution_profile"]["reason_code"] == "INCOMPATIBLE_CONTEXT"
