"""Recompute the SWE-bench Verified table ONLY from raw run files (#1819).

Nothing is read from a summary, a cache or a stored cost field: every cost is recomputed from the token counts
and the price table stored in each raw file, with ``bench/llm_ab``'s own ``cost.cost_breakdown``. Every metric
gets a seeded percentile bootstrap CI (``swe_stats.bootstrap``). A row with fewer than 30 counted tasks is
refused unless ``--allow-small`` is given, and then it is labelled SMALL-N.

Usage::

    python3 bench/swebench/swe_aggregate.py <run_dir> [--seed 1819] [--resamples 10000] \
        [--format md|json] [--out FILE] [--allow-small] [--allow-synthetic]

``<run_dir>`` is a run directory holding ``raw/*.json`` (see ``swe_runner.py``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import swe_common as common
import swe_stats

DEFAULT_SEED = 1819
DEFAULT_RESAMPLES = swe_stats.DEFAULT_RESAMPLES
CONFIDENCE = 0.95
MIN_TASKS = common.MIN_TASKS
TABLE_SCHEMA = "simplicio-swebench-table/1"
_ARM_ORDER = {arm: i for i, arm in enumerate(common.LOOP_ARMS)}


class RawError(ValueError):
    """A raw run file, or a set of them, that must not be aggregated."""


class SmallSampleError(ValueError):
    """A row with fewer than MIN_TASKS counted tasks, without --allow-small."""


class RunSet(list):
    """The loaded raw runs plus the provenance and digest of the raw files they came from."""

    def __init__(self, *args):
        super().__init__(*args)
        self.digest = ""
        self.n_files = 0
        self.provenance: dict = {}


def _model_of(doc: dict, arm: str) -> str:
    return doc["arms"][arm]["model"]


def load_runs(run_dir) -> RunSet:
    """Validate and load every raw run file under ``<run_dir>/raw``; refuse anything inconsistent."""
    run_dir = Path(run_dir)
    raw_dir = run_dir / "raw"
    if not raw_dir.is_dir():
        raise RawError(f"{run_dir}: no raw/ directory; this is not a run directory")
    files = sorted(raw_dir.glob("*.json"))
    if not files:
        raise RawError(f"{raw_dir}: raw/ holds no run files")

    digest = hashlib.sha256()
    runs = RunSet()
    provenance: dict | None = None
    prices: dict[str, tuple] = {}
    seen: set = set()
    for path in files:
        data = path.read_bytes()
        digest.update(path.name.encode("utf-8") + b"\0" + data + b"\0")
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise RawError(f"{path.name}: not valid JSON ({e})") from None
        problems = common.validate_raw(doc)
        if problems:
            raise RawError(f"{path.name}: " + "; ".join(problems))

        meta = doc["meta"]
        arm = meta["arm"]
        model = _model_of(doc, arm)
        task = doc["arms"][arm]["tasks"][0]
        prov = {
            "harness_version": meta["harness_version"],
            "dataset": {"name": meta["dataset"]["name"], "revision": meta["dataset"]["revision"]},
            "manifest_id": meta["manifest_id"],
            "synthetic": bool(meta.get("synthetic", False)),
        }
        if provenance is None:
            provenance = prov
        elif prov != provenance:
            raise RawError(f"{path.name}: runs disagree on harness, dataset, manifest or synthetic flag; "
                           "refusing to mix them")

        pricing = meta["pricing"]
        if not pricing.get("available"):
            raise RawError(f"{path.name}: no price table for {model}; its cost cannot be recomputed")
        sig = common.price_signature(pricing)
        if model in prices and prices[model] != sig:
            raise RawError(f"{path.name}: price table for {model} differs from earlier runs of that model")
        prices[model] = sig

        key = (task["instance_id"], arm, model)
        if key in seen:
            raise RawError(f"{path.name}: duplicate run for instance {key[0]}, arm {arm}, model {model}")
        seen.add(key)

        totals = task["totals"]
        breakdown = _cost(totals, pricing)
        counted = task["status"] in common.COUNTED_STATUSES
        runs.append({
            "instance_id": task["instance_id"],
            "arm": arm,
            "model": model,
            "status": task["status"],
            "counted": counted,
            "success": bool(task["success"]) and counted,
            "wall_s": float(task["wall_s"]),
            "cost_usd": breakdown,
        })
    runs.digest = digest.hexdigest()
    runs.n_files = len(files)
    runs.provenance = provenance or {}
    return runs


def _cost(totals: dict, pricing: dict) -> float:
    """Token-computed cost of one task (llm_ab's cache-aware breakdown); stored cost fields are never read."""
    cost_mod = common.load_llm_ab("cost")
    return cost_mod.cost_breakdown(totals.get("prompt_tokens") or 0, totals.get("cached_tokens") or 0,
                                   totals.get("completion_tokens") or 0, pricing)["computed_cost_usd"]


# --- statistics -------------------------------------------------------------------------------------------
# A unit of a (model, arm) row is (success 0/1, cost_usd, wall_s) for one counted task.

def _pass_rate(units):
    return sum(u[0] for u in units) / len(units)


def _cost_per_solved(units):
    solved = sum(u[0] for u in units)
    return None if solved == 0 else sum(u[1] for u in units) / solved


def _wall(units):
    return sum(u[2] for u in units) / len(units)


_ROW_STATS = {"pass_rate": _pass_rate, "cost_per_solved": _cost_per_solved, "wall_s": _wall}


def _paired_delta_pass(units):
    return sum(u[0] - u[1] for u in units) / len(units)


def _paired_delta_wall(units):
    return sum(u[2] - u[3] for u in units) / len(units)


def _paired_delta_cps(units):
    on_solved = sum(u[0] for u in units)
    off_solved = sum(u[1] for u in units)
    if on_solved == 0 or off_solved == 0:
        return None
    return sum(u[4] for u in units) / on_solved - sum(u[5] for u in units) / off_solved


_PAIRED_STATS = {"delta_pass_rate": _paired_delta_pass, "delta_wall_s": _paired_delta_wall,
                 "delta_cost_per_solved": _paired_delta_cps}


def _empty_stat() -> dict:
    return {"est": None, "lo": None, "hi": None, "resamples": 0, "undefined": 0}


def _ci(units, stats: dict, seed: int, resamples: int) -> dict:
    if not units:
        return {name: _empty_stat() for name in stats}
    return swe_stats.bootstrap(units, stats, seed=seed, resamples=resamples, confidence=CONFIDENCE)


# --- table ----------------------------------------------------------------------------------------------------

def build_table(runs, *, seed: int = DEFAULT_SEED, resamples: int = DEFAULT_RESAMPLES, allow_small: bool = False,
                source: str | None = None) -> dict:
    """The published table as plain data. Refuses small rows unless ``allow_small``."""
    by_cell: dict[tuple, list] = {}
    for r in runs:
        by_cell.setdefault((r["model"], r["arm"]), []).append(r)
    cells = sorted(by_cell, key=lambda k: (k[0], _ARM_ORDER.get(k[1], 99)))

    plan_rows = []
    small = []
    for model, arm in cells:
        cell = by_cell[(model, arm)]
        counted = [r for r in cell if r["counted"]]
        plan_rows.append((model, arm, cell, counted))
        if len(counted) < MIN_TASKS:
            small.append(f"{model} / {arm}: {len(counted)} tasks")

    pairs_by_model: dict[str, list] = {}
    for model in sorted({m for m, _ in cells}):
        on = {r["instance_id"]: r for r in by_cell.get((model, "simplicio"), []) if r["counted"]}
        off = {r["instance_id"]: r for r in by_cell.get((model, "normal"), []) if r["counted"]}
        both = sorted(set(on) & set(off))
        pairs_by_model[model] = [(on[i], off[i]) for i in both]
        if len(both) < MIN_TASKS and both:
            small.append(f"{model} paired (loop on vs off): {len(both)} pairs")

    if small and not allow_small:
        raise SmallSampleError(
            "rows with fewer than " + str(MIN_TASKS) + " tasks: " + "; ".join(small)
            + ". Refusing to print them; pass --allow-small to print them labelled SMALL-N.")

    rows = []
    for model, arm, cell, counted in plan_rows:
        units = [(1.0 if r["success"] else 0.0, r["cost_usd"], r["wall_s"]) for r in counted]
        stats = _ci(units, _ROW_STATS, seed, resamples)
        rows.append({
            "model": model,
            "arm": arm,
            "loop": common.ARM_LOOP.get(arm),
            "label": common.ARM_LABELS.get(arm),
            "n": len(counted),
            "solved": sum(1 for r in counted if r["success"]),
            "excluded": len(cell) - len(counted),
            "small_n": len(counted) < MIN_TASKS,
            "pass_rate": stats["pass_rate"],
            "cost_per_solved": stats["cost_per_solved"],
            "wall_s": stats["wall_s"],
            "total_cost_usd": round(sum(r["cost_usd"] for r in counted), 10),
        })

    paired = []
    for model, pairs in pairs_by_model.items():
        if not pairs:
            continue
        units = [(on["success"] * 1.0, off["success"] * 1.0, on["wall_s"], off["wall_s"],
                  on["cost_usd"], off["cost_usd"]) for on, off in pairs]
        stats = _ci(units, _PAIRED_STATS, seed, resamples)
        paired.append({"model": model, "n_pairs": len(pairs), "small_n": len(pairs) < MIN_TASKS,
                       **{name: stats[name] for name in _PAIRED_STATS}})

    prov = getattr(runs, "provenance", None) or {}
    return {
        "schema": TABLE_SCHEMA,
        "meta": {
            "seed": seed,
            "resamples": resamples,
            "confidence": CONFIDENCE,
            "min_tasks": MIN_TASKS,
            "allow_small": bool(allow_small),
            "synthetic": bool(prov.get("synthetic", False)),
            "harness_version": prov.get("harness_version"),
            "dataset": prov.get("dataset"),
            "manifest_id": prov.get("manifest_id"),
            "raw_digest": getattr(runs, "digest", ""),
            "n_raw_files": getattr(runs, "n_files", len(runs)),
            "source": source,
        },
        "rows": rows,
        "paired": paired,
    }


# --- rendering --------------------------------------------------------------------------------------------------

def _fmt(stat: dict, scale: float, digits: int, pct: bool = False) -> str:
    est = stat.get("est")
    if est is None:
        return "n/a"
    suffix = "%" if pct else ""
    text = f"{est * scale:.{digits}f}{suffix}"
    if stat.get("lo") is not None and stat.get("hi") is not None:
        text += f" [{stat['lo'] * scale:.{digits}f}, {stat['hi'] * scale:.{digits}f}]"
    return text


def _dataset_text(dataset) -> str:
    if isinstance(dataset, dict):
        return f"{dataset.get('name')} @ {dataset.get('revision')}"
    return str(dataset)


def render_markdown(table: dict) -> str:
    meta = table["meta"]
    lines = ["# SWE-bench Verified: pass rate, cost per solved task, wall-clock", ""]
    if meta.get("synthetic"):
        lines += ["> SYNTHETIC: invented numbers for unit tests. NOT a benchmark result.", ""]
    lines += [
        f"- Raw run directory: `{meta.get('source')}`",
        f"- {meta['n_raw_files']} raw files; sha256 of their names and bytes: `{meta['raw_digest']}`",
        "- Dataset: " + _dataset_text(meta.get("dataset"))
        + f"; manifest_id `{meta.get('manifest_id')}`; harness {meta.get('harness_version')}",
        f"- Bootstrap: seed {meta['seed']}, {meta['resamples']} resamples, {int(meta['confidence'] * 100)}% percentile CI",
        "",
    ]
    any_small = any(r["small_n"] for r in table["rows"]) or any(p["small_n"] for p in table["paired"])
    if any_small:
        lines += [f"SMALL-N rows have fewer than {meta['min_tasks']} counted tasks; shown only with --allow-small.", ""]
    header = ("| Model | Arm | n | solved | excluded | pass rate [95% CI] | cost per solved, US$ [95% CI] | "
              "wall s per task [95% CI] | total US$ |")
    lines += [header, "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in table["rows"]:
        tag = " **SMALL-N**" if r["small_n"] else ""
        lines.append(
            f"| {r['model']} | {r['label']}{tag} | {r['n']} | {r['solved']} | {r['excluded']} | "
            f"{_fmt(r['pass_rate'], 100, 1, pct=True)} | {_fmt(r['cost_per_solved'], 1, 6)} | "
            f"{_fmt(r['wall_s'], 1, 1)} | {r['total_cost_usd']:.6f} |")
    lines += ["", "Paired (same instances, loop on minus loop off):", "",
              "| Model | pairs | delta pass rate [95% CI] | delta wall s [95% CI] | delta cost per solved, US$ [95% CI] |",
              "|---|---:|---:|---:|---:|"]
    for p in table["paired"]:
        tag = " **SMALL-N**" if p["small_n"] else ""
        lines.append(
            f"| {p['model']}{tag} | {p['n_pairs']} | {_fmt(p['delta_pass_rate'], 100, 1, pct=True)} | "
            f"{_fmt(p['delta_wall_s'], 1, 1)} | {_fmt(p['delta_cost_per_solved'], 1, 6)} |")
    lines.append("")
    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Recompute the SWE-bench Verified table from raw run files.")
    ap.add_argument("run_dir")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    ap.add_argument("--allow-small", action="store_true", help="print rows with fewer than 30 tasks, as SMALL-N")
    ap.add_argument("--allow-synthetic", action="store_true", help="accept SYNTHETIC fixture runs (tests only)")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    ap.add_argument("--out", default=None, help="write the table to this file instead of stdout")
    args = ap.parse_args(argv)

    try:
        runs = load_runs(args.run_dir)
    except RawError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if runs.provenance.get("synthetic") and not args.allow_synthetic:
        print("error: these runs are SYNTHETIC (invented numbers for tests); refusing to publish them. "
              "--allow-synthetic is for the test suite only.", file=sys.stderr)
        return 2
    try:
        table = build_table(runs, seed=args.seed, resamples=args.resamples, allow_small=args.allow_small,
                            source=str(args.run_dir))
    except SmallSampleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    text = json.dumps(table, indent=2, sort_keys=True) + "\n" if args.format == "json" else render_markdown(table)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
