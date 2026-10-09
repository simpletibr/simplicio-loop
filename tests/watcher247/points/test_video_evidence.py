"""Tests for video_evidence extension point (stage pr, conditional on env var and screenshots)."""
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from simplicio_loop.watcher247 import points
from simplicio_loop.watcher247.points import video_evidence


class TestVideoEvidenceApplies:
    """Test the applies() condition: fires only when env var is set and screenshots exist."""

    def test_applies_false_when_env_not_set(self, make_ctx, tmp_path, monkeypatch):
        """applies=False when SIMPLICIO_247_VIDEO_EVIDENCE is not set."""
        monkeypatch.delenv("SIMPLICIO_247_VIDEO_EVIDENCE", raising=False)
        ctx = make_ctx(run_dir=tmp_path)
        assert video_evidence.applies(ctx) is False

    def test_applies_false_when_no_screenshots(self, make_ctx, tmp_path, monkeypatch):
        """applies=False when web_verify dir doesn't exist."""
        monkeypatch.setenv("SIMPLICIO_247_VIDEO_EVIDENCE", "1")
        ctx = make_ctx(run_dir=tmp_path)
        assert video_evidence.applies(ctx) is False

    def test_applies_false_when_no_png_files(self, make_ctx, tmp_path, monkeypatch):
        """applies=False when web_verify dir has no .png files."""
        monkeypatch.setenv("SIMPLICIO_247_VIDEO_EVIDENCE", "1")
        web_verify_dir = tmp_path / "web_verify"
        web_verify_dir.mkdir()
        # Create a non-image file
        (web_verify_dir / "ledger.txt").write_text("log")
        ctx = make_ctx(run_dir=tmp_path)
        assert video_evidence.applies(ctx) is False

    def test_applies_true_when_env_set_and_screenshots_exist(self, make_ctx, tmp_path, monkeypatch):
        """applies=True when SIMPLICIO_247_VIDEO_EVIDENCE=1 and .png files exist."""
        monkeypatch.setenv("SIMPLICIO_247_VIDEO_EVIDENCE", "1")
        web_verify_dir = tmp_path / "web_verify"
        web_verify_dir.mkdir()
        (web_verify_dir / "1-web.png").write_text("fake image")
        ctx = make_ctx(run_dir=tmp_path)
        assert video_evidence.applies(ctx) is True

    def test_applies_false_when_no_run_dir(self, make_ctx, monkeypatch):
        """applies=False when run_dir is None."""
        monkeypatch.setenv("SIMPLICIO_247_VIDEO_EVIDENCE", "1")
        ctx = make_ctx(run_dir=None)
        assert video_evidence.applies(ctx) is False


class TestVideoEvidenceRun:
    """Test the run() async function."""

    def test_run_success_with_video(self, make_ctx, tmp_path, monkeypatch):
        """run returns ok with artifact path in evidence."""
        async def test():
            web_verify_dir = tmp_path / "web_verify"
            web_verify_dir.mkdir()
            (web_verify_dir / "1-web.png").write_text("fake image")
            
            ctx = make_ctx(run_dir=tmp_path)
            
            # Mock proc.run to return success
            async def mock_run(argv, **kw):
                result = MagicMock()
                result.returncode = 0
                result.stdout = "done"
                result.stderr = ""
                return result
            
            monkeypatch.setattr("simplicio_loop.watcher247.points.video_evidence.proc.run", mock_run)
            
            result = await video_evidence.run(ctx)
            assert result.status == "ok"
            assert "artifact" in result.evidence
            assert result.name == "video_evidence"
        
        asyncio.run(test())

    def test_run_script_missing_returns_skipped(self, make_ctx, tmp_path, monkeypatch):
        """run returns skipped when script not found."""
        async def test():
            web_verify_dir = tmp_path / "web_verify"
            web_verify_dir.mkdir()
            (web_verify_dir / "1-web.png").write_text("fake image")
            
            ctx = make_ctx(run_dir=tmp_path)
            
            # Mock proc.run to raise
            async def mock_run(argv, **kw):
                raise FileNotFoundError("python3 not found")
            
            monkeypatch.setattr("simplicio_loop.watcher247.points.video_evidence.proc.run", mock_run)
            
            result = await video_evidence.run(ctx)
            assert result.status == "skipped"
            assert result.reason_code == "script_unavailable"
        
        asyncio.run(test())

    def test_run_no_run_dir_returns_skipped(self, make_ctx):
        """run returns skipped when run_dir is None."""
        async def test():
            ctx = make_ctx(run_dir=None)
            result = await video_evidence.run(ctx)
            assert result.status == "skipped"
            assert result.reason_code == "no_run_dir"
        
        asyncio.run(test())

    def test_run_skipped_by_script_returns_skipped(self, make_ctx, tmp_path, monkeypatch):
        """run returns skipped when script returns exit code 3."""
        async def test():
            web_verify_dir = tmp_path / "web_verify"
            web_verify_dir.mkdir()
            (web_verify_dir / "1-web.png").write_text("fake image")
            
            ctx = make_ctx(run_dir=tmp_path)
            
            # Mock proc.run to return exit code 3 (skipped)
            async def mock_run(argv, **kw):
                result = MagicMock()
                result.returncode = 3
                result.stdout = "skipped: no video source"
                result.stderr = ""
                return result
            
            monkeypatch.setattr("simplicio_loop.watcher247.points.video_evidence.proc.run", mock_run)
            
            result = await video_evidence.run(ctx)
            assert result.status == "skipped"
            assert result.reason_code == "generation_skipped"
        
        asyncio.run(test())


class TestVideoEvidenceContract:
    """Test integration with the points contract."""

    def test_video_evidence_registered(self):
        """video_evidence must be registered in the points registry."""
        infos = points.registered(stage="pr")
        assert any(info.name == "video_evidence" for info in infos), "video_evidence not registered at pr stage"

    def test_video_evidence_conditional(self):
        """video_evidence must be conditional (have applies function)."""
        infos = points.registered(stage="pr")
        video_evidence_info = next(i for i in infos if i.name == "video_evidence")
        assert video_evidence_info.conditional, "video_evidence must be conditional"

    def test_contract_skipped_when_applies_false(self, point_contract, make_ctx, monkeypatch):
        """video_evidence point is skipped when applies returns False."""
        monkeypatch.delenv("SIMPLICIO_247_VIDEO_EVIDENCE", raising=False)
        ctx = make_ctx(run_dir=None)
        
        result = point_contract("video_evidence", ctx, expect="skipped")
        assert result.reason_code == "not_applicable"
