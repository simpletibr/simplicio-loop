"""Strict mode + adaptive Fast bind (standalone-only execution profile)."""
from __future__ import annotations

from simplicio_loop import strict_mode as sm


def test_strict_enabled_from_env():
    assert sm.strict_enabled({"SIMPLICIO_LOOP_STRICT": "1"}) is True
    assert sm.strict_enabled({"SIMPLICIO_LOOP_MODE": "full-stack"}) is True
    assert sm.strict_enabled({}) is False


def test_required_operators_are_core_only_by_default(monkeypatch):
    monkeypatch.setattr(sm, "fast_status", lambda env=None: {
        "binary": "simplicio-fast", "present": False, "operational": False, "version": "", "error": "",
    })
    required = sm.required_bound_operators({})
    assert "simplicio-mapper" in required
    assert "simplicio-dev-cli" in required
    assert "simplicio" not in required


def test_strict_requires_operational_fast(monkeypatch):
    monkeypatch.setattr(sm, "fast_status", lambda env=None: {
        "binary": "simplicio-fast", "present": True, "operational": True, "version": "2.0.14", "error": "",
    })
    required = sm.required_bound_operators({"SIMPLICIO_LOOP_STRICT": "1"})
    assert "simplicio-fast" in required


def test_resolve_profile_is_always_standalone():
    assert sm.resolve_execution_profile({"SIMPLICIO_EXECUTION_PROFILE": "auto"}) == "standalone"
    assert sm.resolve_execution_profile({}) == "standalone"
    assert sm.resolve_execution_profile({"SIMPLICIO_EXECUTION_PROFILE": "standalone"}) == "standalone"


def test_recommended_env_minimal_fallback_is_standalone(monkeypatch):
    # Economy-parallel opted out (via the *passed* env, since recommended_env
    # reads the mapping it is given, not the process environment) falls back
    # to the minimal strict envelope, which is always "standalone" -- there
    # is no Runtime/MCP backend in this stack.
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
    assert rec["SIMPLICIO_EXECUTION_PROFILE"] == "standalone"
    assert "SIMPLICIO_LOOP_REQUIRE_RUNTIME" not in rec
    assert "SIMPLICIO_REQUIRE_MCP" not in rec
    assert "SIMPLICIO_MCP_FORCE" not in rec


def test_recommended_env_economy_enabled_is_standalone(monkeypatch):
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
    assert rec["SIMPLICIO_EXECUTION_PROFILE"] == "standalone"
    assert "SIMPLICIO_LOOP_REQUIRE_RUNTIME" not in rec
    assert "SIMPLICIO_REQUIRE_MCP" not in rec
    assert "SIMPLICIO_MCP_FORCE" not in rec


def test_hand_edit_forbidden_under_strict():
    assert sm.hand_edit_forbidden({"SIMPLICIO_LOOP_STRICT": "1"}) is True
    assert sm.hand_edit_forbidden({}) is False


def test_preflight_payload_shape(monkeypatch, tmp_path):
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
    assert "runtime_available" not in payload
    assert payload["execution_profile"] == "standalone"
    assert payload["hand_edit_forbidden"] is True
    assert "simplicio" not in payload["required_operators"]
    assert all(item["name"] != "simplicio-runtime" for item in payload["operators"])
