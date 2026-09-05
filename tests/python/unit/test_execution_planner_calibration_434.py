from __future__ import annotations

import json

from simplicio_mapper.mapper.execution_planner import AUTO_CALIBRATION_ENV, plan_execution


def test_auto_consumes_calibration_when_sync_is_proven_faster(tmp_path, monkeypatch) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps({"profiles": {"sync": {"p95_ms": 8}, "async": {"p95_ms": 12}}}), encoding="utf-8")
    monkeypatch.setenv(AUTO_CALIBRATION_ENV, str(path))
    plan = plan_execution(440, 5)
    assert plan.selected_profile == "sync"
    assert plan.source == "calibration"


def test_invalid_calibration_keeps_safe_existing_route(tmp_path, monkeypatch) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not-json", encoding="utf-8")
    monkeypatch.setenv(AUTO_CALIBRATION_ENV, str(path))
    plan = plan_execution(440, 5)
    assert plan.selected_profile == "sync"
