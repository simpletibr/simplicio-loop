#!/usr/bin/env python3
"""Squads drain benchmark (part of #1549): the same simulated load, drained with and without squads.

What is REAL here: the planner (`watcher247.squad_flow.plan_repo`: `squads.plan_squads_auto`, `squad_routing.route`,
`squad_capacity.recommend` on a real or a fixed probe), the merge train (`merge_train.plan_train` + `run_train`) and the metrics
(`squad_metrics.task_record` + `summarize_records`), plus the CPU time and the RSS of this process while it orchestrates.
What is SIMULATED: every task duration (`asyncio.sleep`, scaled down), the 15% first-attempt failures, the cost of one merge
and of one integration test. No model, no GitHub, no git: it is NOT a real drain with an LLM (#1549 stays open for that).

The executor is a faithful asyncio model of the rules, not the watcher tick: the real tick holds a repo lock for the whole
run of a worker, so on ONE repo it runs one worker at a time. This model is the /simplicio-loop squads flow instead: one
worktree per worker, workers in parallel up to the capacity plan, dependencies order only the merge (as `plan_squads`
does), and one serial merge writer.

Modes (the same load for each):
  baseline        the loop before squads: ONE worker, every PR tested and merged before the next task starts.
  squads-v2-off   SIMPLICIO_247_SQUADS_BASELINE=1: auto-sized squads, but routing, merge batch and contracts off (batch of 1).
  squads          squads v2: auto-sized squads, routing by complexity, merge train in batches of up to 4.
Probes (the machine the capacity plan sees):
  live            `squad_capacity.measure`: this host, with the load other jobs put on it (MEASURED).
  idle            a fixed idle 10-core host with 64 GiB free (SIMULATED machine, the same for any host).

Run: nice -n 10 python3 bench/benchmark_squads_drain.py --reps 5 [--json] [--out result.json]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import math
import os
import platform
import random
import resource
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simplicio_loop import merge_train, squad_capacity, squad_metrics, squad_routing  # noqa: E402
from simplicio_loop.watcher247 import squad_flow  # noqa: E402

SCHEMA = "simplicio.squads-drain-benchmark/v1"
SCOPE = (
    "SIMULATED drain: task durations, first-attempt failures, merge cost and integration-test cost are simulated "
    "(asyncio.sleep, scaled). The planner, the merge train, the metrics, the CPU time and the RSS of the orchestrator are real. "
    "Not a real drain with an LLM: that stays UNVERIFIED (#1549)."
)
MODES = ("baseline", "squads", "squads-v2-off")
PROBES = ("live", "idle")
LADDER = {squad_routing.EXECUTION: squad_routing.COORDINATION, squad_routing.COORDINATION: "planning"}
IDLE_CORES = 10
GIB = 1 << 30
MODULES = 8
METRICS = (  # (key, label) of the numbers the table and the JSON spread over the repetitions
    "wall_s", "prs_per_min", "dependency_wait_mean_s", "escalation_rate", "orchestrator_cpu_s", "cpu_pct_of_wall", "plan_ms",
    "load1_before", "load1_peak", "load1_after", "rss_peak_kib", "rss_start_kib", "workers", "squads", "max_concurrent_workers",
    "train_tests", "train_batches",
)


# ------------------------------------------------------------------------------------------------ the load (SIMULATED)


@dataclass(frozen=True)
class Task:
    number: int
    level: int
    deps: tuple[int, ...]
    module: int
    paths: tuple[str, ...]
    duration_s: float  # first attempt (simulated, unscaled)
    retry_duration_s: float  # the attempt after an escalation (simulated, unscaled)
    fails_first: bool


@dataclass(frozen=True)
class Load:
    seed: int
    tasks: tuple[Task, ...]
    params: tuple[tuple[str, object], ...]


def generate_load(seed: int = 1, n: int = 40, max_width: int = 12, depth: int = 5, fail_rate: float = 0.15,
                  dur_lo: float = 0.2, dur_hi: float = 1.5, cross_module_rate: float = 0.2, first_number: int = 101) -> Load:
    """A seeded DAG of `n` tasks in `depth` levels, the widest level exactly `max_width`, every other level 3..max_width-1.

    Every task above level 0 depends on 1 or 2 tasks of the level just below, so the chain is `depth` long. Durations are
    uniform in [dur_lo, dur_hi] seconds (simulated, unscaled); exactly round(fail_rate * n) tasks fail their first attempt.
    Each task owns one file; `cross_module_rate` of them also touch a second module (the router sends those to coordination).
    """
    rng = random.Random(seed)
    rest = n - max_width
    if depth < 2 or rest < 3 * (depth - 1) or rest > (max_width - 1) * (depth - 1):
        raise ValueError("n, depth and max_width cannot make a DAG with the widest level at max_width")
    while True:  # rejection sampling over the other levels; the loop ends fast for the default shape
        others = [rng.randint(3, max_width - 1) for _ in range(depth - 1)]
        if sum(others) == rest:
            break
    widest = rng.randrange(depth)
    widths = others[:widest] + [max_width] + others[widest:]
    numbers, level_of, deps_of = [], {}, {}
    cursor = first_number
    for level, width in enumerate(widths):
        row = list(range(cursor, cursor + width))
        cursor += width
        for number in row:
            level_of[number] = level
            below = numbers[-1] if numbers else []
            deps_of[number] = tuple(sorted(rng.sample(below, min(rng.choice((1, 1, 2)), len(below))))) if level else ()
        numbers.append(row)
    flat = [number for row in numbers for number in row]
    failing = set(rng.sample(flat, round(fail_rate * n)))
    tasks = []
    for number in flat:
        module = rng.randrange(MODULES)
        paths = [f"m{module}/t{number}.py"]
        if rng.random() < cross_module_rate:
            other = (module + 1 + rng.randrange(MODULES - 1)) % MODULES
            paths.append(f"m{other}/x{number}.py")
        tasks.append(Task(number, level_of[number], deps_of[number], module, tuple(paths),
                          round(rng.uniform(dur_lo, dur_hi), 3), round(rng.uniform(dur_lo, dur_hi), 3), number in failing))
    params = (("n", n), ("max_width", max_width), ("depth", depth), ("fail_rate", fail_rate), ("dur_lo", dur_lo),
              ("dur_hi", dur_hi), ("cross_module_rate", cross_module_rate))
    return Load(seed, tuple(tasks), params)


def issue_rows(load: Load) -> list[dict]:
    """The load as the issues `plan_repo` plans: dependencies in the real `depende de #N` syntax, files in backticks."""
    rows = []
    for t in load.tasks:
        lines = ["Tarefa simulada."]
        if t.deps:
            lines.append("depende de " + ", ".join(f"#{d}" for d in t.deps))
        lines.append("Arquivos: " + " ".join(f"`{p}`" for p in t.paths))
        rows.append({"number": t.number, "title": f"tarefa {t.number}", "body": "\n".join(lines),
                     "labels": [{"name": f"area:m{t.module}"}]})
    return rows


# ------------------------------------------------------------------------------------------------ metrics


def spread(values: list) -> dict:
    """n, median, min and max of the numbers in `values` (None entries are dropped, never counted as zero)."""
    nums = [v for v in values if v is not None]
    if not nums:
        return {"n": 0, "median": None, "min": None, "max": None}
    return {"n": len(nums), "median": statistics.median(nums), "min": min(nums), "max": max(nums)}


def run_metrics(records: list[dict], wall_s: float, merged: int) -> dict:
    """Throughput, mean dependency wait and escalation rate of one drain, from the real `squad_metrics` records."""
    summary = squad_metrics.summarize_records(records)
    waits = [r["dependency_wait_s"] for r in records if r.get("depends_on") and r.get("dependency_wait_s") is not None
             and r.get("proof_kind", {}).get("dependency_wait") == "measured"]
    return {
        "prs_per_min": round(merged / wall_s * 60.0, 3) if wall_s > 0 else None,
        "dependency_wait_mean_s": round(statistics.fmean(waits), 3) if waits else None,
        "dependency_wait_n": len(waits),
        "dependency_wait_p50_s": summary["dependency_wait_p50_s"],
        "dependency_wait_p95_s": summary["dependency_wait_p95_s"],
        "dependency_wait_max_s": summary["dependency_wait_max_s"],
        "escalation_rate": summary["escalation_rate"],
        "escalated": summary["escalated"],
        "escalation_n": summary["escalation_n"],
        "escalations_by_transition": summary["escalations_by_transition"],
    }


def _cpu_s() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def _rss_kib() -> tuple[int | None, int]:
    """(current RSS, peak RSS) in KiB from /proc/self/status (VmRSS, VmHWM); getrusage ru_maxrss when /proc cannot be read."""
    try:
        with open("/proc/self/status", encoding="utf-8") as fh:
            fields = {line.split(":")[0]: int(line.split()[1]) for line in fh if line.startswith(("VmRSS:", "VmHWM:"))}
        return fields["VmRSS"], fields["VmHWM"]
    except (OSError, KeyError, ValueError):
        return None, int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _load1() -> float | None:
    try:
        return os.getloadavg()[0]
    except OSError:
        return None


async def _sample_load(peak: list, stop: asyncio.Event, period_s: float = 0.25) -> None:
    while not stop.is_set():
        now = _load1()
        if now is not None:
            peak[0] = now if peak[0] is None else max(peak[0], now)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), period_s)


# ------------------------------------------------------------------------------------------------ the drain


def make_probe(kind: str) -> squad_capacity.Probe:
    if kind == "live":
        return squad_capacity.measure(".")
    if kind == "idle":
        return squad_capacity.Probe(cpu_count=IDLE_CORES, load_average=(0.0, 0.0, 0.0), memory_available_bytes=64 * GIB,
                                    disk_free_bytes=500 * GIB, observed_at_ns=time.time_ns())
    raise ValueError(f"probe must be one of {PROBES}: {kind!r}")


async def drain(load: Load, plan: squad_flow.RepoPlan, *, workers: int, hold_until_merged: bool, time_scale: float,
                test_cost_s: float, merge_cost_s: float, clock=time.monotonic) -> dict:
    """Run the planned tasks: a pool of `workers`, a serial merge writer, dependencies ordering the merge only."""
    by_number = {t.number: t for t in load.tasks}
    order = [step.issue for step in plan.plan.merge_order]
    pool = asyncio.Semaphore(workers)
    ready_at: dict[int, float] = {}
    merged_at: dict[int, float] = {}
    steps_of: dict[int, list[dict]] = {}
    ready: set[int] = set()
    merged: set[int] = set()
    merged_event = {n: asyncio.Event() for n in order}
    wake = asyncio.Event()
    state = {"running": 0, "peak": 0, "tests": 0, "bisect": 0}
    batches: list[int] = []

    async def work(number: int) -> None:
        task = by_number[number]
        async with pool:  # a slot frees when the PR is open (squads) or when it is merged (the loop before squads)
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
            role, steps = plan.routed[number], []
            await asyncio.sleep(task.duration_s * time_scale)
            if task.fails_first:
                steps.append({"role": role, "outcome": "failed", "reason": "verify_failed"})
                role = LADDER[role]  # the ladder goes up one role
                await asyncio.sleep(task.retry_duration_s * time_scale)
            steps.append({"role": role, "outcome": "ok"})
            steps_of[number] = steps
            state["running"] -= 1
            ready_at[number] = clock()  # the squad approved the PR
            ready.add(number)
            wake.set()
            if hold_until_merged:
                await merged_event[number].wait()

    async def test_fn(items: list[int]) -> bool:
        state["tests"] += 1
        await asyncio.sleep(test_cost_s * time_scale)
        return True

    async def merge_fn(number: int) -> None:
        await asyncio.sleep(merge_cost_s * time_scale)
        merged_at[number] = clock()
        merged.add(number)
        merged_event[number].set()

    async def writer() -> None:
        while len(merged) < len(order):
            wake.clear()
            eligible, accepted = [], set()
            for number in order:  # ready, and every dependency merged or ahead of it in this very batch
                if number in ready and number not in merged and all(d in merged or d in accepted for d in plan.deps[number]):
                    eligible.append(number)
                    accepted.add(number)
            if not eligible:
                await wake.wait()
                continue
            batch = merge_train.plan_train(eligible, order, max_batch=plan.merge_batch)[0]
            batches.append(len(batch))
            report = await merge_train.run_train(batch, test_fn, merge_fn)
            state["bisect"] += report.bisect_steps

    started = clock()
    jobs = [asyncio.ensure_future(work(n)) for n in order]
    await writer()
    await asyncio.gather(*jobs)
    wall_s = clock() - started
    ordered = all(merged_at[n] >= merged_at[d] for n in order for d in plan.deps[n])
    records = [{**squad_metrics.task_record(steps_of[n], plan.deps[n], ready_at.get(n), merged_at, "ok"), "issue": f"bench#{n}"}
              for n in order]
    return {"wall_s": wall_s, "merged": len(merged), "records": records, "max_concurrent_workers": state["peak"],
            "train_tests": state["tests"], "train_batches": len(batches), "train_batch_max": max(batches, default=0),
            "bisect_steps": state["bisect"], "invariants_ok": ordered and len(merged) == len(order)}


async def run_once(mode: str, probe_kind: str, seed: int = 1, time_scale: float = 1.0, test_cost_s: float = 0.25,
                   merge_cost_s: float = 0.10) -> dict:
    """One drain of the seeded load in `mode`; returns every number of one repetition."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}: {mode!r}")
    load = generate_load(seed=seed)
    rows = issue_rows(load)
    peak, stop = [_load1()], asyncio.Event()
    load_before = peak[0]
    sampler = asyncio.ensure_future(_sample_load(peak, stop))
    rss_start, _ = _rss_kib()
    cpu_start = _cpu_s()
    plan_started = time.perf_counter()
    probe = make_probe(probe_kind)
    limits = squad_capacity.Limits(workers=1, override_source="bench: the loop before squads") if mode == "baseline" \
        else squad_capacity.Limits()  # explicit, so SIMPLICIO_SQUADS and friends in the environment cannot move the result
    with contextlib.redirect_stdout(io.StringIO()):  # plan_repo logs its capacity line to stdout
        plan = squad_flow.plan_repo("bench", rows, "claude", probe, limits, mode="v2" if mode == "squads" else "baseline")
    plan_ms = (time.perf_counter() - plan_started) * 1000.0
    cap = plan.capacity
    result = await drain(load, plan, workers=cap["total_workers"], hold_until_merged=(mode == "baseline"),
                         time_scale=time_scale, test_cost_s=test_cost_s, merge_cost_s=merge_cost_s)
    cpu_s = _cpu_s() - cpu_start
    stop.set()
    await sampler
    _, rss_peak = _rss_kib()
    records = result.pop("records")
    metrics = run_metrics(records, result["wall_s"], result["merged"])
    return {
        "mode": mode, "probe": probe_kind, "seed": seed, "simulated": True, "time_scale": time_scale,
        "test_cost_s": test_cost_s, "merge_cost_s": merge_cost_s,
        **result, **metrics,
        "plan_ms": round(plan_ms, 3), "orchestrator_cpu_s": round(cpu_s, 4),
        "cpu_pct_of_wall": round(cpu_s / result["wall_s"] * 100.0, 3) if result["wall_s"] > 0 else None,
        "load1_before": load_before, "load1_peak": peak[0], "load1_after": _load1(),
        "rss_start_kib": rss_start, "rss_peak_kib": rss_peak,
        "workers": cap["total_workers"], "squads": cap["squads"], "workers_per_squad": cap["workers_per_squad"],
        "limited_by": cap["limited_by"], "capacity_proof_kind": cap["proof_kind"], "probe_load_average": cap["probe"]["load_average"],
        "initial_roles": dict(sorted(Counter(plan.routed.values()).items())), "plan_mode": plan.mode,
        "merge_batch": plan.merge_batch, "contracts": len(plan.plan.contracts),
    }


# ------------------------------------------------------------------------------------------------ the harness


def wait_for_load(limit: float, max_wait_s: float, poll_s: float = 5.0) -> float:
    """Sleep while load1 is above `limit`, at most `max_wait_s`; returns the seconds waited (0.0 when the load was low)."""
    waited = 0.0
    while waited < max_wait_s:
        now = _load1()
        if now is None or now <= limit:
            break
        time.sleep(poll_s)
        waited += poll_s
    return waited


def configs_for(modes: list[str], probes: list[str]) -> list[tuple[str, str]]:
    """(mode, probe) pairs. `baseline` is one worker whatever the machine is, so it runs once, on the first probe."""
    out = []
    for mode in modes:
        out.extend([(mode, probes[0])] if mode == "baseline" else [(mode, p) for p in probes])
    return out


def run_child(mode: str, probe: str, args: argparse.Namespace) -> dict:
    cmd = [sys.executable, str(Path(__file__).resolve()), "--one", "--mode", mode, "--probe", probe, "--seed", str(args.seed),
           "--time-scale", str(args.time_scale), "--test-cost", str(args.test_cost), "--merge-cost", str(args.merge_cost)]
    out = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if out.returncode:
        raise RuntimeError(f"{mode}/{probe} failed: {out.stderr.strip()[-500:]}")
    return json.loads(out.stdout)


def aggregate(runs: list[dict]) -> dict:
    first = runs[0]
    stable = {k: first[k] for k in ("merged", "escalated", "limited_by", "initial_roles", "merge_batch", "invariants_ok")}
    return {"mode": first["mode"], "probe": first["probe"], "reps": len(runs), "first_rep": stable,
            "all_invariants_ok": all(r["invariants_ok"] for r in runs),
            "metrics": {k: spread([r.get(k) for r in runs]) for k in METRICS},
            "workers_seen": sorted({r["workers"] for r in runs}), "runs": runs}


def _cell(s: dict, digits: int = 2) -> str:
    if not s["n"]:
        return "UNVERIFIED"
    f = lambda v: f"{v:.{digits}f}"  # noqa: E731
    return f(s["median"]) if s["min"] == s["max"] else f"{f(s['median'])} ({f(s['min'])}-{f(s['max'])})"


def render_table(result: dict) -> str:
    head = ("| Mode | Probe | Workers / squads | Wall s | PRs/min | Mean dep. wait s | Escalation | Orchestrator CPU s | Peak load1 | Peak RSS MiB |\n"
            "|---|---|---|---|---|---|---|---|---|---|")
    rows = [head]
    for c in result["configs"]:
        m = c["metrics"]
        rss = {"n": m["rss_peak_kib"]["n"], **{k: (m["rss_peak_kib"][k] / 1024 if m["rss_peak_kib"][k] is not None else None)
                                              for k in ("median", "min", "max")}}
        probe = "n/a (1 worker)" if c["mode"] == "baseline" else ("live (MEASURED)" if c["probe"] == "live" else "idle (SIMULATED)")
        rows.append("| {mode} | {probe} | {w} / {s} | {wall} | {ppm} | {dep} | {esc} | {cpu} | {load} | {rss} |".format(
            mode=c["mode"], probe=probe, w=_cell(m["workers"], 0), s=_cell(m["squads"], 0), wall=_cell(m["wall_s"]),
            ppm=_cell(m["prs_per_min"]), dep=_cell(m["dependency_wait_mean_s"], 3), esc=_cell(m["escalation_rate"], 3),
            cpu=_cell(m["orchestrator_cpu_s"], 3), load=_cell(m["load1_peak"]), rss=_cell(rss, 1)))
    return "\n".join(rows)


def harness(args: argparse.Namespace) -> dict:
    pairs = configs_for(args.modes, args.probes)
    runs: dict[tuple[str, str], list[dict]] = {pair: [] for pair in pairs}
    waits: list[dict] = []
    started = time.time()
    for rep in range(args.reps):  # repetition-major: every config sees the same drift of the host load
        for mode, probe in pairs:
            waited = wait_for_load(args.wait_load, args.wait_max)
            before = os.getloadavg()
            run = run_child(mode, probe, args)
            after = os.getloadavg()
            run.update(rep=rep + 1, waited_for_load_s=waited, harness_loadavg_before=list(before), harness_loadavg_after=list(after))
            if waited:
                waits.append({"rep": rep + 1, "mode": mode, "probe": probe, "waited_s": waited})
            runs[(mode, probe)].append(run)
    result = {
        "schema": SCHEMA, "proof_kind": "SIMULATED+MEASURED", "scope": SCOPE,
        "load": {"seed": args.seed, **dict(generate_load(args.seed).params), "time_scale": args.time_scale,
                 "test_cost_s": args.test_cost, "merge_cost_s": args.merge_cost, "label": "SIMULATED"},
        "host": {"cpu_count": os.cpu_count(), "python": platform.python_version(), "platform": platform.platform(),
                 "loadavg_at_start": list(os.getloadavg()), "idle_probe_cores": IDLE_CORES},
        "reps": args.reps, "wait_load_limit": args.wait_load, "load_waits": waits, "harness_wall_s": round(time.time() - started, 1),
        "configs": [aggregate(runs[pair]) for pair in pairs],
    }
    base = next((c for c in result["configs"] if c["mode"] == "baseline"), None)
    if base:  # derived from the two medians, nothing else
        b = base["metrics"]["wall_s"]["median"]
        for c in result["configs"]:
            w = c["metrics"]["wall_s"]["median"]
            c["wall_speedup_vs_baseline"] = round(b / w, 3) if w else None
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--probes", default=",".join(PROBES))
    ap.add_argument("--time-scale", type=float, default=1.0, help="multiplies every simulated duration (default 1: 0.2-1.5 s per task)")
    ap.add_argument("--test-cost", type=float, default=0.25, help="simulated seconds of one integration test of a merge batch")
    ap.add_argument("--merge-cost", type=float, default=0.10, help="simulated seconds of one PR merge")
    ap.add_argument("--wait-load", type=float, default=8.0, help="before each repetition wait while load1 is above this")
    ap.add_argument("--wait-max", type=float, default=600.0, help="most seconds to wait for the load to fall")
    ap.add_argument("--json", action="store_true", help="print the JSON document instead of the table")
    ap.add_argument("--out", help="also write the JSON document to this file")
    ap.add_argument("--one", action="store_true", help=argparse.SUPPRESS)  # internal: one repetition, printed as JSON
    ap.add_argument("--mode", help=argparse.SUPPRESS)
    ap.add_argument("--probe", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.one:
        print(json.dumps(asyncio.run(run_once(args.mode, args.probe, args.seed, args.time_scale, args.test_cost, args.merge_cost))))
        return 0
    args.modes, args.probes = [m for m in args.modes.split(",") if m], [p for p in args.probes.split(",") if p]
    if not (args.reps >= 1 and set(args.modes) <= set(MODES) and set(args.probes) <= set(PROBES) and args.modes and args.probes
            and args.time_scale > 0):
        ap.error(f"need reps>=1, time-scale>0, modes within {MODES}, probes within {PROBES}")
    result = harness(args)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{SCOPE}\nseed={args.seed} reps={args.reps} (median (min-max)); host load1 at start {result['host']['loadavg_at_start'][0]:.2f}\n")
        print(render_table(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
