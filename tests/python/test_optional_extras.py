"""#99 — optional ML/benchmark deps stay out of the base install.

Cross-checks pyproject.toml so the extras graph cannot silently drift from
what the deterministic CLI actually imports. Provider and local-model extras
must remain absent because ``simplicio-py`` never executes or provisions an
LLM.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: tomllib is stdlib only from 3.11+
    import tomli as tomllib  # type: ignore[no-redef]

import pytest

from simplicio import precedent

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _load_pyproject():
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# No provider or local-model extras
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# ml extra: sentence-transformers
# --------------------------------------------------------------------------- #


def test_embedder_missing_sentence_transformers_is_actionable(monkeypatch):
    precedent._emb = None
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(SystemExit) as exc:
        precedent._embedder()
    assert "sentence-transformers" in str(exc.value)
    assert "simplicio-cli[ml]" in str(exc.value)


# --------------------------------------------------------------------------- #
# pyproject.toml audit — base stays free of heavy/optional deps
# --------------------------------------------------------------------------- #

_HEAVY_OR_OPTIONAL = {
    "sentence-transformers",
    "openai",
    "anthropic",
    "llama-cpp-python",
    "huggingface-hub",
    "fpdf2",
}


def test_base_dependencies_exclude_heavy_and_provider_packages():
    data = _load_pyproject()
    base_names = {
        req.split(">=")[0].split("==")[0].split("[")[0].strip() for req in data["project"]["dependencies"]
    }
    overlap = base_names & _HEAVY_OR_OPTIONAL
    assert not overlap, f"heavy/optional packages leaked into base deps: {overlap}"
    # numpy is a deliberate exception: cache.py/precedent.py/skill_router.py
    # import it unconditionally for cosine-similarity ranking even without
    # the sentence-transformers embedding model, so the core task/run
    # pipeline needs it in base. See the comment above [project.dependencies].
    assert "numpy" in base_names


def test_optional_dependencies_groups_match_actual_imports():
    data = _load_pyproject()
    extras = data["project"]["optional-dependencies"]
    assert {"ml", "bench", "fast", "performance", "all"} <= extras.keys()
    assert "providers" not in extras
    assert "local" not in extras

    def _names(group):
        return {
            req.split(">=")[0].split("==")[0].split("[")[0].strip()
            for req in extras[group]
            if not req.startswith("simplicio-cli[")
        }

    assert _names("ml") == {"sentence-transformers"}
    assert _names("bench") == {"fpdf2"}
    assert _names("performance") == {"uvloop"}
    # `all` is a union expressed via self-referential extras, not a flat list.
    assert all(req.startswith("simplicio-cli[") for req in extras["all"])
    referenced = {req.split("[", 1)[1].rstrip("]") for req in extras["all"]}
    assert referenced == {"ml", "bench", "performance"}
