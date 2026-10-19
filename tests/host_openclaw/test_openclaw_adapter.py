"""OpenClaw adapter: its `.agents/skills` copy is detected, its loop is the native scheduler, and the planner lands it."""
from __future__ import annotations

import importlib
from pathlib import Path

from simplicio_loop.install import planner

adapter = importlib.import_module("adapters.openclaw.adapter")


def test_detects_the_agents_skills_copy_only_when_it_is_present(tmp_path: Path) -> None:
    assert adapter.detect(tmp_path)["detected"] is False
    skills = tmp_path / ".agents" / "skills" / "simplicio-loop"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("loop\n", encoding="utf-8")
    found = adapter.detect(tmp_path)
    assert found["detected"] is True and ".agents/skills" in found["signals"]


def test_reports_the_native_scheduler_and_marks_it_unverified_here() -> None:
    caps = adapter.capabilities()
    assert caps["host"] == "openclaw" and caps["loop_drive"] == "native_scheduler"
    assert caps["native_interception"] is False and caps["live_status"] == "UNVERIFIED"


def test_the_planner_lands_the_surface_the_adapter_verifies(tmp_path: Path) -> None:
    planner.apply_plan(planner.plan_install(tmp_path, host="openclaw"))
    assert adapter.verify(tmp_path)["verified"] is True
