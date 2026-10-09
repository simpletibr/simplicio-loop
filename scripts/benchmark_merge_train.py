#!/usr/bin/env python3
"""MEASURED before x after: serial integration vs the real merge train (#1504, criterion 5).

Builds a throwaway local git repo (real git, no network) with N feature branches, then times
(a) SERIAL integration (the "before": per PR, merge main into it, run the smoke command, merge it)
against (b) ``simplicio_loop.merge_train`` (``plan_train`` + ``run_train`` with a test callable that
merges the batch cumulatively on a temporary branch and runs the same smoke command). Repo setup is
outside the timed region; only the integration work is timed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simplicio_loop.merge_train import DEFAULT_MAX_BATCH, plan_train, run_train  # noqa: E402

SCOPE = (
    "Measures local git plus a local smoke command only (time per merge). It is NOT escalation rate "
    "and NOT dependency wait: those need a real drain and stay UNVERIFIED."
)
SMOKE = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "GIT_TERMINAL_PROMPT": "0"}


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=bench", "-c", "user.email=bench@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=repo, env=ENV, capture_output=True, text=True,
    )
    if out.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def bad_prs_for(n: int, k: int) -> list[int]:
    """K culprits spread evenly over 1..N (deterministic)."""
    return [1 + ((2 * j + 1) * n) // (2 * k) for j in range(k)]


def build_repo(root: Path, n: int, bad: set[int]) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / ".gitignore").write_text("__pycache__/\n")
    (repo / "README.md").write_text("benchmark repo\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    for i in range(1, n + 1):
        git(repo, "checkout", "-q", "-b", f"pr-{i}", "main")
        (repo / f"feat_{i}.py").write_text(f"VALUE = {i}\n")
        expected = i + 1 if i in bad else i
        (repo / f"test_feat_{i}.py").write_text(
            f"import feat_{i}\n\n\ndef test_feat_{i}():\n    assert feat_{i}.VALUE == {expected}\n"
        )
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", f"feat {i}")
    git(repo, "checkout", "-q", "main")
    return repo


class Smoke:
    def __init__(self, repo: Path):
        self.repo, self.runs = repo, 0

    def __call__(self) -> bool:
        self.runs += 1
        return subprocess.run(SMOKE, cwd=self.repo, env=ENV, capture_output=True).returncode == 0


def run_serial(repo: Path, prs: list[int]) -> dict:
    smoke = Smoke(repo)
    start = time.perf_counter()
    for pr in prs:
        git(repo, "checkout", "-q", f"pr-{pr}")
        git(repo, "merge", "-q", "--no-edit", "main")
        green = smoke()
        git(repo, "checkout", "-q", "main")
        if green:
            git(repo, "merge", "-q", "--no-ff", "--no-edit", f"pr-{pr}")
    return {"wall_ms": (time.perf_counter() - start) * 1000.0, "smoke_runs": smoke.runs, "bisect_steps": 0}


def run_merge_train(repo: Path, prs: list[int], max_batch: int) -> dict:
    smoke = Smoke(repo)

    def test_fn(batch: list[int]) -> bool:
        git(repo, "checkout", "-q", "-B", "train-tmp", "main")
        try:
            for pr in batch:
                git(repo, "merge", "-q", "--no-ff", "--no-edit", f"pr-{pr}")
            return smoke()
        finally:
            git(repo, "checkout", "-q", "main")

    def merge_fn(pr: int) -> None:
        git(repo, "merge", "-q", "--no-ff", "--no-edit", f"pr-{pr}")

    bisect_steps = 0
    start = time.perf_counter()
    for batch in plan_train(prs, order=prs, max_batch=max_batch):
        bisect_steps += asyncio.run(run_train(batch, test_fn, merge_fn)).bisect_steps
    wall_ms = (time.perf_counter() - start) * 1000.0
    git(repo, "branch", "-q", "-D", "train-tmp")
    return {"wall_ms": wall_ms, "smoke_runs": smoke.runs, "bisect_steps": bisect_steps}


def merged_prs(repo: Path, prs: list[int]) -> list[int]:
    merged = set(git(repo, "branch", "--merged", "main", "--format=%(refname:short)").split())
    return [pr for pr in prs if f"pr-{pr}" in merged]


def measure(mode: str, n: int, bad: list[int], max_batch: int) -> dict:
    prs = list(range(1, n + 1))
    with tempfile.TemporaryDirectory(prefix="merge-train-bench-") as tmp:
        repo = build_repo(Path(tmp), n, set(bad))
        result = run_serial(repo, prs) if mode == "serial" else run_merge_train(repo, prs, max_batch)
        result["merged_prs"] = merged_prs(repo, prs)
    return result


def summarize(runs: list[dict], n: int) -> dict:
    stable = {(r["smoke_runs"], r["bisect_steps"], tuple(r["merged_prs"])) for r in runs}
    if len(stable) != 1:
        raise RuntimeError(f"non-deterministic run outcome across repeats: {stable}")
    first = runs[0]
    walls = [r["wall_ms"] for r in runs]
    merged = first["merged_prs"]
    return {
        "wall_ms": walls,
        "median_wall_ms": statistics.median(walls),
        "merges": len(merged),
        "median_ms_per_merge": statistics.median(walls) / len(merged) if merged else None,
        "smoke_runs": first["smoke_runs"],
        "bisect_steps": first["bisect_steps"],
        "merged_prs": merged,
        "unmerged_prs": [pr for pr in range(1, n + 1) if pr not in merged],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=8, help="feature branches / PRs")
    ap.add_argument("--bad", type=int, default=0, help="PRs that deliberately fail the smoke command")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--max-batch", type=int, default=DEFAULT_MAX_BATCH)
    args = ap.parse_args(argv)
    if not (args.n >= 1 and 0 <= args.bad <= args.n and args.repeats >= 1 and args.max_batch >= 1):
        ap.error("need n>=1, 0<=bad<=n, repeats>=1, max-batch>=1")
    bad = bad_prs_for(args.n, args.bad) if args.bad else []
    runs = {"serial": [], "train": []}
    for _ in range(args.repeats):
        for mode in runs:  # fresh repo per run; alternate modes each repeat
            runs[mode].append(measure(mode, args.n, bad, args.max_batch))
    serial, train = (summarize(runs[m], args.n) for m in ("serial", "train"))
    report = {
        "schema": "simplicio.merge-train-benchmark/v1",
        "proof_kind": "MEASURED",
        "scope": SCOPE,
        "n": args.n,
        "bad_prs": bad,
        "repeats": args.repeats,
        "max_batch": args.max_batch,
        "smoke_command": " ".join(["python3", *SMOKE[1:]]),
        "serial": serial,
        "train": train,
        "speedup": serial["median_wall_ms"] / train["median_wall_ms"],
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
