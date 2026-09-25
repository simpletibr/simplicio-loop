"""Strict mode + adaptive Runtime/Fast bind."""
from __future__ import annotations

from simplicio_loop import strict_mode as sm


def test_strict_enabled_from_env():
    assert sm.strict_enabled({"SIMPLICIO_LOOP_STRICT": "1"}) is True
    assert sm.strict_enabled({"SIMPLICIO_LOOP_MODE": "full-stack"}) is True
    assert sm.strict_enabled({}) is False


def test_required_operators_include_runtime_when_operational(monkeypatch):
    monkeypatch.setattr(sm, "runtime_status", lambda env=None: {
        "binary": "simplicio", "present": True, "operational": True, "version": "3.5.5", "error": "",
    })
    monkeypatch.setattr(sm, "fast_status", lambda env=None: {
        "binary": "simplicio-fast", "present": False, "operational": False, "version": "", "error": "",
    })
    monkeypatch.setattr(sm, "action_operator_status", lambda env=None: {
        "operational": True, "resolved_as": "simplicio-dev-cli", "version": "ok", "error": "",
    })
    monkeypatch.setattr(sm, "_probe_version", lambda binary, args=("--version",), timeout=8.0: {
        "binary": binary, "present": True, "operational": True, "version": "ok", "error": "",
    })
    required = sm.required_bound_operators({"SIMPLICIO_LOOP_REQUIRE_RUNTIME": "auto"})
    assert "simplicio-mapper" in required
    assert "simplicio-dev-cli" in required
    assert "simplicio" in required


def test_required_operators_skip_runtime_when_absent(monkeypatch):
    monkeypatch.setattr(sm, "runtime_status", lambda env=None: {
        "binary": "simplicio", "present": False, "operational": False, "version": "", "error": "missing",
    })
    monkeypatch.setattr(sm, "fast_status", lambda env=None: {
        "binary": "simplicio-fast", "present": False, "operational": False, "version": "", "error": "",
    })
    required = sm.required_bound_operators({"SIMPLICIO_LOOP_REQUIRE_RUNTIME": "auto"})
    assert "simplicio" not in required


def test_strict_requires_operational_fast(monkeypatch):
    monkeypatch.setattr(sm, "runtime_status", lambda env=None: {
        "binary": "simplicio", "present": False, "operational": False, "version": "", "error": "",
    })
    monkeypatch.setattr(sm, "fast_status", lambda env=None: {
        "binary": "simplicio-fast", "present": True, "operational": True, "version": "2.0.14", "error": "",
    })
    required = sm.required_bound_operators({"SIMPLICIO_LOOP_STRICT": "1"})
    assert "simplicio-fast" in required


def test_resolve_profile_runtime_backed_when_operational(monkeypatch):
    monkeypatch.setattr(sm, "runtime_status", lambda env=None: {
        "binary": "simplicio", "present": True, "operational": True, "version": "3.5.5", "error": "",
    })
    assert sm.resolve_execution_profile({"SIMPLICIO_EXECUTION_PROFILE": "auto"}) == "runtime-backed"
    assert sm.resolve_execution_profile({}) == "standalone"
    assert sm.resolve_execution_profile({"SIMPLICIO_EXECUTION_PROFILE": "standalone"}) == "standalone"


def test_recommended_env_minimal_fallback_keeps_runtime_off_when_economy_disabled(monkeypatch):
    # Economy-parallel opted out (via the *passed* env, since recommended_env
    # reads the mapping it is given, not the process environment) falls back
    # to the minimal strict envelope, which stays hard "off"/"standalone" —
    # this is the explicit opt-out path, distinct from the adaptive "auto"
    # economy_parallel_env() now returns (issue #1287).
    monkeypatch.setattr(
        sm,
        "runtime_status",
        lambda env=None: {
            "binary": "simplicio",
            "present": True,
            "operational": True,
            "version": "3.5.5",
            "error": "",
        },
    )
    monkeypatch.setattr(
        sm,
        "fast_status",
        lambda env=None: {
            "binary": "simplicio-fast",
            "present": False,
            "operational": False,
            "version": "",
            "error": "",
        },
    )
    rec = sm.recommended_env({"SIMPLICIO_ECONOMY_PARALLEL": "0"})
    assert rec["SIMPLICIO_LOOP_REQUIRE_RUNTIME"] == "off"
    assert rec["SIMPLICIO_EXECUTION_PROFILE"] == "standalone"


def test_recommended_env_economy_enabled_is_adaptive_auto_with_runtime_operational(monkeypatch):
    # When economy-parallel is enabled (default) and Runtime is operational,
    # recommended_env must surface the adaptive "auto" values + bound MCP,
    # not the old hard-coded standalone/off/MCP-disabled triple (issue #1287).
    monkeypatch.setattr(
        sm,
        "runtime_status",
        lambda env=None: {
            "binary": "simplicio",
            "present": True,
            "operational": True,
            "version": "3.5.5",
            "error": "",
        },
    )
    monkeypatch.setattr(
        sm,
        "fast_status",
        lambda env=None: {
            "binary": "simplicio-fast",
            "present": False,
            "operational": False,
            "version": "",
            "error": "",
        },
    )
    rec = sm.recommended_env({})
    assert rec["SIMPLICIO_LOOP_REQUIRE_RUNTIME"] == "auto"
    assert rec["SIMPLICIO_EXECUTION_PROFILE"] == "auto"
    assert rec["SIMPLICIO_REQUIRE_MCP"] == "1"
    assert rec["SIMPLICIO_MCP_FORCE"] == "1"


def test_hand_edit_forbidden_under_strict():
    assert sm.hand_edit_forbidden({"SIMPLICIO_LOOP_STRICT": "1"}) is True
    assert sm.hand_edit_forbidden({}) is False


def test_preflight_payload_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(sm, "runtime_status", lambda env=None: {
        "binary": "simplicio", "present": True, "operational": True, "version": "3.5.5", "error": "",
    })
    monkeypatch.setattr(sm, "fast_status", lambda env=None: {
        "binary": "simplicio-fast", "present": True, "operational": True, "version": "2.0.14", "error": "",
    })
    monkeypatch.setattr(sm, "action_operator_status", lambda env=None: {
        "operational": True, "resolved_as": "simplicio-dev-cli", "version": "ok", "error": "",
    })
    monkeypatch.setattr(sm, "_probe_version", lambda binary, args=("--version",), timeout=8.0: {
        "binary": binary, "present": True, "operational": True, "version": "ok", "error": "",
    })
    payload = sm.preflight_payload(str(tmp_path), strict=True)
    assert payload["schema"] == "simplicio.preflight/v1"
    assert payload["strict"] is True
    assert payload["runtime_available"] is True
    assert payload["execution_profile"] == "standalone"
    assert payload["hand_edit_forbidden"] is True
    assert "simplicio" not in payload["required_operators"]
