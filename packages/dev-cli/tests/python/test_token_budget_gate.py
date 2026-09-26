from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_token_budget_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "token_budget.py"
    spec = importlib.util.spec_from_file_location("token_budget_script", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_token_budget_normalizes_mapper_artifact_paths(tmp_path):
    module = _load_token_budget_module()
    artifact = tmp_path / ".simplicio-loop" / "project-map.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}", encoding="utf-8")

    discovered = module.discover_mapper_artifacts(tmp_path)

    assert discovered == [("mapper artifact (project-map.json)", ".simplicio-loop/project-map.json")]


def test_token_budget_tracks_extracted_pipeline_stage_and_current_thresholds():
    module = _load_token_budget_module()
    estimate_fn, estimator_id = module.get_estimator()
    baseline = module.load_baseline()

    tracked = dict(module.TRACKED_ARTIFACTS)
    assert tracked["pipeline_stages.py"] == "simplicio/pipeline_stages.py"
    assert "simplicio/pipeline_stages.py" in baseline["artifacts"]

    measurements = module.measure(
        estimate_fn,
        repo=module.REPO,
        artifacts=[
            ("pipeline.py", "simplicio/pipeline.py"),
            ("pipeline_stages.py", "simplicio/pipeline_stages.py"),
        ],
    )

    assert module.report(measurements, baseline, estimator_id, quiet=True) is True
