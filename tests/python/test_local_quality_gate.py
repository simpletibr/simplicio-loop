from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_actions_stay_removed_and_local_hooks_cover_posix_and_windows() -> None:
    assert not (REPO_ROOT / ".github" / "workflows").exists()

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
