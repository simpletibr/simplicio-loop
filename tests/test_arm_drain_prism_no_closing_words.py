"""The drain scratchpad must never tell a worker to write a GitHub closing word (#1644)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from simplicio_loop.watcher247.closing_words import has_closing

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "arm_drain_prism.py"


def _load():
    spec = importlib.util.spec_from_file_location("arm_drain_prism_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_drain_scratchpad_uses_parte_de_and_no_closing_word(tmp_path, monkeypatch):
    module = _load()
    monkeypatch.setattr(module, "_open_issue_count", lambda repo: 3)
    receipt = module.arm(tmp_path, slots=1)
    text = Path(receipt["scratchpad"]).read_text(encoding="utf-8")
    assert "Parte de #N" in text
    assert not has_closing(text)


def test_script_source_has_no_closing_word_before_issue_number():
    source = SCRIPT.read_text(encoding="utf-8")
    assert not has_closing(source)
