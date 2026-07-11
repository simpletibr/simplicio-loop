from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _workflow_text(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_publish_workflow_waits_for_ci_and_runs_release_gate_checks() -> None:
    workflow = _workflow_text("publish-pypi.yml")

    assert "workflow_run:" in workflow
    assert 'workflows: ["CI"]' in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "python bench/run_delivery_corpus.py" in workflow
    assert "python scripts/gen_package_interdependence.py --check" in workflow
    assert "ruff check ." in workflow
    assert "mypy simplicio" in workflow


def test_starter_harness_workflow_matches_repo_package_scripts() -> None:
    workflow = _workflow_text("starter-e2e.yml")

    assert "Starter Kit E2E Harness (non-gating)" in workflow
    assert "paths:" in workflow
    assert '"package.json"' in workflow
    assert '"tests/e2e/**"' in workflow
    assert "npm run lint" not in workflow
    assert "npm test -- --coverage" not in workflow
    assert "npm run test:e2e" in workflow
    assert "Verify harness scripts declared in package.json" in workflow
