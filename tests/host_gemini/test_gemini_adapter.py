"""Gemini adapter: its GEMINI.md is detected, its loop is self-paced, and the planner lands what it verifies."""
from __future__ import annotations

import importlib
from pathlib import Path

from simplicio_loop.install import planner

adapter = importlib.import_module("adapters.gemini.adapter")


def test_detects_the_context_file_only_when_it_is_present(tmp_path: Path) -> None:
    assert adapter.detect(tmp_path)["detected"] is False
    (tmp_path / "GEMINI.md").write_text("context\n", encoding="utf-8")
    found = adapter.detect(tmp_path)
    assert found["detected"] is True and "GEMINI.md" in found["signals"]


def test_reports_a_self_paced_loop_and_no_native_hook() -> None:
    caps = adapter.capabilities()
    assert caps["host"] == "gemini" and caps["loop_drive"] == "self_paced"
    assert caps["native_interception"] is False and caps["live_status"] == "UNVERIFIED"


def test_the_planner_lands_the_surface_the_adapter_verifies(tmp_path: Path) -> None:
    planner.apply_plan(planner.plan_install(tmp_path, host="gemini"))
    assert adapter.verify(tmp_path)["verified"] is True
