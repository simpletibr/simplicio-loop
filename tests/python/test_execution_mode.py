from __future__ import annotations

import json
from timeit import timeit
from types import SimpleNamespace

import pytest

from simplicio import cli
from simplicio.execution_mode import negotiate_execution_mode, requested_mode

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


class RuntimeEffectSink:
    pass


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


def test_auto_policy_fallback_and_kill_switch(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTION_ROLLOUT", "default")
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


def test_shadow_observes_but_never_dispatches_integrated():
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


def test_task_feature_sprint_cli_parser_mode_parity():
    parser = cli._build_parser()
    task = parser.parse_args(["task", "g", "--target", "x", "--mode", "standalone"])
    feature = parser.parse_args(["run", "g", "--scope", "feature", "--mode", "integrated"])
    sprint = parser.parse_args(["run", "g", "--scope", "sprint", "--mode", "auto"])
    assert (task.mode, feature.mode, sprint.mode) == ("standalone", "integrated", "auto")


def test_negotiation_benchmark_hot_path_under_100_microseconds(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_EXECUTION_ROLLOUT", "canary")
    elapsed = timeit(
        lambda: negotiate_execution_mode(
            "auto", runtime_handshake=READY, context_snapshot=CONTEXT, effect_sink=RuntimeEffectSink()
        ),
        number=1000,
    )
    assert elapsed / 1000 < 0.0001
