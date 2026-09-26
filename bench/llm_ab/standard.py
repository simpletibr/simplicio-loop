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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

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


def build_full_html(index_html: str, reports: dict[str, str]) -> str:
    """One printable document: the summary index, then every combination's
    full report (all sections and base64 charts) on its own page."""
    styles = {_between(h, r"<style[^>]*>", "</style>") for h in [index_html, *reports.values()]}
    parts = [f"<section>{_between(index_html, r'<body[^>]*>', '</body>')}</section>"]
    parts += [f"<section style='page-break-before: always'>{_between(h, r'<body[^>]*>', '</body>')}</section>"
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


def main(argv: list[str] | None = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
