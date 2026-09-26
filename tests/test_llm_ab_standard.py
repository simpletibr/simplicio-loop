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
