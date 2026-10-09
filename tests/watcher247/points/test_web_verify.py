"""Tests for web_verify extension point (stage verify, conditional on UI files)."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from simplicio_loop.watcher247 import points
from simplicio_loop.watcher247.points import web_verify


class TestWebVerifyApplies:
    """Test the applies() condition: fires only when diff touches UI files."""

    def test_applies_true_when_tsx_changed(self, make_ctx):
        """applies=True when plan includes .tsx files."""
        ctx = make_ctx(plan={"files_changed": ["src/components/Button.tsx"]})
        assert web_verify.applies(ctx) is True

    def test_applies_true_when_css_changed(self, make_ctx):
        """applies=True when .css/.scss files in diff."""
        ctx = make_ctx(plan={"files_changed": ["src/styles/theme.css"]})
        assert web_verify.applies(ctx) is True

    def test_applies_true_when_html_changed(self, make_ctx):
        """applies=True when .html files touched."""
        ctx = make_ctx(plan={"files_changed": ["public/index.html"]})
        assert web_verify.applies(ctx) is True

    def test_applies_true_when_vue_changed(self, make_ctx):
        """applies=True when .vue files touched."""
        ctx = make_ctx(plan={"files_changed": ["components/Hero.vue"]})
        assert web_verify.applies(ctx) is True

    def test_applies_false_when_only_py_changed(self, make_ctx):
        """applies=False when only .py files changed."""
        ctx = make_ctx(plan={"files_changed": ["src/main.py", "tests/test_app.py"]})
        assert web_verify.applies(ctx) is False

    def test_applies_false_when_no_plan(self, make_ctx):
        """applies=False when plan is None."""
        ctx = make_ctx(plan=None)
        assert web_verify.applies(ctx) is False

    def test_applies_true_when_jsx_changed(self, make_ctx):
        """applies=True when .jsx files touched."""
        ctx = make_ctx(plan={"files_changed": ["src/App.jsx"]})
        assert web_verify.applies(ctx) is True


class TestWebVerifyRun:
    """Test the web_verify() async function."""

    def test_run_success_with_screenshots(self, make_ctx, tmp_path, monkeypatch):
        """web_verify returns ok with screenshot path in evidence."""
        async def test():
            ctx = make_ctx(clone=tmp_path, run_dir=tmp_path / "run")
            
            # Mock proc.run to return success
            async def mock_run(argv, **kw):
                result = MagicMock()
                result.returncode = 0
                result.stdout = "done"
                result.stderr = ""
                return result
            
            monkeypatch.setattr("simplicio_loop.watcher247.points.web_verify.proc.run", mock_run)
            
            result = await web_verify.run(ctx)
            assert result.status == "ok"
            assert "screenshot" in result.evidence
            assert result.name == "web_verify"
        
        asyncio.run(test())

    def test_run_script_missing_returns_skipped(self, make_ctx, tmp_path, monkeypatch):
        """web_verify returns skipped when script not found."""
        async def test():
            ctx = make_ctx(clone=tmp_path)
            
            # Mock proc.run to raise (script not found)
            async def mock_run(argv, **kw):
                raise FileNotFoundError("python3 not found")
            
            monkeypatch.setattr("simplicio_loop.watcher247.points.web_verify.proc.run", mock_run)
            
            result = await web_verify.run(ctx)
            assert result.status == "skipped"
            assert result.reason_code == "script_unavailable"
        
        asyncio.run(test())

    def test_run_no_clone_returns_skipped(self, make_ctx):
        """web_verify returns skipped when clone is None."""
        async def test():
            ctx = make_ctx(clone=None)
            result = await web_verify.run(ctx)
            assert result.status == "skipped"
            assert result.reason_code == "no_clone"
        
        asyncio.run(test())


class TestWebVerifyContract:
    """Test integration with the points contract."""

    def test_web_verify_registered(self):
        """web_verify must be registered in the points registry."""
        infos = points.registered(stage="verify")
        assert any(info.name == "web_verify" for info in infos), "web_verify not registered at verify stage"

    def test_web_verify_conditional(self):
        """web_verify must be conditional (have applies function)."""
        infos = points.registered(stage="verify")
        web_verify_info = next(i for i in infos if i.name == "web_verify")
        assert web_verify_info.conditional, "web_verify must be conditional"

    def test_contract(self, point_contract, make_ctx, tmp_path, monkeypatch):
        """web_verify point passes the contract when applied."""
        ctx = make_ctx(clone=tmp_path, plan={"files_changed": ["src/app.tsx"]})
        
        # Mock proc.run
        async def mock_run(argv, **kw):
            result = MagicMock()
            result.returncode = 0
            result.stdout = "done"
            result.stderr = ""
            return result
        
        monkeypatch.setattr("simplicio_loop.watcher247.points.web_verify.proc.run", mock_run)
        
        result = point_contract("web_verify", ctx, expect="ok")
        assert result.evidence.get("screenshot")
