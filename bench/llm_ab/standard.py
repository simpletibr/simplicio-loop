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
    return ap


def _result_path_for(out_dir: str, tasks: int, batch: bool) -> str:
    date = bench_run.datetime.date.today().isoformat()
    short_sha = bench_run._short_sha(bench_run.REPO_ROOT)
    return os.path.join(out_dir, bench_run.result_filename(date, short_sha, tasks, batch=batch))


def build_index(written: list[tuple[str, str, str]]) -> str:
    """``written`` is ``[(suffix, result_path, report_path), ...]``. A plain
    static index -- no charts, no aggregation across combinations (a
    1-task run and a 4-task run, or a sequential and a batch run, are never
    comparable -- see STANDARD.md's history rule)."""
    rows = "".join(
        f"<li><a href='{os.path.basename(report_path)}'>{suffix}</a> "
        f"&mdash; <code>{os.path.basename(result_path)}</code></li>\n"
        for suffix, result_path, report_path in written
    )
    if not rows:
        rows = "<li>nenhuma combinação da matriz foi executada</li>\n"
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>Benchmark A/B — matriz padrão</title></head>
<body>
<h1>Benchmark A/B: matriz padrão (bench/llm_ab/STANDARD.md)</h1>
<p>Modelo: <code>{bench_run.lc.MODEL}</code> &middot; braços: normal, simplicio</p>
<ul>
{rows}</ul>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    if args.keys_file:
        os.environ["SIMPLICIO_BENCH_KEYS"] = args.keys_file
    bench_run.lc.keys_path()  # fail fast, before any work, if unset/missing

    os.makedirs(args.out, exist_ok=True)
    written: list[tuple[str, str, str]] = []

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

        result_path = _result_path_for(args.out, combo["tasks"], combo["batch"])
        with open(result_path) as f:
            results_data = json.load(f)

        import report as bench_report  # noqa: E402 -- needs matplotlib, imported lazily

        html = bench_report.build(results_data, args.out, current_path=result_path)
        report_path = os.path.join(HERE, f"REPORT-{suffix}.html")
        with open(report_path, "w") as f:
            f.write(html)
        print(f"wrote {result_path}", file=sys.stderr)
        print(f"wrote {report_path}", file=sys.stderr)
        written.append((suffix, result_path, report_path))

    index_path = os.path.join(HERE, "REPORT.html")
    with open(index_path, "w") as f:
        f.write(build_index(written))
    print(f"wrote {index_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
