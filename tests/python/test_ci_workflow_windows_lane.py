from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_keeps_linux_python_gate_and_adds_windows_pipeline_slice():
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "python:\n" in workflow
    assert "name: Python package (${{ matrix.python-version }})" in workflow
    assert "runs-on: ubuntu-latest" in workflow

    assert "windows-pipeline:\n" in workflow
    assert "name: Windows token-budget + pipeline slice" in workflow
    assert "runs-on: windows-latest" in workflow
    assert 'python-version: "3.11"' in workflow
    assert "python scripts/token_budget.py --check" in workflow
    assert "tests/python/test_token_budget_gate.py" in workflow
    assert "tests/python/test_pipeline_task_result.py" in workflow
    assert "tests/python/test_pipeline_fixers.py" in workflow
    assert "tests/python/test_prompt_retry_flow.py" in workflow
