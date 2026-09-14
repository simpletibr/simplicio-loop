from __future__ import annotations

from pathlib import Path

import simplicio_loop.prompt_bridge as bridge


def test_enrich_user_prompt_is_passthrough_and_does_not_call_runtime(tmp_path: Path):
    def runner(argv: list[str], timeout: float, env):
        raise AssertionError(f"runtime must not run: {argv!r} timeout={timeout} env={env}")

    result = bridge.enrich_user_prompt(
        "implement the roster fix",
        session_id="session-1",
        repo=tmp_path,
        env={"SIMPLICIO_RUNTIME_BIN": "/opt/simplicio"},
        runner=runner,
        body_loader=lambda handle: f"body for {handle}",
    )

    assert result["prompt"] == "implement the roster fix"
    assert result["receipt"]["schema"] == bridge.RECEIPT_SCHEMA
    assert result["receipt"]["status"] == "skipped"
    assert result["receipt"]["reason_code"] == "prompt_enrichment_removed"
    assert result["receipt"]["materialized_handles"] == []
    assert "## Simplicio skill:" not in result["additional_context"]
    assert "body for" not in result["additional_context"]
    assert bridge.RECEIPT_SCHEMA in result["additional_context"]


def test_enrichment_is_skipped_even_when_runtime_is_declared_available():
    def runner(argv: list[str], timeout: float, env):
        raise AssertionError("runtime process must not run")

    result = bridge.enrich_user_prompt(
        "implement the parser",
        session_id="session-degraded",
        env={"SIMPLICIO_RUNTIME_AVAILABLE": "1"},
        runner=runner,
        body_loader=lambda handle: f"fallback body for {handle}",
    )

    assert result["prompt"] == "implement the parser"
    assert result["receipt"]["status"] == "skipped"
    assert result["receipt"]["reason_code"] == "prompt_enrichment_removed"
    assert result["receipt"]["fallback"]["used"] is False
    assert result["route"]["runtime_status"] == "unavailable"
    assert result["route_decision"] == result["route"]


def test_supplied_route_environment_does_not_inject_skill_bodies():
    def runner(argv: list[str], timeout: float, env):
        raise AssertionError("runtime process must not run")

    result = bridge.enrich_user_prompt(
        "survey repository",
        env={"SIMPLICIO_ROUTE_DECISION": "{}"},
        runner=runner,
        body_loader=lambda handle: "skill",
    )

    assert result["prompt"] == "survey repository"
    assert result["receipt"]["status"] == "skipped"
    assert "skill" not in result["additional_context"]


def test_reset_cache_is_a_noop():
    bridge.reset_cache()
    first = bridge.enrich_user_prompt("survey repository", session_id="cache-session")
    bridge.reset_cache()
    second = bridge.enrich_user_prompt("survey repository", session_id="cache-session")
    assert first["receipt"]["status"] == second["receipt"]["status"] == "skipped"


def test_public_exports_remain_importable():
    assert bridge.RECEIPT_SCHEMA == "simplicio.prompt-enrichment-receipt/v1"
    assert bridge.ROUTE_SCHEMA
    assert bridge.AUTHORITY_LOCKED == {"writes": False, "effects": False}
    assert callable(bridge.enrich_user_prompt)
    assert callable(bridge.reset_cache)
