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


# -- 7-arm ablation matrix (issue #1337) -------------------------------------

PRICING = {
    "available": True, "prompt": 1e-6, "completion": 2e-6,
    "input_cache_read": 5e-7, "input_cache_write": None, "internal_reasoning": None,
}


def _task(kind, success, turns, wall, prompt, cached, completion):
    return {
        "kind": kind, "success": success, "turns": turns, "wall_s": wall,
        "totals": {
            "prompt_tokens": prompt, "cached_tokens": cached, "completion_tokens": completion,
            "cost_usd": 0.0, "cost_source": "computed-from-tokens",
        },
    }


def _ablation_results(arms_tasks: dict[str, list[dict]]) -> dict:
    return {"meta": {"pricing": PRICING}, "arms": {a: {"tasks": t} for a, t in arms_tasks.items()}}


def test_ablation_result_filename_has_the_ablation_suffix():
    name = standard.ablation_result_filename("2026-09-26", "abc1234", 4)
    assert name == "2026-09-26-abc1234-t4-ablation.json"


def test_ablation_rows_sorted_by_computed_cost_ascending():
    results = _ablation_results({
        "normal": [_task("create", True, 3, 10.0, 1000, 0, 500)],
        "mapper": [_task("create", True, 2, 8.0, 400, 100, 200)],
        "simplicio": [_task("create", True, 1, 5.0, 200, 50, 100)],
    })
    rows = standard.ablation_rows(results)
    assert [r["arm"] for r in rows] == sorted(
        [r["arm"] for r in rows], key=lambda a: next(r["computed_cost"] for r in rows if r["arm"] == a)
    )
    costs = [r["computed_cost"] for r in rows]
    assert costs == sorted(costs)
    # simplicio has fewer/cheaper tokens here, so it must rank first.
    assert rows[0]["arm"] == "simplicio"


def test_ablation_rows_kind_filter_scopes_tokens_and_wall():
    results = _ablation_results({
        "normal": [
            _task("create", True, 1, 4.0, 100, 0, 50),
            _task("edit", True, 1, 6.0, 200, 0, 100),
        ],
    })
    create_rows = standard.ablation_rows(results, kind="create")
    edit_rows = standard.ablation_rows(results, kind="edit")
    assert create_rows[0]["wall"] == 4.0
    assert edit_rows[0]["wall"] == 6.0
    assert create_rows[0]["prompt_tokens"] == 100
    assert edit_rows[0]["prompt_tokens"] == 200


def test_ablation_rows_reports_ok_over_n():
    results = _ablation_results({
        "devcli": [
            _task("create", True, 1, 1.0, 10, 0, 10),
            _task("edit", False, 1, 1.0, 10, 0, 10),
        ],
    })
    row = standard.ablation_rows(results)[0]
    assert row["ok"] == 1
    assert row["n"] == 2


def test_ablation_winners_picks_lowest_cost_and_lowest_wall_independently():
    rows = [
        {"arm": "a", "computed_cost": 0.01, "wall": 50.0, "ok": 1, "n": 1},
        {"arm": "b", "computed_cost": 0.02, "wall": 5.0, "ok": 1, "n": 1},
    ]
    winners = standard.ablation_winners(rows)
    assert winners["cheapest"]["arm"] == "a"
    assert winners["fastest"]["arm"] == "b"


def test_ablation_winners_empty_rows_returns_none():
    winners = standard.ablation_winners([])
    assert winners == {"cheapest": None, "fastest": None}


def test_ablation_sections_total_only_for_t1():
    results = _ablation_results({"normal": [_task("create", True, 1, 1.0, 10, 0, 10)]})
    sections = standard.ablation_sections(results, 1)
    assert [label for label, _ in sections] == ["Total"]


def test_ablation_sections_total_create_edit_for_t4():
    results = _ablation_results({
        "normal": [
            _task("create", True, 1, 1.0, 10, 0, 10),
            _task("edit", True, 1, 1.0, 10, 0, 10),
        ],
    })
    sections = standard.ablation_sections(results, 4)
    assert [label for label, _ in sections] == ["Total", "Criação (create)", "Edição (edit)"]


def test_build_ablation_markdown_includes_both_task_sets_and_winner_lines():
    results = {
        1: _ablation_results({
            "normal": [_task("create", True, 3, 10.0, 1000, 0, 500)],
            "simplicio": [_task("create", True, 1, 2.0, 100, 50, 50)],
        }),
        4: _ablation_results({
            "normal": [
                _task("create", True, 1, 1.0, 10, 0, 10),
                _task("edit", True, 1, 1.0, 10, 0, 10),
            ],
            "simplicio": [
                _task("create", True, 1, 1.0, 5, 0, 5),
                _task("edit", True, 1, 1.0, 5, 0, 5),
            ],
        }),
    }
    md = standard.build_ablation_markdown(results)
    assert "## t1" in md
    assert "## t4" in md
    assert "Menor custo" in md
    assert "Mais rápido" in md
    assert "Criação (create)" in md
    assert "Edição (edit)" in md


def test_build_ablation_markdown_flags_a_failing_arm():
    results = {
        1: _ablation_results({
            "normal": [_task("create", True, 1, 1.0, 10, 0, 10)],
            "mapper": [_task("create", False, 5, 20.0, 5000, 0, 5000)],
        }),
    }
    md = standard.build_ablation_markdown(results)
    assert "mapper" in md and "falhou" in md


def test_build_ablation_html_index_renders_a_table_per_task_set():
    results = {1: _ablation_results({"normal": [_task("create", True, 1, 1.0, 10, 0, 10)]})}
    html = standard.build_ablation_html_index(results)
    assert "<h2>t1</h2>" in html
    assert "<table" in html


def test_arm_choices_includes_all_ablation_arms():
    assert set(standard.bench_arms.ARM_NAMES) == {
        "normal", "mapper", "devcli", "mapper-devcli", "simplicio",
    }


def test_build_arg_parser_has_ablation_flag_defaulting_false():
    ap = standard.build_arg_parser()
    args = ap.parse_args([])
    assert args.ablation is False


def test_build_arg_parser_accepts_ablation_flag():
    ap = standard.build_arg_parser()
    args = ap.parse_args(["--ablation"])
    assert args.ablation is True
    assert args.task_timeout == standard.bench_run.oc.DEFAULT_RUN_TIMEOUT
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
                "totals": {"cost_usd": cost, "cost_source": "billed-delta",
                           "prompt_tokens": 10, "cached_tokens": 5}}
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
                "totals": {"cost_usd": cost, "cost_source": "billed-delta",
                           "prompt_tokens": 1000, "cached_tokens": 500, "completion_tokens": 10}}
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


def test_summary_shows_billed_and_computed_cost_side_by_side_with_flag_count():
    """Issue #1335: the summary must show custo cobrado (billed) AND custo
    calculado (token-computed) side by side, plus how many tasks were
    flagged for a >10% divergence between the two."""
    pricing = {"available": True, "prompt": 0.00000014, "completion": 0.00000042}

    def task(cost_usd):
        # billed far below the token price -- issue #1335's own example.
        return {"index": 1, "kind": "create", "success": True, "turns": 1, "wall_s": 1.0,
                "totals": {"cost_usd": cost_usd, "cost_source": "billed-delta",
                           "prompt_tokens": 1000, "cached_tokens": 0, "completion_tokens": 0}}

    res = {"meta": {"batch": False, "pricing": pricing}, "arms": {
        "normal": {"tasks": [task(0.00005)]},
        "simplicio": {"tasks": [task(0.00014)]},
    }}
    rec = standard.summary_records("t1", res)[0]
    assert rec["normal"]["cost"] == 0.00005            # billed kept as cost_usd
    assert round(rec["normal"]["cost_computed"], 6) == 0.00014  # token-computed cross-check
    assert rec["normal"]["flagged"] == 1                # >10% divergence
    assert rec["simplicio"]["flagged"] == 0              # matches computed, not flagged

    row = standard.summary_rows("t1", res)[0]
    assert "$0.00014" in row  # computed cost shown alongside billed


def test_find_chromium_honors_env(monkeypatch, tmp_path):
    fake = tmp_path / "chrome"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("SIMPLICIO_BENCH_CHROMIUM", str(fake))
    assert standard.find_chromium() == str(fake)


# --- issue #1336: STANDARD.md's simplicio cache-hit >= 80% gate (target 90%) -


def test_flag_low_simplicio_cache_hit_marks_the_hit_cell():
    cells = standard._arm_cells({
        "ok": 3, "n": 3, "turns": 10, "wall": 5.0,
        "cost": 0.01, "cost_computed": 0.01, "flagged": 0,
        "hit": 75.0, "nocache": 0.02, "cache_saved": 0.01,
    })
    hit_at = next(i for i, cell in enumerate(cells) if cell == "75.0%")
    standard._flag_low_simplicio_cache_hit(cells, 75.0)
    assert cells[hit_at].startswith("⚠ ")
    assert "75.0%" in cells[hit_at]
    assert "<80%" in cells[hit_at]
    assert standard._ARM_CELL_CACHE_HIT_INDEX == hit_at
    assert all("⚠" not in cell for i, cell in enumerate(cells) if i != hit_at)


def test_flag_low_simplicio_cache_hit_leaves_cell_alone_at_the_gate():
    cells = ["3/3", "10", "5.0", "$0.01000", "80.0%", "$0.02000", "$0.01000"]
    before = list(cells)
    standard._flag_low_simplicio_cache_hit(cells, 80.0)
    assert cells == before


def _cache_hit_results(normal_cached: int, simplicio_cached: int) -> dict:
    def totals(cached):
        return {"prompt_tokens": 100, "cached_tokens": cached, "completion_tokens": 5, "cost_usd": 0.01}

    return {
        "meta": {"pricing": {}, "batch": False},
        "arms": {
            "normal": {"tasks": [{"kind": "create", "success": True, "turns": 1, "wall_s": 1.0,
                                   "totals": totals(normal_cached)}]},
            "simplicio": {"tasks": [{"kind": "create", "success": True, "turns": 1, "wall_s": 1.0,
                                      "totals": totals(simplicio_cached)}]},
        },
    }


def test_summary_rows_flags_simplicio_below_cache_hit_gate():
    rows = standard.summary_rows("t1", _cache_hit_results(normal_cached=90, simplicio_cached=50))
    joined = "".join(rows)
    assert "⚠" in joined
    assert "<80%" in joined


def test_summary_rows_does_not_flag_simplicio_at_or_above_cache_hit_gate():
    rows = standard.summary_rows("t1", _cache_hit_results(normal_cached=90, simplicio_cached=95))
    joined = "".join(rows)
    assert "⚠" not in joined


def test_build_markdown_flags_simplicio_below_cache_hit_gate():
    results = _cache_hit_results(normal_cached=90, simplicio_cached=50)
    md = standard.build_markdown([("t1", "/out/r.json", "/out/REPORT-t1.html")], {"t1": results})
    assert "⚠" in md
    assert "<80%" in md


def test_build_full_html_drops_the_command_timeline_from_the_pdf():
    """The PDF is the shareable summary: the per-command timeline (every
    command line the agent ran) stays in the HTML reports only."""
    report = ("<html><head></head><body><h2>Gráficos</h2><img src='x'>"
              "<h2>Linha do tempo de comandos (por braço, por tarefa)</h2>"
              "<table class=\"timeline\"><tr><td>cat big.html</td></tr></table>"
              "<p class=\"meta\">★ = comando simplicio-loop/mapper/dev-cli/fast.</p>"
              "<h2>Histórico (comparação com execuções anteriores)</h2></body></html>")
    full = standard.build_full_html("<html><body><h1>Resumo</h1></body></html>", {"t1": report})
    assert "Linha do tempo de comandos" not in full
    assert "cat big.html" not in full
    assert "Gráficos" in full and "Histórico" in full


def test_build_full_html_drops_the_per_call_cache_table_from_the_pdf():
    """Issue #1336: the per-LLM-call cache breakdown is an HTML-only
    debugging aid (it can have one row per turn per task), not part of the
    shareable PDF summary."""
    report = ("<html><head></head><body><h2>Custo real</h2><table></table>"
              "<h2>Cache por chamada de LLM (bisecção de quebras de prefixo, issue #1336)</h2>"
              "<table class=\"compare\"><tr><td>simplicio</td><td>99.9%</td></tr></table>"
              "<h2>Gráficos</h2><img src='x'></body></html>")
    full = standard.build_full_html("<html><body><h1>Resumo</h1></body></html>", {"t1": report})
    assert "Cache por chamada de LLM" not in full
    assert "99.9%" not in full
    assert "Custo real" in full and "Gráficos" in full


def test_ablation_never_clobbers_the_classic_matrix_result(tmp_path, monkeypatch):
    """The ablation's raw run.py output must not reuse the classic matrix's
    ``-t<N>.json`` path: moving it to ``-ablation.json`` used to delete the
    standard result written earlier in the same day/commit."""
    out = str(tmp_path)
    for n in standard.ABLATION_TASK_COUNTS:
        with open(standard._result_path_for(out, n, batch=False), "w", encoding="utf-8") as f:
            f.write('{"classic": true}')

    def fake_run(argv):
        run_out = argv[argv.index("--out") + 1]
        n = int(argv[argv.index("--tasks") + 1])
        os.makedirs(run_out, exist_ok=True)
        with open(standard._result_path_for(run_out, n, batch=False), "w", encoding="utf-8") as f:
            f.write('{"ablation": true}')
        return 0

    monkeypatch.setattr(standard.bench_run, "main", fake_run)
    monkeypatch.setattr(standard, "write_ablation_reports", lambda entries, out_dir: None)
    monkeypatch.setattr(standard, "per_call_cache_gate", lambda entries: 0)
    args = standard.build_arg_parser().parse_args(["--ablation", "--out", out])

    assert standard.run_ablation(args) == 0
    for n in standard.ABLATION_TASK_COUNTS:
        with open(standard._result_path_for(out, n, batch=False), encoding="utf-8") as f:
            assert f.read() == '{"classic": true}'
        with open(standard._ablation_result_path(out, n), encoding="utf-8") as f:
            assert f.read() == '{"ablation": true}'
