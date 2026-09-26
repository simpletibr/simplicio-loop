"""TDD unit tests for bench/llm_ab/standard.py -- the canonical benchmark
matrix runner (issue #1310 follow-up). Only the pure, side-effect-free
pieces are exercised here: no real LLM call is ever made from a test.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import standard  # noqa: E402


def test_matrix_covers_tasks_1_and_4_sequential_and_batch():
    combos = {(m["tasks"], m["batch"]) for m in standard.MATRIX}
    assert combos == {(1, False), (1, True), (4, False), (4, True)}


def test_suffix_for_sequential_has_no_batch_marker():
    assert standard.suffix_for(1, False) == "t1"
    assert standard.suffix_for(4, False) == "t4"


def test_suffix_for_batch_has_batch_marker():
    assert standard.suffix_for(1, True) == "t1-batch"
    assert standard.suffix_for(4, True) == "t4-batch"


def test_every_matrix_combo_has_a_distinct_suffix():
    suffixes = {standard.suffix_for(m["tasks"], m["batch"]) for m in standard.MATRIX}
    assert len(suffixes) == len(standard.MATRIX)


def test_build_arg_parser_defaults():
    ap = standard.build_arg_parser()
    args = ap.parse_args([])
    assert args.keys_file is None
    assert args.max_turns == 30
    assert args.cmd_timeout == 180
    assert args.out.endswith(os.path.join("llm_ab", "results"))


def test_build_arg_parser_accepts_keys_file():
    ap = standard.build_arg_parser()
    args = ap.parse_args(["--keys-file", "/tmp/keys.env"])
    assert args.keys_file == "/tmp/keys.env"


def test_build_index_links_every_written_report():
    written = [
        ("t1", "/out/2026-09-26-abc-t1.json", "/repo/bench/llm_ab/REPORT-t1.html"),
        ("t1-batch", "/out/2026-09-26-abc-t1-batch.json", "/repo/bench/llm_ab/REPORT-t1-batch.html"),
    ]
    html = standard.build_index(written)
    assert "REPORT-t1.html" in html
    assert "REPORT-t1-batch.html" in html
    assert "2026-09-26-abc-t1.json" in html
    assert "<html" in html


def test_build_index_handles_empty_matrix_without_crashing():
    html = standard.build_index([])
    assert "<html" in html


def test_build_index_has_summary_with_create_and_edit_rows():
    def task(i, kind, cost, turns, wall):
        return {"index": i, "kind": kind, "success": True, "turns": turns, "wall_s": wall,
                "totals": {"cost_usd": cost, "prompt_tokens": 10, "cached_tokens": 5}}
    res = {"meta": {"batch": False}, "arms": {
        "normal": {"tasks": [task(1, "create", 0.001, 5, 10.0), task(2, "edit", 0.002, 6, 12.0)]},
        "simplicio": {"tasks": [task(1, "create", 0.003, 7, 20.0), task(2, "edit", 0.001, 3, 6.0)]},
    }}
    html = standard.build_index([("t2", "r.json", "REPORT-t2.html")], {"t2": res})
    assert "Resumo" in html
    assert "t2 · edição" in html and "t2 · criação" in html
    assert "$0.00100" in html  # simplicio edit cost


def test_summary_rows_are_cache_aware():
    """Every summary row shows cache hit %, the no-cache (list price) cost and
    the $ saved by the cache, priced from the run's own pricing snapshot."""
    pricing = {"available": True, "prompt": 0.00000014, "completion": 0.00000042,
               "input_cache_read": 0.0000000042}

    def task(kind, prompt, cached, compl, cost):
        return {"index": 1, "kind": kind, "success": True, "turns": 2, "wall_s": 1.0,
                "totals": {"cost_usd": cost, "prompt_tokens": prompt,
                           "cached_tokens": cached, "completion_tokens": compl}}
    res = {"meta": {"batch": True, "pricing": pricing}, "arms": {
        "normal": {"tasks": [task("create", 1_000_000, 0, 0, 0.14)]},
        "simplicio": {"tasks": [task("create", 1_000_000, 500_000, 0, 0.0721)]},
    }}
    row = standard.summary_rows("t1-batch", res)[0]
    assert "50.0%" in row          # simplicio cache hit
    assert "$0.14000" in row       # simplicio no-cache cost (1M prompt at list price)
    assert "$0.06790" in row       # simplicio cache savings: 500k * (0.14 - 0.0042)/1M


def test_build_markdown_report_has_summary_create_edit_and_cache():
    pricing = {"available": True, "prompt": 0.00000014, "completion": 0.00000042,
               "input_cache_read": 0.0000000042}

    def task(i, kind, cost):
        return {"index": i, "kind": kind, "success": True, "turns": 3, "wall_s": 2.0,
                "totals": {"cost_usd": cost, "prompt_tokens": 1000, "cached_tokens": 500,
                           "completion_tokens": 10}}
    res = {"meta": {"batch": False, "pricing": pricing, "model": "m", "main_commit": "abc"},
           "arms": {"normal": {"tasks": [task(1, "create", 0.001), task(2, "edit", 0.002)]},
                    "simplicio": {"tasks": [task(1, "create", 0.0005), task(2, "edit", 0.001)]}}}
    md = standard.build_markdown([("t2", "results/r.json", "REPORT-t2.html")], {"t2": res})
    assert md.startswith("# ")
    assert "| t2 · criação |" in md and "| t2 · edição |" in md
    assert "cache hit" in md and "50.0%" in md
    assert "$0.00150 (50.0%)" in md  # total savings: 0.003 -> 0.0015


def test_build_full_html_joins_summary_and_every_report_with_page_breaks():
    index = "<html><head><style>a{}</style></head><body><h1>Resumo</h1></body></html>"
    reports = {
        "t1": "<html><head><style>.x{color:red}</style></head><body><h1>R1</h1><img src='data:image/png;base64,AA'></body></html>",
        "t4": "<html><head><style>.x{color:red}</style></head><body><h1>R4</h1></body></html>",
    }
    full = standard.build_full_html(index, reports)
    assert full.count("page-break-before") >= 2
    assert "Resumo" in full and "R1" in full and "R4" in full
    assert "data:image/png;base64,AA" in full  # charts carried over
    assert ".x{color:red}" in full


def test_find_chromium_honors_env(monkeypatch, tmp_path):
    fake = tmp_path / "chrome"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("SIMPLICIO_BENCH_CHROMIUM", str(fake))
    assert standard.find_chromium() == str(fake)
