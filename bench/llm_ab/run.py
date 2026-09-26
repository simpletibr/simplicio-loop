#!/usr/bin/env python3
"""LLM A/B benchmark entry point: normal agent vs the simplicio-loop wave
flow, on 2 dependent HTML tasks (create, then edit).

Usage::

    SIMPLICIO_BENCH_KEYS=/path/to/keys.env \\
      python3 bench/llm_ab/run.py --arms normal,simplicio \\
        --out bench/llm_ab/results

Writes ``<out>/<UTC-date>-<shortsha>.json`` (append-only history) and
``bench/llm_ab/REPORT.html``. See bench/llm_ab/README.md for what each arm
measures and how the keys.env file is shaped.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import llm_client as lc  # noqa: E402
import runner_loop  # noqa: E402
import runner_normal  # noqa: E402

ARM_CHOICES = ("normal", "simplicio")


def _find_loop_bin() -> str:
    found = shutil.which("simplicio-loop")
    if not found:
        raise RuntimeError(
            "simplicio-loop not found on PATH -- install it "
            "(bash scripts/dev_install.sh && source .venv/bin/activate) before running "
            "the simplicio arm."
        )
    return found


def _short_sha(repo: str) -> str:
    out = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    return out or "nogit"


def _pip_versions(python_bin: str) -> dict:
    pip = os.path.join(os.path.dirname(python_bin), "pip") if os.path.dirname(python_bin) else "pip"
    try:
        out = subprocess.run([pip, "list"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        out = ""
    return {
        line.split()[0]: line.split()[1]
        for line in out.splitlines()
        if line.lower().startswith("simplicio")
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--arms", default=",".join(ARM_CHOICES),
        help=f"comma-separated arms to run, from {ARM_CHOICES} (default: all three)",
    )
    ap.add_argument(
        "--out", default=os.path.join(HERE, "results"),
        help="directory to write the append-only results.json history into",
    )
    ap.add_argument(
        "--work-dir", default=None,
        help="scratch directory for each arm's seeded repo (default: a temp dir under --out)",
    )
    ap.add_argument(
        "--python-bin", default=sys.executable,
        help="python interpreter used to run the harness-owned check_cadastro.py in each repo",
    )
    ap.add_argument(
        "--skip-report", action="store_true",
        help="write results.json only; skip rendering REPORT.html (matplotlib not required)",
    )
    args = ap.parse_args(argv)

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for arm in arms:
        if arm not in ARM_CHOICES:
            ap.error(f"unknown arm {arm!r}; choose from {ARM_CHOICES}")

    lc.keys_path()  # fail fast, before any work, if SIMPLICIO_BENCH_KEYS is unset/missing

    fixture_dir = os.path.join(HERE, "fixture")
    work_dir = args.work_dir or os.path.join(args.out, "_work")
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    loop_bin = None
    if "simplicio" in arms:
        loop_bin = _find_loop_bin()

    arms_results = {}
    if "normal" in arms:
        repo_dir = os.path.join(work_dir, "normal-repo")
        arms_results["normal"] = runner_normal.run_arm(fixture_dir, repo_dir, args.python_bin)
    if "simplicio" in arms:
        repo_dir = os.path.join(work_dir, "simplicio-repo")
        arms_results["simplicio"] = runner_loop.run_arm(
            arm="simplicio", fixture_dir=fixture_dir, repo_dir=repo_dir,
            loop_bin=loop_bin, python_bin=args.python_bin, loop_src=REPO_ROOT,
        )

    meta = {
        "model": lc.MODEL,
        "date": datetime.date.today().isoformat(),
        "main_commit": _short_sha(REPO_ROOT),
        "pip_versions": _pip_versions(loop_bin or sys.executable),
    }
    results = {"meta": meta, "arms": arms_results}

    short_sha = _short_sha(REPO_ROOT)
    out_path = os.path.join(args.out, f"{meta['date']}-{short_sha}.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"wrote {out_path}", file=sys.stderr)

    if not args.skip_report:
        import report

        html = report.build(results, args.out, current_path=out_path)
        report_path = os.path.join(HERE, "REPORT.html")
        with open(report_path, "w") as f:
            f.write(html)
        print(f"wrote {report_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
