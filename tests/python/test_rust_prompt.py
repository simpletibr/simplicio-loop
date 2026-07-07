"""Issue #17 / #18: Rust extension parity + smoke.

These tests are skipped automatically when the Rust extension is not
installed (e.g. a pip-only install without `maturin develop`).
"""

from __future__ import annotations

import pytest

simplicio_core = pytest.importorskip(
    "simplicio_core",
    reason="rust extension not installed; build with maturin develop --release",
)

import os  # noqa: E402

from simplicio.prompt import _assemble_python, _load_template  # noqa: E402


def _template_path() -> str:
    import simplicio

    return os.path.join(os.path.dirname(simplicio.__file__), "templates", "simplicio_prompt.md")


def test_hello_smoke():
    assert simplicio_core.hello("rust") == "hello, rust!"


def test_substitution_parity_basic():
    tpl = _load_template(_template_path())
    args = ("angular", "g", "tgt", "pre", "sk", "ad", "cr", "co")
    rs = simplicio_core.build_6layer_prompt(tpl, *args)
    py = _assemble_python(tpl, *args)
    assert rs == py


def test_substitution_parity_utf8_em_dash():
    # The real 6-layer template contains an em-dash; make sure the rust
    # walker does not corrupt multibyte UTF-8.
    tpl = "Header — note\n{{GOAL}}\n{# strip me #}\nTail — end"
    rs = simplicio_core.build_6layer_prompt(tpl, "stack", "MY GOAL", "t", "p", "s", "a", "c", "co")
    assert "—" in rs
    assert "MY GOAL" in rs
    assert "strip me" not in rs


def test_substitution_unknown_placeholder_passthrough():
    tpl = "real {{GOAL}} and unknown {{NOT_A_PLACEHOLDER}} keep"
    rs = simplicio_core.build_6layer_prompt(tpl, "stack", "X", "t", "p", "s", "a", "c", "co")
    assert "real X and unknown {{NOT_A_PLACEHOLDER}} keep" == rs


def test_comment_strip_multiline():
    tpl = "before\n{# multi\nline\ncomment #}\nafter"
    rs = simplicio_core.build_6layer_prompt(tpl, "stack", "g", "t", "p", "s", "a", "c", "co")
    assert rs == "before\n\nafter"
