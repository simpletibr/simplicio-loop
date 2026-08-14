from __future__ import annotations

import os
from pathlib import Path

from simplicio.pipeline_stages import _configured_test_command, _infer_test_command


def test_infer_pytest_from_python_layout(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    assert _infer_test_command(tmp_path) == "pytest -q"


def test_infer_pytest_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths=['tests']\n", encoding="utf-8")
    assert _infer_test_command(tmp_path) == "pytest -q"


def test_configured_command_prefers_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "custom-test")
    command, error = _configured_test_command(tmp_path)
    assert command == "custom-test"
    assert error is None


def test_configured_command_infers_when_env_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    command, error = _configured_test_command(tmp_path)
    assert command == "pytest -q"
    assert error is None


def test_configured_command_still_fails_closed_without_repo_signal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    command, error = _configured_test_command(tmp_path)
    assert command is None
    assert error is not None
    assert "SIMPLICIO_TEST_CMD" in error


def test_live_qlt001_operational_script() -> None:
    repo = Path(os.environ.get("SIMPLICIO_QLT001_REPO", Path(__file__).resolve().parents[2].parent / "simplicio-loop-quality"))
    if not (repo / "src" / "simplicio_loop_quality" / "loop_invoker.py").is_file():
        import pytest

        pytest.skip("simplicio-loop-quality sibling is not checked out")
    from scripts.qlt001_devcli_operational_flow import run_flow

    report = run_flow(repo)
    assert report["status"] == "pass", report
    required = {
        "devcli_smoke",
        "devcli_inspect_mapper",
        "devcli_verify_only_inferred",
        "devcli_task_no_contract_receipt",
        "devcli_mechanical_edit_no_contract",
        "devcli_changeset_standalone",
        "mapper_default_route",
        "fast_query_after_mapper",
        "loop_preflight_devcli_bound",
    }
    assert required.issubset({step["name"] for step in report["steps"]})
