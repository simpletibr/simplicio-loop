"""Economy-parallel profile: token path + bounded parallel defaults."""
from __future__ import annotations

import pytest

from simplicio_loop import economy_profile as ep
from simplicio_loop import strict_mode


def test_worker_bounds_scale_with_cpu():
    # Maximum the machine can use: all logical CPUs (floor 2)
    assert ep.recommend_operator_workers(1) == 2
    assert ep.recommend_operator_workers(4) == 4
    assert ep.recommend_operator_workers(32) == 32  # no artificial 12 clamp


def test_prism_slots_machine_max_scales_with_cpu(monkeypatch):
    # Isolate from RAM so CPU formula is deterministic
    monkeypatch.setattr(ep, "_ram_gb", lambda: (None, None))
    assert ep.recommend_prism_slots(1) == 2
    assert ep.recommend_prism_slots(2) == 2
    assert ep.recommend_prism_slots(4) == 3  # leave 1 core for OS/Runtime
    assert ep.recommend_prism_slots(16) == 15  # no 8-slot ceiling
    # Total RAM capacity caps slots (32 GiB → 28 usable → up to 28; min with cpu)
    monkeypatch.setattr(ep, "_ram_gb", lambda: (32.0, 20.0))
    assert ep.recommend_prism_slots(16) == 15  # cpu still binds
    monkeypatch.setattr(ep, "_ram_gb", lambda: (8.0, 6.0))  # 8-4=4 slots
    assert ep.recommend_prism_slots(16) == 4
    # Critical free RAM tightens further
    monkeypatch.setattr(ep, "_ram_gb", lambda: (32.0, 2.0))
    assert ep.recommend_prism_slots(16) == 2


def test_economy_env_is_adaptive_auto_regardless_of_runtime():
    # REQUIRE_RUNTIME / EXECUTION_PROFILE stay "auto" (never a hard "off"/"standalone")
    # whether or not Runtime happens to be operational right now (issue #1287).
    for operational in (True, False):
        env = ep.economy_parallel_env(
            runtime_operational=operational, prism_slots=4, operator_workers=6
        )
        assert env["SIMPLICIO_LOOP_REQUIRE_RUNTIME"] == "auto"
        assert env["SIMPLICIO_EXECUTION_PROFILE"] == "auto"


def test_economy_env_binds_mcp_when_runtime_operational():
    env = ep.economy_parallel_env(runtime_operational=True, prism_slots=4, operator_workers=6)
    assert env["SIMPLICIO_REQUIRE_MCP"] == "1"
    assert env["SIMPLICIO_MCP_FORCE"] == "1"


def test_economy_env_enables_fan_out_and_latest():
    env = ep.economy_parallel_env(runtime_operational=True, prism_slots=4, operator_workers=6)
    assert env["SIMPLICIO_LOOP_AUTO_FAN_OUT"] == "1"
    assert env["SIMPLICIO_OPERATOR_ALWAYS_LATEST"] == "1"
    assert env["SIMPLICIO_PRISM_SLOTS"] == "4"
    assert env["SIMPLICIO_PRISM_BATCH_SIZE"] == "10"
    assert env["SIMPLICIO_LOOP_OPERATOR_WORKERS"] == "6"
    assert env["SIMPLICIO_FAST_MODE"] == "required"
    assert env["SIMPLICIO_REQUIRE_MCP"] == "1"
    assert env["SIMPLICIO_MCP_FORCE"] == "1"
    assert env["SIMPLICIO_EXECUTION_PROFILE"] == "auto"


def test_profile_status_exposes_llm_max_speed_orientation():
    status = ep.profile_status(runtime_operational=True)
    orient = status["llm_orientation"]
    assert orient["schema"] == "simplicio.llm-max-speed-orientation/v1"
    assert orient["canonical_doc"] == "docs/LLM_MAX_SPEED_ORIENTATION.md"
    assert "DONE" in orient["message_cadence"]
    assert any("hand-edit" in f for f in orient["forbid"])
    assert orient["context_route"]["primary"] == "simplicio-fast"
    assert orient["fallback_policy"]["auto"] == "mapper_read_only"
    assert orient["mutation_boundary"]["authorized"] is False
    assert orient["receipt_schema"] == "simplicio.loop-orient-receipt/v1"
    assert status["hot_path"][0].startswith("simplicio loop decide")


def test_prism_batch_defaults_to_ten_and_supports_explicit_thirty():
    assert ep.resolve_prism_batch_size() == 10
    assert ep.resolve_prism_batch_size(30) == 30
    assert ep.prism_batches(range(1, 26), 10) == [
        list(range(1, 11)), list(range(11, 21)), list(range(21, 26))
    ]
    assert ep.prism_is_eligible(3)["eligible"] is False
    assert ep.prism_is_eligible(3)["parallelism"] == "direct"
    assert ep.prism_is_eligible(4)["eligible"] is True
    assert ep.prism_is_eligible(4)["reason_code"] == "prism_above_three_tasks"
    assert ep.prism_is_eligible(1)["reason_code"] == "single_item"
    assert ep.resolve_prism_batch_size(65) == 65
    with pytest.raises(ValueError):
        ep.resolve_prism_batch_size(9)


def test_economy_env_without_runtime_disables_mcp_force():
    env = ep.economy_parallel_env(runtime_operational=False)
    assert env["SIMPLICIO_REQUIRE_MCP"] == "0"
    assert env["SIMPLICIO_MCP_FORCE"] == "0"
    assert env["SIMPLICIO_EXECUTION_PROFILE"] == "auto"


def test_profile_status_reports_runtime_backed_and_no_note_when_operational():
    status = ep.profile_status(runtime_operational=True)
    assert status["runtime_operational"] is True
    assert status["execution_profile"] == "runtime-backed"
    assert status["note"] is None
    assert status["recommended"]["SIMPLICIO_LOOP_REQUIRE_RUNTIME"] == "auto"
    assert status["recommended"]["SIMPLICIO_EXECUTION_PROFILE"] == "auto"
    assert status["recommended"]["SIMPLICIO_REQUIRE_MCP"] == "1"
    assert status["recommended"]["SIMPLICIO_MCP_FORCE"] == "1"


def test_profile_status_reports_standalone_and_unverified_note_when_not_operational():
    status = ep.profile_status(runtime_operational=False)
    assert status["runtime_operational"] is False
    assert status["execution_profile"] == "standalone"
    assert status["note"] == "UNVERIFIED|runtime_unavailable"
    assert status["recommended"]["SIMPLICIO_REQUIRE_MCP"] == "0"
    assert status["recommended"]["SIMPLICIO_MCP_FORCE"] == "0"


def test_recommended_env_uses_economy_when_enabled(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ECONOMY_PARALLEL", "1")
    monkeypatch.setattr(
        strict_mode,
        "runtime_status",
        lambda env=None: {
            "operational": True,
            "present": True,
            "version": "Simplicio Runtime 3.5.7",
            "path": "x",
        },
    )
    monkeypatch.setattr(
        strict_mode,
        "fast_status",
        lambda env=None: {"operational": True, "present": True, "version": "2.0.23"},
    )
    rec = strict_mode.recommended_env({})
    assert rec["SIMPLICIO_LOOP_AUTO_FAN_OUT"] == "1"
    assert rec["SIMPLICIO_OPERATOR_ALWAYS_LATEST"] == "1"
    assert "SIMPLICIO_PRISM_SLOTS" in rec


def test_recommended_env_opt_out_minimal(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ECONOMY_PARALLEL", "0")
    monkeypatch.setattr(
        strict_mode,
        "runtime_status",
        lambda env=None: {"operational": False, "present": False, "version": ""},
    )
    monkeypatch.setattr(
        strict_mode,
        "fast_status",
        lambda env=None: {"operational": False, "present": False, "version": ""},
    )
    rec = strict_mode.recommended_env({})
    assert rec["SIMPLICIO_LOOP"] == "1"
    # minimal path still prefers auto fan-out + always-latest
    assert rec["SIMPLICIO_LOOP_AUTO_FAN_OUT"] == "1"
