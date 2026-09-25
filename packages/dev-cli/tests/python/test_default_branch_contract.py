from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_live_branch_references_target_main() -> None:
    assert "origin/main..." in _read("scripts/check_integration_claims.py")

    for readme in ("README.md", "README.pt-BR.md"):
        text = _read(readme)
        assert "simplicio-dev-cli/main/output/" in text
        assert "simplicio-dev-cli/master/output/" not in text

    for instructions in ("AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md"):
        text = _read(instructions)
        assert "`main` limpa e sincronizada com `origin/main`" in text
        assert "`master` preservada apenas como compatibilidade" in text


def test_local_gate_declares_main_as_default_and_master_as_compatibility() -> None:
    gate = _read("docs/ci-quality-gate.md")

    assert "Pull requests target\n`main`" in gate
    assert "`master` branch is compatibility-only" in gate
