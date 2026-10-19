"""Aider adapter: its config and conventions file are detected, its loop is self-paced, and the planner lands them."""
from __future__ import annotations

import importlib
from pathlib import Path

from simplicio_loop.install import planner

adapter = importlib.import_module("adapters.aider.adapter")


def test_detects_the_aider_config_only_when_it_is_present(tmp_path: Path) -> None:
    assert adapter.detect(tmp_path)["detected"] is False
    (tmp_path / ".aider.conf.yml").write_text("read:\n  - CONVENTIONS.md\n", encoding="utf-8")
    found = adapter.detect(tmp_path)
    assert found["detected"] is True and ".aider.conf.yml" in found["signals"]


def test_reports_a_self_paced_loop_and_no_native_hook() -> None:
    caps = adapter.capabilities()
    assert caps["host"] == "aider" and caps["loop_drive"] == "self_paced"
    assert caps["native_interception"] is False and caps["live_status"] == "UNVERIFIED"


def test_the_planner_lands_the_surface_the_adapter_verifies(tmp_path: Path) -> None:
    planner.apply_plan(planner.plan_install(tmp_path, host="aider"))
    assert adapter.verify(tmp_path)["verified"] is True
