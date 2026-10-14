"""End-to-end benchmark test of the virtualized ``sl-diff-view`` with a 50 000-line diff.

Runs ``scripts/benchmark_diff_view.py`` in a real Chromium. Requires the optional e2e extra
(``pip install -e ".[e2e]"``) and a Chromium; otherwise it skips. The thresholds are loose on purpose (the measured
numbers are far below them): they catch a return to rendering every row, which made a 50 000-line diff freeze the
page before the viewer was virtualized.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip(
    "playwright.sync_api", reason="optional e2e extra: pip install -e '.[e2e]'"
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_diff_view.py"
LINES = 50_000
FILES = 100


def _load():
    spec = importlib.util.spec_from_file_location("benchmark_diff_view", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _measure(module, lines: int, files: int):
    try:
        return module.run(lines, files)
    except Exception as exc:  # no usable browser binary
        if "Executable doesn't exist" in str(exc) or "chromium" in str(exc).lower():
            pytest.skip("no Chromium available: " + str(exc).splitlines()[0])
        raise


@pytest.fixture(scope="module")
def result():
    return _measure(_load(), LINES, FILES)


@pytest.fixture(scope="module")
def small():
    return _measure(_load(), 800, 8)


def test_only_the_visible_rows_are_in_the_dom(result):
    assert result["lines"] == LINES
    assert result["virtual"] is True
    assert result["table_rows"] == 0
    assert result["dom_rows"] < 300
    assert result["dom_nodes_total"] < 700


def test_the_rest_of_the_diff_is_a_spacer_and_the_summary_counts_everything(result):
    assert result["spacer_bottom_px"] > 0
    assert result["summary"] == "49700 linhas, 100 arquivos"


def test_rendering_a_50k_line_diff_stays_interactive(result):
    for key in ("render_ms", "scroll_mid_ms"):
        assert result[key] < 2000, (key, result)


def test_scrolling_to_the_middle_shows_the_expected_row(result):
    assert result["mid_row_found"] is True


def test_a_small_diff_keeps_the_plain_table(small):
    assert small["virtual"] is False
    assert small["table_rows"] > 0
    assert small["dom_rows"] == 768
    assert small["mid_row_found"] is True
