#!/usr/bin/env python3
"""bench/llm_ab/standard.py -- the ONE canonical benchmark matrix run for
every release (see bench/llm_ab/STANDARD.md for the full standard).

Runs both task sets that exercise pure create and pure create+edit work
(``--tasks 1`` and ``--tasks 4``), each once sequentially (one agent
session per task) and once in ``--batch`` (all tasks in one agent
session), for both arms (``normal``, ``simplicio``), on the harness's
default model (``llm_client.MODEL``, ``deepseek/deepseek-v4.1-flash`` --
never overridden here). That is 4 combinations, each an append-only
``results/<date>-<sha>-t<N>[-batch].json`` plus its own
``REPORT-<suffix>.html``, and one combined ``REPORT.html`` index linking
all four.

Keys: this script never reads, prints, or hardcodes a raw API key. It
reuses ``llm_client.py``'s existing ``SIMPLICIO_BENCH_KEYS`` mechanism
(a keys.env path -> ``OR_KEY_NORMAL``/``OR_KEY_SIMPLICIO`` inside it) --
either export ``SIMPLICIO_BENCH_KEYS`` yourself before running this, or
pass ``--keys-file /path/to/keys.env`` and this script sets
``SIMPLICIO_BENCH_KEYS`` to it for this invocation only. Never commit a
keys file.

Usage::

    export SIMPLICIO_BENCH_KEYS=/path/to/keys.env   # OR_KEY_NORMAL / OR_KEY_SIMPLICIO
    python3 bench/llm_ab/standard.py
    # or, in one line:
    python3 bench/llm_ab/standard.py --keys-file /path/to/keys.env

See bench/llm_ab/STANDARD.md for the full standard (metrics, history/
comparison rule, and the "run every release" policy).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import arms as bench_arms  # noqa: E402
import cost as bench_cost  # noqa: E402
import run as bench_run  # noqa: E402

# Each entry: (--tasks value, --batch flag). Order matters only for the
# printed progress log; results/report filenames are what make each
# combination independently addressable and comparable across releases.
MATRIX: list[dict] = [
    {"tasks": 1, "batch": False},
    {"tasks": 1, "batch": True},
    {"tasks": 4, "batch": False},
    {"tasks": 4, "batch": True},
]


def suffix_for(tasks: int, batch: bool) -> str:
    """``t<N>`` or ``t<N>-batch`` -- matches ``run.result_filename``'s own
    suffixing, so a combination's results file and its REPORT-<suffix>.html
    are always named consistently."""
    return f"t{tasks}-batch" if batch else f"t{tasks}"


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--keys-file", default=None,
        help=(
            "path to a keys.env (OR_KEY_NORMAL=... / OR_KEY_SIMPLICIO=...); sets "
            "SIMPLICIO_BENCH_KEYS to it for this run only. Omit to use the "
            "SIMPLICIO_BENCH_KEYS already exported in the environment. Never commit this file."
        ),
    )
    ap.add_argument(
        "--out", default=os.path.join(HERE, "results"),
        help="directory for the append-only results/<date>-<sha>-t<N>[-batch].json history",
    )
    ap.add_argument(
        "--task-timeout", type=int, default=bench_run.oc.DEFAULT_RUN_TIMEOUT,
        help="per `opencode run` invocation per task, forwarded to run.py's --task-timeout",
    )
    ap.add_argument(
        "--reports-only", metavar="SHA", default=None,
        help="re-render every REPORT-*.html and REPORT.html from the existing results/*-<SHA>-*.json "
             "files, without calling any LLM (no keys needed)",
    )
    ap.add_argument(
        "--ablation", action="store_true",
        help=(
            "run the 5-arm ablation matrix instead (issue #1337; issue #1343 dropped "
            "the Fast arms): normal, mapper, devcli, mapper-devcli, simplicio "
            "(arms.ARM_SPECS), each isolated to only its own skills/binaries, on "
            "--tasks 1 and --tasks 4 "
            "(sequential only, no --batch) -- writes results/<date>-<sha>-t<N>-ablation.json "
            "and REPORT-ablation.md/.html/.pdf ranked by computed cost ascending"
        ),
    )
    return ap


def _result_path_for(out_dir: str, tasks: int, batch: bool) -> str:
    date = bench_run.datetime.date.today().isoformat()
    short_sha = bench_run._short_sha(bench_run.REPO_ROOT)
    return os.path.join(out_dir, bench_run.result_filename(date, short_sha, tasks, batch=batch))


def _finalized_tasks(tasks: list[dict], pricing: dict) -> list[dict]:
    """``tasks`` with every ``totals`` run through
    ``cost.finalize_task_cost`` (issue #1335) -- non-mutating, so this works
    the same whether ``tasks`` already carries the settled/computed cost
    fields (a fresh run) or predates this fix (an OLDER result rendered via
    ``--reports-only``, which never has its stored JSON edited)."""
    return [dict(t, totals=bench_cost.finalize_task_cost(t.get("totals") or {}, pricing)) for t in tasks]


def _arm_sums(tasks: list[dict], pricing: dict) -> dict:
    """Per-slice totals. ``cost`` is the settled-billed cost (or the
    token-computed fallback when the ledger never settled -- ``cost_usd``
    after ``finalize_task_cost``); ``cost_computed`` is always the
    token-computed figure, for the side-by-side cross-check;
    ``flagged`` counts tasks whose billed/computed divergence exceeded 10%.
    ``nocache`` prices the same tokens at the list prompt rate, so
    ``cache_saved`` is what the cache actually saved -- both from the run's
    own pricing snapshot."""
    tasks = _finalized_tasks(tasks, pricing)

    def tot(key: str) -> float:
        return sum((t.get("totals") or {}).get(key) or 0 for t in tasks)

    prompt, cached, compl = int(tot("prompt_tokens")), int(tot("cached_tokens")), int(tot("completion_tokens"))
    sums = {
        "ok": sum(1 for t in tasks if t.get("success")),
        "n": len(tasks),
        "turns": sum(t.get("turns") or 0 for t in tasks),
        "wall": sum(t.get("wall_s") or 0.0 for t in tasks),
        "cost": tot("cost_usd"),
        "cost_computed": tot("computed_cost_usd"),
        "flagged": sum(1 for t in tasks if (t.get("totals") or {}).get("cost_flag")),
        "hit": (cached / prompt * 100.0) if prompt else 0.0,
        "nocache": None,
        "cache_saved": None,
    }
    if pricing.get("prompt") is not None and pricing.get("completion") is not None:
        breakdown = bench_cost.cost_breakdown(prompt, cached, compl, pricing)
        sums["cache_saved"] = breakdown["cache_savings_usd"]
        sums["nocache"] = breakdown["computed_cost_usd"] + breakdown["cache_savings_usd"]
    return sums


def _usd(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.5f}"


# -- 5-arm ablation matrix (issue #1337; issue #1343 dropped the Fast arms) --
# normal / mapper / devcli / mapper-devcli / simplicio, on --tasks 1 and
# --tasks 4, sequential only (no --batch), all arms isolated uniformly
# (run.py --isolate-arms) so cost/speed differences are attributable to the
# operators actually granted, never a PATH leak.

ABLATION_HEADERS = [
    "arm", "ok/n", "turns", "wall (s)", "custo calculado", "custo cobrado",
    "cache hit", "custo sem cache", "economia do cache",
    "tokens prompt", "tokens cache", "tokens completion",
]


def ablation_result_filename(date: str, short_sha: str, task_count: int) -> str:
    """``<date>-<sha>-t<N>-ablation.json`` (issue #1337) -- distinct from
    ``run.result_filename``'s own ``-t<N>[-batch].json`` naming, so an
    ablation run's history never mixes with the classic 2-arm matrix's."""
    return f"{date}-{short_sha}-t{task_count}-ablation.json"


def _ablation_arm_row(arm: str, tasks: list[dict], pricing: dict) -> dict:
    """One arm's totals for a ranking row: computed cost is the primary
    ranking figure (token-exact per task, issue #1337); billed is the
    settled-ledger cross-check (or the same computed figure when the
    ledger never settled -- ``cost_usd`` after ``finalize_task_cost``)."""
    tasks = _finalized_tasks(tasks, pricing)

    def tot(key: str) -> float:
        return sum((t.get("totals") or {}).get(key) or 0 for t in tasks)

    prompt, cached, compl = int(tot("prompt_tokens")), int(tot("cached_tokens")), int(tot("completion_tokens"))
    nocache = cache_saved = None
    if pricing.get("prompt") is not None and pricing.get("completion") is not None:
        breakdown = bench_cost.cost_breakdown(prompt, cached, compl, pricing)
        cache_saved = breakdown["cache_savings_usd"]
        nocache = breakdown["computed_cost_usd"] + cache_saved
    return {
        "arm": arm,
        "ok": sum(1 for t in tasks if t.get("success")),
        "n": len(tasks),
        "turns": sum(t.get("turns") or 0 for t in tasks),
        "wall": sum(t.get("wall_s") or 0.0 for t in tasks),
        "computed_cost": tot("computed_cost_usd"),
        "billed_cost": tot("cost_usd"),
        "cache_hit": (cached / prompt * 100.0) if prompt else 0.0,
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "completion_tokens": compl,
        "nocache": nocache,
        "cache_saved": cache_saved,
    }


def ablation_rows(results: dict, kind: str | None = None) -> list[dict]:
    """One row per arm present in ``results["arms"]``, sorted by computed
    cost ascending (the ranking cost, per issue #1337) -- ``kind`` scopes
    every figure to that task kind (``"create"``/``"edit"``), matching
    ``summary_records``'s create/edit slicing for the classic matrix."""
    arms_data = results.get("arms") or {}
    pricing = (results.get("meta") or {}).get("pricing") or {}
    rows = []
    for arm, arm_data in arms_data.items():
        tasks = arm_data.get("tasks", [])
        if kind is not None:
            tasks = [t for t in tasks if t.get("kind") == kind]
        rows.append(_ablation_arm_row(arm, tasks, pricing))
    rows.sort(key=lambda r: r["computed_cost"])
    return rows


def _ablation_row_cells(r: dict) -> list[str]:
    return [
        r["arm"], f"{r['ok']}/{r['n']}", str(r["turns"]), f"{r['wall']:.1f}",
        f"${r['computed_cost']:.5f}", f"${r['billed_cost']:.5f}", f"{r['cache_hit']:.1f}%",
        _usd(r.get("nocache")), _usd(r.get("cache_saved")),
        str(r["prompt_tokens"]), str(r["cached_tokens"]), str(r["completion_tokens"]),
    ]


def ablation_winners(rows: list[dict]) -> dict:
    """``{"cheapest": row, "fastest": row}`` -- lowest computed cost and
    lowest total wall time among ``rows`` (ties broken by whichever
    ``sorted`` keeps first, i.e. arm-table order). Never filters by
    success: an arm that "won" without passing every task is still
    reported, flagged by its own ``ok/n`` cell, so a caller can see the
    anomaly rather than have it silently excluded."""
    if not rows:
        return {"cheapest": None, "fastest": None}
    cheapest = min(rows, key=lambda r: r["computed_cost"])
    fastest = min(rows, key=lambda r: r["wall"])
    return {"cheapest": cheapest, "fastest": fastest}


def _winner_lines(rows: list[dict]) -> list[str]:
    winners = ablation_winners(rows)
    cheapest, fastest = winners["cheapest"], winners["fastest"]
    lines = [
        f"- **Menor custo:** `{cheapest['arm']}` (${cheapest['computed_cost']:.5f} calculado, "
        f"${cheapest['billed_cost']:.5f} cobrado, {cheapest['ok']}/{cheapest['n']} ok)",
        f"- **Mais rápido:** `{fastest['arm']}` ({fastest['wall']:.1f}s, {fastest['ok']}/{fastest['n']} ok)",
    ]
    for r in rows:
        if r["ok"] < r["n"]:
            lines.append(f"- ⚠ `{r['arm']}` falhou {r['n'] - r['ok']}/{r['n']} tarefa(s)")
    return lines


def _ablation_table_md(title: str, rows: list[dict]) -> str:
    lines = [
        f"### {title}", "", "| " + " | ".join(ABLATION_HEADERS) + " |",
        "|" + "---|" * len(ABLATION_HEADERS),
    ]
    for r in rows:
        lines.append("| " + " | ".join(_ablation_row_cells(r)) + " |")
    return "\n".join(lines)


def _ablation_table_html(title: str, rows: list[dict]) -> str:
    header = "".join(f"<th>{h}</th>" for h in ABLATION_HEADERS)
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in _ablation_row_cells(r)) + "</tr>\n" for r in rows
    )
    return f"<h3>{title}</h3>\n<table border='1' cellpadding='4'><tr>{header}</tr>\n{body}</table>\n"


ABLATION_SLICES = (("Total", None), ("Criação (create)", "create"), ("Edição (edit)", "edit"))


def ablation_sections(results: dict, task_count: int) -> list[tuple[str, list[dict]]]:
    """``[("Total", rows), ...]`` for ``results`` -- create/edit slices are
    only meaningful for a sequential multi-task run (``t4``), matching
    ``summary_records``'s same restriction for the classic matrix."""
    slices = [("Total", None)]
    if task_count == 4:
        slices += [(label, kind) for label, kind in ABLATION_SLICES[1:]]
    return [(label, ablation_rows(results, kind=kind)) for label, kind in slices]


def build_ablation_markdown(results_by_n: dict[int, dict]) -> str:
    lines = [
        f"# Ablation benchmark — {len(bench_arms.ARM_NAMES)} arms (issue #1337)", "",
        f"Modelo: `{bench_run.lc.MODEL}` · braços: {', '.join(bench_arms.ARM_NAMES)}", "",
    ]
    for n in sorted(results_by_n):
        results = results_by_n[n]
        lines.append(f"## t{n}")
        lines.append("")
        for label, rows in ablation_sections(results, n):
            if label == "Total":
                lines.extend(_winner_lines(rows))
                lines.append("")
            lines.append(_ablation_table_md(label, rows))
            lines.append("")
    return "\n".join(lines) + "\n"


def build_ablation_html_index(results_by_n: dict[int, dict]) -> str:
    sections = []
    for n in sorted(results_by_n):
        results = results_by_n[n]
        sections.append(f"<h2>t{n}</h2>")
        for label, rows in ablation_sections(results, n):
            if label == "Total":
                items = "".join(f"<li>{w.lstrip('- ').replace('**', '')}</li>" for w in _winner_lines(rows))
                sections.append(f"<ul>{items}</ul>")
            sections.append(_ablation_table_html(label, rows))
    body = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>Ablation benchmark — {len(bench_arms.ARM_NAMES)} arms</title></head>
<body>
<h1>Ablation benchmark: {len(bench_arms.ARM_NAMES)} arms (issue #1337)</h1>
<p>Modelo: <code>{bench_run.lc.MODEL}</code> &middot; braços: {", ".join(bench_arms.ARM_NAMES)}</p>
{body}
</body>
</html>
"""


def summary_records(suffix: str, results: dict) -> list[dict]:
    """One record per slice of a result file: its total, plus create-only and
    edit-only for sequential runs (a batch run is one session, so its calls
    cannot be split per task). Shared by the HTML and Markdown summaries."""
    arms = results.get("arms") or {}
    pricing = (results.get("meta") or {}).get("pricing") or {}
    slices = [("total", None)]
    if not (results.get("meta") or {}).get("batch"):
        kinds = {t.get("kind") for a in arms.values() for t in a.get("tasks", [])}
        slices += [(label, kind) for label, kind in (("criação", "create"), ("edição", "edit")) if kind in kinds]
    records = []
    for label, kind in slices:
        sums = {}
        for arm in ("normal", "simplicio"):
            tasks = (arms.get(arm) or {}).get("tasks", [])
            sums[arm] = _arm_sums([t for t in tasks if kind is None or t.get("kind") == kind], pricing)
        saved = sums["normal"]["cost"] - sums["simplicio"]["cost"]
        pct = f"{saved / sums['normal']['cost'] * 100:.1f}%" if sums["normal"]["cost"] else "n/a"
        records.append({"name": f"{suffix} · {label}", "normal": sums["normal"],
                        "simplicio": sums["simplicio"], "saved": f"${saved:.5f} ({pct})"})
    return records


def _arm_cells(a: dict) -> list[str]:
    return [f"{a['ok']}/{a['n']}", str(a["turns"]), f"{a['wall']:.1f}", f"${a['cost']:.5f}",
            _usd(a.get("cost_computed")), str(a.get("flagged", 0)),
            f"{a['hit']:.1f}%", _usd(a["nocache"]), _usd(a["cache_saved"])]


# Index of the cache-hit cell within `_arm_cells`'s return -- kept as a named
# constant instead of a magic number at each call site below.
_ARM_CELL_CACHE_HIT_INDEX = 4

# STANDARD.md: the simplicio arm's prompt-cache hit rate must be >= 80% (target 90%)
# (issue #1336). Report-only gate: it never changes `_arm_sums`/`_arm_cells`'s
# own numbers, only flags the rendered cell when the simplicio arm misses it.
SIMPLICIO_CACHE_HIT_GATE_PCT = 80.0
SIMPLICIO_CACHE_HIT_TARGET_PCT = 90.0


def _flag_low_simplicio_cache_hit(cells: list[str], hit_pct: float) -> None:
    """Mutate ``cells`` (a ``simplicio``-arm ``_arm_cells()`` result) in
    place, marking its cache-hit cell when ``hit_pct`` is below the
    STANDARD.md gate -- so a combination that misses the requirement is
    visibly flagged in REPORT.html, REPORT.md, and the PDF (which renders
    the same HTML) without anyone having to cross-reference raw numbers."""
    if hit_pct < SIMPLICIO_CACHE_HIT_GATE_PCT:
        cells[_ARM_CELL_CACHE_HIT_INDEX] = (
            f"⚠ {cells[_ARM_CELL_CACHE_HIT_INDEX]} (<{SIMPLICIO_CACHE_HIT_GATE_PCT:.0f}%)"
        )


def summary_rows(suffix: str, results: dict) -> list[str]:
    rows = []
    for r in summary_records(suffix, results):
        normal_cells = _arm_cells(r["normal"])
        simplicio_cells = _arm_cells(r["simplicio"])
        _flag_low_simplicio_cache_hit(simplicio_cells, r["simplicio"]["hit"])
        cells = [r["name"], *normal_cells, *simplicio_cells, r["saved"]]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return rows


SUMMARY_HEADERS = [
    "combinação",
    "normal ok", "turnos", "tempo (s)", "custo cobrado", "custo calculado", "sinalizados",
    "cache hit", "custo sem cache", "economia do cache",
    "simplicio ok", "turnos", "tempo (s)", "custo cobrado", "custo calculado", "sinalizados",
    "cache hit", "custo sem cache", "economia do cache",
    "economia de custo cobrado com simplicio",
]
CACHE_NOTE = ("Custo cobrado = delta assentado da chave OpenRouter (issue #1335: assentado é "
              "3+ leituras seguidas sem variar, nunca o primeiro movimento), ou o próprio custo "
              "calculado quando o uso nunca assenta dentro da janela (`cost_source = "
              "computed-from-tokens`). Custo calculado = os mesmos tokens pelo preço da própria "
              "execução (prompt/cache/completion), sempre presente, mesmo para runs antigas sem o "
              "campo (recalculado aqui a partir dos tokens armazenados, nunca editando o "
              "results/*.json histórico). Sinalizados = tarefas cujo custo cobrado divergiu do "
              "calculado em mais de 10%. Custo sem cache = os mesmos tokens ao preço cheio de "
              "prompt. Economia do cache = diferença, pelo preço de cache read da própria "
              "execução. Batch = uma sessão para todas as tarefas, por isso sem linhas de "
              "criação/edição; veja a execução sequencial do mesmo conjunto.")


def build_markdown(written: list[tuple[str, str, str]], results_by_suffix: dict) -> str:
    """`REPORT.md`: the same summary as REPORT.html (total / create-only /
    edit-only per combination, cache-aware) as plain Markdown tables."""
    meta = next((r.get("meta") or {} for r in results_by_suffix.values()), {})
    lines = [
        "# Benchmark A/B — matriz padrão (bench/llm_ab/STANDARD.md)",
        "",
        f"Modelo: `{meta.get('model') or bench_run.lc.MODEL}` · commit: `{meta.get('main_commit', '?')}` "
        f"· braços: normal, simplicio",
        "",
        "## Resumo (normal vs simplicio)",
        "",
        "| " + " | ".join(SUMMARY_HEADERS) + " |",
        "|" + "---|" * len(SUMMARY_HEADERS),
    ]
    for suffix, _, _ in written:
        if suffix in results_by_suffix:
            for r in summary_records(suffix, results_by_suffix[suffix]):
                normal_cells = _arm_cells(r["normal"])
                simplicio_cells = _arm_cells(r["simplicio"])
                _flag_low_simplicio_cache_hit(simplicio_cells, r["simplicio"]["hit"])
                cells = [r["name"], *normal_cells, *simplicio_cells, r["saved"]]
                lines.append("| " + " | ".join(cells) + " |")
    lines += ["", CACHE_NOTE, "", "## Relatórios por combinação", ""]
    lines += [f"- [{suffix}]({os.path.basename(report_path)}) — `{os.path.basename(result_path)}`"
              for suffix, result_path, report_path in written]
    return "\n".join(lines) + "\n"


def build_index(written: list[tuple[str, str, str]], results_by_suffix: dict | None = None) -> str:
    """``written`` is ``[(suffix, result_path, report_path), ...]``. Links
    every combination's report, plus a summary table (total / create-only /
    edit-only per combination) when ``results_by_suffix`` is given. Rows are
    never aggregated across combinations (STANDARD.md's history rule)."""
    rows = "".join(
        f"<li><a href='{os.path.basename(report_path)}'>{suffix}</a> "
        f"&mdash; <code>{os.path.basename(result_path)}</code></li>\n"
        for suffix, result_path, report_path in written
    )
    if not rows:
        rows = "<li>nenhuma combinação da matriz foi executada</li>\n"
    summary = ""
    if results_by_suffix:
        body = "".join(r for suffix, _, _ in written if suffix in results_by_suffix
                       for r in summary_rows(suffix, results_by_suffix[suffix]))
        summary = (
            "<h2>Resumo (normal vs simplicio)</h2>\n<table border='1' cellpadding='4'><tr>"
            + "".join(f"<th>{h}</th>" for h in SUMMARY_HEADERS) + "</tr>\n"
            + body + "</table>\n" + f"<p>{CACHE_NOTE}</p>\n"
        )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>Benchmark A/B — matriz padrão</title></head>
<body>
<h1>Benchmark A/B: matriz padrão (bench/llm_ab/STANDARD.md)</h1>
<p>Modelo: <code>{bench_run.lc.MODEL}</code> &middot; braços: normal, simplicio</p>
{summary}<ul>
{rows}</ul>
</body>
</html>
"""


def _between(html: str, open_re: str, close: str) -> str:
    m = re.search(open_re, html, re.S | re.I)
    if not m:
        return ""
    end = html.find(close, m.end())
    return html[m.end():end if end != -1 else len(html)]


_TIMELINE_RE = re.compile(
    r"<h2>Linha do tempo de comandos.*?(?=<h2>|</body>|$)", re.S | re.I)


def _drop_timeline(body: str) -> str:
    """The PDF is the shareable summary: the per-command timeline (every
    command line the agent ran) stays in the HTML reports only."""
    return _TIMELINE_RE.sub("", body)


_PER_CALL_CACHE_TABLE_RE = re.compile(
    r"<h2>Cache por chamada de LLM.*?(?=<h2>|</body>|$)", re.S | re.I)


def _drop_per_call_cache_table(body: str) -> str:
    """The PDF is the shareable summary: the per-LLM-call cache breakdown
    (issue #1336, one row per turn per task -- a debugging/bisection aid,
    not a summary figure) stays in the HTML reports only."""
    return _PER_CALL_CACHE_TABLE_RE.sub("", body)


def build_full_html(index_html: str, reports: dict[str, str]) -> str:
    """One printable document: the summary index, then every combination's
    report (tables and base64 charts, without the per-command timeline) on
    its own page."""
    styles = {_between(h, r"<style[^>]*>", "</style>") for h in [index_html, *reports.values()]}
    parts = [f"<section>{_between(index_html, r'<body[^>]*>', '</body>')}</section>"]
    parts += [f"<section style='page-break-before: always'>"
              f"{_drop_per_call_cache_table(_drop_timeline(_between(h, r'<body[^>]*>', '</body>')))}</section>"
              for h in reports.values()]
    style = "\n".join(s for s in styles if s)
    return (f"<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'>"
            f"<title>Benchmark A/B — relatório completo</title><style>{style}\n"
            f"img {{ max-width: 100%; }} table {{ font-size: 10px; }}</style></head><body>"
            + "\n".join(parts) + "</body></html>")


def find_chromium() -> str | None:
    """The Chromium Playwright already ships (no extra dependency):
    ``SIMPLICIO_BENCH_CHROMIUM``, then chromium/chrome on PATH, then the
    ``PLAYWRIGHT_BROWSERS_PATH`` install."""
    env = os.environ.get("SIMPLICIO_BENCH_CHROMIUM")
    if env and os.access(env, os.X_OK):
        return env
    for name in ("chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    for pattern in ("chromium-*/chrome-linux/chrome", "chromium_headless_shell-*/chrome-linux/headless_shell"):
        matches = sorted(glob.glob(os.path.join(root, pattern)))
        if matches:
            return matches[-1]
    return None


def html_to_pdf(html_path: str, pdf_path: str) -> None:
    chrome = find_chromium()
    if chrome is None:
        raise RuntimeError("no Chromium found for the PDF report (set SIMPLICIO_BENCH_CHROMIUM)")
    subprocess.run(
        [chrome, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf_path}", "file://" + os.path.abspath(html_path)],
        check=True, capture_output=True, timeout=180,
    )
    if not os.path.isfile(pdf_path) or os.path.getsize(pdf_path) == 0:
        raise RuntimeError(f"Chromium did not write {pdf_path}")


def write_reports(entries: list[tuple[str, str]], out_dir: str) -> None:
    """Render ``REPORT-<suffix>.html`` for each ``(suffix, result_path)`` and
    the combined ``REPORT.html`` index with its summary table."""
    import report as bench_report  # noqa: E402 -- needs matplotlib, imported lazily

    written: list[tuple[str, str, str]] = []
    loaded: dict[str, dict] = {}
    for suffix, result_path in entries:
        with open(result_path) as f:
            loaded[suffix] = json.load(f)
        report_path = os.path.join(HERE, f"REPORT-{suffix}.html")
        with open(report_path, "w") as f:
            f.write(bench_report.build(loaded[suffix], out_dir, current_path=result_path))
        print(f"wrote {report_path}", file=sys.stderr)
        written.append((suffix, result_path, report_path))
    index_path = os.path.join(HERE, "REPORT.html")
    with open(index_path, "w") as f:
        f.write(build_index(written, loaded))
    print(f"wrote {index_path}", file=sys.stderr)
    md_path = os.path.join(HERE, "REPORT.md")
    with open(md_path, "w") as f:
        f.write(build_markdown(written, loaded))
    print(f"wrote {md_path}", file=sys.stderr)

    reports = {}
    for suffix, _, report_path in written:
        with open(report_path) as f:
            reports[suffix] = f.read()
    with open(index_path) as f:
        full = build_full_html(f.read(), reports)
    full_path = os.path.join(HERE, "REPORT-full.html")
    with open(full_path, "w") as f:
        f.write(full)
    pdf_path = os.path.join(HERE, "REPORT.pdf")
    html_to_pdf(full_path, pdf_path)
    print(f"wrote {pdf_path}", file=sys.stderr)


ABLATION_TASK_COUNTS = (1, 4)


def _ablation_result_path(out_dir: str, tasks: int) -> str:
    date = bench_run.datetime.date.today().isoformat()
    short_sha = bench_run._short_sha(bench_run.REPO_ROOT)
    return os.path.join(out_dir, ablation_result_filename(date, short_sha, tasks))


def write_ablation_reports(entries: list[tuple[int, str]], out_dir: str) -> None:
    """``entries`` is ``[(task_count, result_path), ...]``. Renders each
    task-set's own full ``REPORT-ablation-t<N>.html`` (charts + per-arm
    table, via the existing generic ``report.build``, which already
    iterates ``arms`` for however many arm names are present) plus the
    combined ranking (``build_ablation_markdown``/``build_ablation_html_index``)
    as ``REPORT-ablation.md``/``.html``, then one printable
    ``REPORT-ablation.pdf`` with the ranking first and every task-set's full
    report after it (same pattern as ``write_reports``/``build_full_html``)."""
    import report as bench_report  # noqa: E402 -- needs matplotlib, imported lazily

    results_by_n: dict[int, dict] = {}
    per_n_html: dict[str, str] = {}
    for n, result_path in entries:
        with open(result_path) as f:
            results_by_n[n] = json.load(f)
        suffix = f"ablation-t{n}"
        report_path = os.path.join(HERE, f"REPORT-{suffix}.html")
        html = bench_report.build(results_by_n[n], out_dir, current_path=result_path)
        with open(report_path, "w") as f:
            f.write(html)
        per_n_html[f"t{n}"] = html
        print(f"wrote {report_path}", file=sys.stderr)

    md_path = os.path.join(HERE, "REPORT-ablation.md")
    with open(md_path, "w") as f:
        f.write(build_ablation_markdown(results_by_n))
    print(f"wrote {md_path}", file=sys.stderr)

    index_html = build_ablation_html_index(results_by_n)
    html_path = os.path.join(HERE, "REPORT-ablation.html")
    with open(html_path, "w") as f:
        f.write(index_html)
    print(f"wrote {html_path}", file=sys.stderr)

    full = build_full_html(index_html, per_n_html)
    full_path = os.path.join(HERE, "REPORT-ablation-full.html")
    with open(full_path, "w") as f:
        f.write(full)
    pdf_path = os.path.join(HERE, "REPORT-ablation.pdf")
    html_to_pdf(full_path, pdf_path)
    print(f"wrote {pdf_path}", file=sys.stderr)


def run_ablation(args: argparse.Namespace) -> int:
    """The 5-arm ablation matrix (issue #1337; issue #1343 dropped the Fast
    arms): ``arms.ARM_NAMES``, on
    ``--tasks 1`` and ``--tasks 4``, sequential only (``run.py
    --isolate-arms``, never ``--batch`` -- per-arm isolation is the point of
    this matrix, so every arm -- including normal/simplicio -- gets the same
    skill/PATH contract). Each task count's raw ``run.py`` result is moved
    to its ``-ablation.json`` name (issue #1337's own naming, distinct from
    the classic matrix's) before the ranking reports are built."""
    os.makedirs(args.out, exist_ok=True)
    arm_arg = ",".join(bench_arms.ARM_NAMES)
    entries: list[tuple[int, str]] = []

    # run.py names its raw result like the classic matrix (-t<N>.json); a
    # separate scratch dir keeps it from overwriting that result.
    raw_out = tempfile.mkdtemp(prefix=".ablation-raw-", dir=args.out)

    for n in ABLATION_TASK_COUNTS:
        print(f"=== ablation matrix: t{n} ({arm_arg}) ===", file=sys.stderr)
        run_argv = [
            "--arms", arm_arg,
            "--tasks", str(n),
            "--out", raw_out,
            "--task-timeout", str(args.task_timeout),
            "--skip-report",
            "--isolate-arms",
        ]
        rc = bench_run.main(run_argv)
        if rc != 0:
            print(f"ablation matrix: run.py failed for t{n} (exit {rc})", file=sys.stderr)
            return rc

        raw_path = _result_path_for(raw_out, n, batch=False)
        final_path = _ablation_result_path(args.out, n)
        os.replace(raw_path, final_path)
        print(f"wrote {final_path}", file=sys.stderr)
        entries.append((n, final_path))

    shutil.rmtree(raw_out, ignore_errors=True)
    write_ablation_reports(entries, args.out)
    return per_call_cache_gate([(f"t{n}-ablation", path) for n, path in entries])


def main(argv: list[str] | None = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    if args.ablation:
        if args.keys_file:
            os.environ["SIMPLICIO_BENCH_KEYS"] = args.keys_file
        bench_run.lc.keys_path()  # fail fast, before any work, if unset/missing
        return run_ablation(args)

    if args.reports_only:
        entries = []
        for combo in MATRIX:
            suffix = suffix_for(combo["tasks"], combo["batch"])
            matches = sorted(
                f for f in os.listdir(args.out)
                if f.endswith(f"-{args.reports_only}-{suffix}.json")
            )
            if matches:
                entries.append((suffix, os.path.join(args.out, matches[-1])))
        if not entries:
            print(f"standard matrix: no results for sha {args.reports_only} in {args.out}", file=sys.stderr)
            return 2
        write_reports(entries, args.out)
        return 0

    if args.keys_file:
        os.environ["SIMPLICIO_BENCH_KEYS"] = args.keys_file
    bench_run.lc.keys_path()  # fail fast, before any work, if unset/missing

    os.makedirs(args.out, exist_ok=True)
    entries: list[tuple[str, str]] = []

    for combo in MATRIX:
        suffix = suffix_for(combo["tasks"], combo["batch"])
        print(f"=== standard matrix: {suffix} ===", file=sys.stderr)
        run_argv = [
            "--arms", "normal,simplicio",
            "--tasks", str(combo["tasks"]),
            "--out", args.out,
            "--task-timeout", str(args.task_timeout),
            "--skip-report",
        ]
        if combo["batch"]:
            run_argv.append("--batch")
        rc = bench_run.main(run_argv)
        if rc != 0:
            print(f"standard matrix: run.py failed for {suffix} (exit {rc})", file=sys.stderr)
            return rc

        entries.append((suffix, _result_path_for(args.out, combo["tasks"], combo["batch"])))

    write_reports(entries, args.out)
    return per_call_cache_gate(entries)


def per_call_cache_gate(entries: list[tuple[str, str]]) -> int:
    """Fail (exit 3) when any simplicio call after the first of its task read
    no prompt cache (issue #1342). Names the first cold call."""
    import report as bench_report  # noqa: E402 -- needs matplotlib, imported lazily

    status = 0
    for suffix, result_path in entries:
        with open(result_path) as f:
            arms = json.load(f).get("arms", {})
        cold = bench_report.first_cold_call(arms)
        if cold is not None:
            print(
                f"per-call cache gate FAILED ({suffix}): task {cold['task']} turn {cold['turn']} "
                f"had cache_read == 0 -- {cold['cause']}",
                file=sys.stderr,
            )
            status = 3
    return status


if __name__ == "__main__":
    raise SystemExit(main())
