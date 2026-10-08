"""End-to-end benchmark test of the virtualized ``sl-log-viewer`` with 100 000 lines (issue #1405).

Runs ``scripts/benchmark_log_viewer.py`` in a real Chromium. Requires the optional e2e extra
(``pip install -e ".[e2e]"``) and a Chromium; otherwise it skips. The thresholds are loose on purpose (the
measured numbers are far below them): they catch a return to rendering every line, which took about 20 s and
100 000 DOM rows before the viewer was virtualized.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="optional e2e extra: pip install -e '.[e2e]'")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_log_viewer.py"
LINES = 100_000


@pytest.fixture(scope="module")
def result():
    spec = importlib.util.spec_from_file_location("benchmark_log_viewer", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.run(LINES)
    except Exception as exc:  # no usable browser binary
        if "Executable doesn't exist" in str(exc) or "chromium" in str(exc).lower():
            pytest.skip("no Chromium available: " + str(exc).splitlines()[0])
        raise


def test_only_the_visible_rows_are_in_the_dom(result):
    assert result["lines"] == LINES
    assert result["dom_rows"] < 200
    assert result["dom_nodes_total"] < 400


def test_rendering_100k_lines_stays_interactive(result):
    for key in ("render_ms", "follow_ms", "scroll_mid_ms", "filter_errors_ms", "search_ms"):
        assert result[key] < 2000, (key, result)


def test_follow_reaches_the_end_and_scrolling_shows_the_right_line(result):
    assert result["at_end"] is True
    assert result["mid_row_found"] is True


def test_filter_and_search_count_the_whole_set_but_render_a_window(result):
    assert result["count_label"] == "1031 linhas"
    assert result["filter_rows"] < 200
    assert result["search_rows"] == 1
