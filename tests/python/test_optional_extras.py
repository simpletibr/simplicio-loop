"""#99 — heavy ML/provider deps live behind pip extras, not the base install.

Covers the actionable-error contract for each extra (`providers`, `ml`,
`local`, `bench`) and cross-checks pyproject.toml so the extras graph can't
silently drift from what the code actually imports. `local`'s own
actionable-error tests already live in test_providers_local.py
(`test_resolve_local_path_no_hf_lib_raises`, `test_local_llama_missing_backend_raises`);
this file adds the same pattern for `providers` (openai/anthropic) and `ml`
(sentence-transformers), plus the base/optional-dependencies audit.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: tomllib is stdlib only from 3.11+
    import tomli as tomllib  # type: ignore[no-redef]

import pytest

from simplicio import precedent, providers

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _load_pyproject():
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# providers extra: openai / anthropic
# --------------------------------------------------------------------------- #


def test_import_openai_missing_raises_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(SystemExit) as exc:
        providers._import_openai()
    assert "openai" in str(exc.value)
    assert "simplicio-cli[providers]" in str(exc.value)


def test_import_anthropic_missing_raises_actionable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(SystemExit) as exc:
        providers._import_anthropic()
    assert "anthropic" in str(exc.value)
    assert "simplicio-cli[providers]" in str(exc.value)


def test_generate_native_anthropic_path_missing_sdk_is_actionable(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_MODEL", "claude-opus-4-7")
    monkeypatch.setenv("SIMPLICIO_API_KEY", "x")
    monkeypatch.delenv("SIMPLICIO_BASE_URL", raising=False)
    monkeypatch.setenv("SIMPLICIO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setitem(sys.modules, "anthropic", None)
    from simplicio._cache import reset_for_tests

    reset_for_tests()
    with pytest.raises(SystemExit) as exc:
        providers.generate("do a thing")
    assert "simplicio-cli[providers]" in str(exc.value)
    reset_for_tests()


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
        req.split(">=")[0].split("==")[0].split("[")[0].strip()
        for req in data["project"]["dependencies"]
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
    assert {"providers", "ml", "local", "bench", "all"} <= extras.keys()

    def _names(group):
        return {
            req.split(">=")[0].split("==")[0].split("[")[0].strip()
            for req in extras[group]
            if not req.startswith("simplicio-cli[")
        }

    assert _names("providers") == {"anthropic", "openai"}
    assert _names("ml") == {"sentence-transformers"}
    assert _names("local") == {"llama-cpp-python", "huggingface-hub"}
    assert _names("bench") == {"fpdf2"}
    # `all` is a union expressed via self-referential extras, not a flat list.
    assert all(req.startswith("simplicio-cli[") for req in extras["all"])
    referenced = {req.split("[", 1)[1].rstrip("]") for req in extras["all"]}
    assert referenced == {"providers", "ml", "bench", "local"}
