"""Langfuse e opcional e nao tem extra de instalacao (issue #1595)."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_nao_define_o_extra_langfuse() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]
    assert "langfuse" not in extras


def test_docs_nao_mandam_instalar_o_extra_langfuse() -> None:
    for name in ("LANGFUSE.md", "A2A_SPIKE.md"):
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert "simplicio-loop[langfuse]" not in text, name
        assert "[langfuse]" not in text, name
