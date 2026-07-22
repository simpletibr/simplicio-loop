from __future__ import annotations

import re
from pathlib import Path

from scripts import coverage_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_ci_invokes_blocking_coverage_gate_on_main_pushes_and_prs() -> None:
    workflow = _read(".github/workflows/ci.yml")
    flattened = " ".join(workflow.split())

    assert re.search(r"push:\s*\n\s*branches: \[main\]", workflow)
    assert re.search(r"pull_request:\s*\n\s*branches: \[main\]", workflow)
    assert "pytest --cov=simplicio" in flattened
    assert "--cov-report=json:coverage.json" in flattened
    assert "python3 scripts/coverage_gate.py --report coverage.json" in workflow
    assert "continue-on-error" not in workflow


def test_documented_thresholds_equal_enforced_thresholds() -> None:
    global_floor, critical_floor, critical_modules = coverage_gate._load_config()
    gate_docs = _read("docs/ci-quality-gate.md")

    assert global_floor == 85
    assert critical_floor == 90
    assert critical_modules
    assert f"fail_under = {global_floor:.0f}" in gate_docs
    assert f"must clear {critical_floor:.0f}%" in gate_docs


def test_coverage_gate_rejects_reports_below_either_floor() -> None:
    modules = ["simplicio/cli.py"]
    low_global = {
        "totals": {"percent_covered": 84.99},
        "files": {modules[0]: {"summary": {"percent_covered": 100}}},
    }
    low_critical = {
        "totals": {"percent_covered": 100},
        "files": {modules[0]: {"summary": {"percent_covered": 89.99}}},
    }

    assert coverage_gate.evaluate(low_global, 85, 90, modules)[0] is False
    assert coverage_gate.evaluate(low_critical, 85, 90, modules)[0] is False


def test_documented_workflow_references_exist() -> None:
    audited_paths = [
        REPO_ROOT / name
        for name in (
            "AGENTS.md",
            "CLAUDE.md",
            "DOD.md",
            "README.md",
            "INSTALL.md",
            "INIT.md",
            "_BOOTSTRAP.md",
        )
    ]
    audited_paths.extend(
        source for source in (REPO_ROOT / "docs").rglob("*.md") if "evidence" not in source.parts
    )
    audited_paths.extend((REPO_ROOT / "tests").rglob("*.py"))
    audited_paths.extend((REPO_ROOT / "tests").rglob("*.js"))
    audited_paths.extend(REPO_ROOT / name for name in ("bootstrap.sh", "bootstrap.ps1"))

    reference = re.compile(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml")
    missing: list[str] = []
    for source in audited_paths:
        for workflow in reference.findall(source.read_text(encoding="utf-8")):
            if not (REPO_ROOT / workflow).is_file():
                missing.append(f"{source.relative_to(REPO_ROOT)} -> {workflow}")

    assert missing == []


def test_local_hooks_cover_posix_and_windows() -> None:

    for hook in (".claude/hooks/pre-commit.sh", ".claude/hooks/pre-commit.ps1"):
        text = _read(hook)
        assert "ruff check ." in text
        assert "pytest -q" in text
        assert "--cov=simplicio" in text
        assert "--cov-fail-under=85" in text
        assert "scripts/check_json_boundaries.py --strict" in text


def test_local_gate_documents_all_repository_guards() -> None:
    gate = _read("docs/ci-quality-gate.md")

    assert "ruff check ." in gate
    assert "ruff format --check ." in gate
    assert "mypy simplicio" in gate
    assert "pytest --cov=simplicio" in gate
    assert "scripts/coverage_gate.py --report coverage.json" in gate
    assert "scripts/token_budget.py --check" in gate
    assert "scripts/gen_package_interdependence.py --check" in gate
    assert "python -m build" in gate
    assert "python -m twine check dist/*" in gate
