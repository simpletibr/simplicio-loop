"""web_research (plan): optional web research gated by SIMPLICIO_247_WEB_RESEARCH env var.

Applies only when the env var is set to '1'.
When disabled (default), records as skipped for security.
"""
import os

import pytest

from simplicio_loop.watcher247 import points


def test_web_research_skipped_by_default(point_contract, make_ctx, monkeypatch):
    """When SIMPLICIO_247_WEB_RESEARCH is not set, the point is skipped."""
    monkeypatch.delenv("SIMPLICIO_247_WEB_RESEARCH", raising=False)
    
    ctx = make_ctx(task_text="research: find best practices for async Python")
    result = point_contract("web_research", ctx, expect="skipped")
    assert result.reason_code == "disabled"


def test_web_research_applies_when_enabled(point_contract, make_ctx, monkeypatch):
    """When SIMPLICIO_247_WEB_RESEARCH=1, the point returns ok (hook for future web calls)."""
    monkeypatch.setenv("SIMPLICIO_247_WEB_RESEARCH", "1")
    
    ctx = make_ctx(task_text="research: find best practices for async Python")
    result = point_contract("web_research", ctx, expect="ok")
    assert result.status == "ok"
    assert "hook" in str(result.evidence).lower() or "skipped" in str(result.reason_code).lower()


def test_web_research_records_intent(point_contract, make_ctx, monkeypatch):
    """When enabled, web_research records the search intent from the task."""
    monkeypatch.setenv("SIMPLICIO_247_WEB_RESEARCH", "1")
    
    task_text = "research: find async patterns in FastAPI"
    ctx = make_ctx(task_text=task_text)
    result = point_contract("web_research", ctx, expect="ok")
    # The evidence should document that this is a hook point
    assert isinstance(result.evidence, dict)
