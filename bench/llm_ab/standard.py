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
import json
import os
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
    ap.add_argument("--max-turns", type=int, default=30, help="per agent.run_agent call (see run.py)")
    ap.add_argument("--cmd-timeout", type=int, default=180, help="per bash-tool command (see run.py)")
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


def _arm_sums(tasks: list[dict], pricing: dict) -> dict:
    """Per-slice totals. ``cost`` is the real billed cost (OpenRouter
    generation stats, cache discount included); ``nocache`` prices the same
    tokens at the list prompt rate, so ``cache_saved`` is what the cache
    actually saved -- both from the run's own pricing snapshot."""
    def tot(key: str) -> float:
        return sum((t.get("totals") or {}).get(key) or 0 for t in tasks)

    prompt, cached, compl = int(tot("prompt_tokens")), int(tot("cached_tokens")), int(tot("completion_tokens"))
    sums = {
        "ok": sum(1 for t in tasks if t.get("success")),
        "n": len(tasks),
        "turns": sum(t.get("turns") or 0 for t in tasks),
        "wall": sum(t.get("wall_s") or 0.0 for t in tasks),
        "cost": tot("cost_usd"),
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


def summary_rows(suffix: str, results: dict) -> list[str]:
    """One row per slice of a result file: its total, plus create-only and
    edit-only for sequential runs (a batch run is one session, so its calls
    cannot be split per task)."""
    arms = results.get("arms") or {}
    pricing = (results.get("meta") or {}).get("pricing") or {}
    slices = [("total", None)]
    if not (results.get("meta") or {}).get("batch"):
        kinds = {t.get("kind") for a in arms.values() for t in a.get("tasks", [])}
        slices += [(label, kind) for label, kind in (("criação", "create"), ("edição", "edit")) if kind in kinds]
    rows = []
    for label, kind in slices:
        sums = {}
        for arm in ("normal", "simplicio"):
            tasks = (arms.get(arm) or {}).get("tasks", [])
            sums[arm] = _arm_sums([t for t in tasks if kind is None or t.get("kind") == kind], pricing)
        n, s = sums["normal"], sums["simplicio"]
        saved = n["cost"] - s["cost"]
        pct = f"{saved / n['cost'] * 100:.1f}%" if n["cost"] else "n/a"
        cells = "".join(
            f"<td>{a['ok']}/{a['n']}</td><td>{a['turns']}</td><td>{a['wall']:.1f}</td>"
            f"<td>${a['cost']:.5f}</td><td>{a['hit']:.1f}%</td><td>{_usd(a['nocache'])}</td>"
            f"<td>{_usd(a['cache_saved'])}</td>"
            for a in (n, s)
        )
        rows.append(f"<tr><td>{suffix} · {label}</td>{cells}<td>${saved:.5f} ({pct})</td></tr>")
    return rows


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
            "<h2>Resumo (normal vs simplicio)</h2>\n<table border='1' cellpadding='4'>"
            "<tr><th>combinação</th>"
            "<th>normal ok</th><th>turnos</th><th>tempo (s)</th><th>custo real</th>"
            "<th>cache hit</th><th>custo sem cache</th><th>economia do cache</th>"
            "<th>simplicio ok</th><th>turnos</th><th>tempo (s)</th><th>custo real</th>"
            "<th>cache hit</th><th>custo sem cache</th><th>economia do cache</th>"
            "<th>economia de custo real com simplicio</th></tr>\n" + body + "</table>\n"
            "<p>Custo real = cobrado pelo OpenRouter (desconto de cache incluído). Custo sem cache = "
            "os mesmos tokens ao preço cheio de prompt. Economia do cache = diferença, pelo preço "
            "de cache read da própria execução.</p>\n"
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
            "--max-turns", str(args.max_turns),
            "--cmd-timeout", str(args.cmd_timeout),
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
