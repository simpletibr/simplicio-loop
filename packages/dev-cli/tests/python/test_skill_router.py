from __future__ import annotations

import numpy as np

from simplicio import skill_router


class _StubEmbedder:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def encode(self, texts, show_progress_bar=False):
        self.calls.append(list(texts))
        return np.asarray([self.vectors[text] for text in texts], dtype=float)


def test_build_skill_block_returns_empty_without_skills(tmp_path):
    assert skill_router.build_skill_block(str(tmp_path), "task") == ""


def test_build_skill_block_returns_top_match(tmp_path, monkeypatch):
    skills_dir = tmp_path / ".mapper" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "auth.md").write_text("# auth\nuse auth flow\n", encoding="utf-8")
    (skills_dir / "billing.md").write_text("# billing\nuse billing flow\n", encoding="utf-8")
    stub = _StubEmbedder(
        {
            "auth": [1.0, 0.0],
            "billing": [0.0, 1.0],
            "login task": [1.0, 0.0],
        }
    )
    monkeypatch.setattr("simplicio.precedent._embedder", lambda: stub)

    block = skill_router.build_skill_block(str(tmp_path), "login task")

    assert "# auth.md" in block
    assert "match 1.00" in block
    assert len(stub.calls) == 2


def test_build_skill_block_respects_threshold(tmp_path, monkeypatch):
    skills_dir = tmp_path / ".mapper" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "auth.md").write_text("# auth\nuse auth flow\n", encoding="utf-8")
    stub = _StubEmbedder({"auth": [1.0, 0.0], "other": [0.0, 1.0]})
    monkeypatch.setattr("simplicio.precedent._embedder", lambda: stub)

    block = skill_router.build_skill_block(str(tmp_path), "other", threshold=1.01)

    assert block == ""


def test_build_skill_block_handles_zero_norm_vectors(tmp_path, monkeypatch):
    skills_dir = tmp_path / ".mapper" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "empty.md").write_text("# empty\nnone\n", encoding="utf-8")
    stub = _StubEmbedder({"empty": [0.0, 0.0], "task": [0.0, 0.0]})
    monkeypatch.setattr("simplicio.precedent._embedder", lambda: stub)

    block = skill_router.build_skill_block(str(tmp_path), "task")

    assert block == ""
