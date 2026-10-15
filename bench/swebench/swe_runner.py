"""SWE-bench Verified benchmark runner (#1819): instances x models x arms, one raw JSON per run.

Arms are the ``bench/llm_ab`` loop arms: ``normal`` (loop OFF) and ``simplicio`` (loop ON, skill installed and the
prompt prefixed with ``/simplicio-loop ``, from ``bench/llm_ab/arms.py``). Models come from the environment
(``SIMPLICIO_SWEBENCH_MODELS``, at least two). Each run writes one raw JSON in the ``bench/llm_ab`` results
schema (see ``swe_common.build_raw_doc``); ``swe_aggregate.py`` recomputes the table from those files alone.

``--dry-run`` validates every input and prints the plan, and writes nothing. It is the only mode a session
without API keys, docker or a budget should run. A live run needs: keys.env (OR_KEY_NORMAL, OR_KEY_SIMPLICIO),
an opencode binary, docker, the ``swebench`` package, a VERIFIED manifest and the instance cache built by
``swe_runner.py fetch``. The live adapters (``_live_agent``, ``_live_eval``) are NOT exercised by the test suite,
which injects fakes; they are UNVERIFIED until a real run has been made.

Commands::

    python3 bench/swebench/swe_runner.py --dry-run --budget-usd 20 [--models a/x,b/y] [--arms normal,simplicio]
    python3 bench/swebench/swe_runner.py --budget-usd 20 --out bench/swebench/results     # live, needs keys
    python3 bench/swebench/swe_runner.py fetch --out bench/swebench/.cache/instances.json  # needs the dataset
"""
from __future__ import annotations

import argparse
import datetime
import functools
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import swe_common as common
import swe_manifest as sm

REPO_ROOT = common.REPO_ROOT
MODELS_ENV = "SIMPLICIO_SWEBENCH_MODELS"
KEYS_ENV = "SIMPLICIO_BENCH_KEYS"
OPENCODE_ENV = "SIMPLICIO_BENCH_OPENCODE_BIN"
INSTANCES_ENV = "SIMPLICIO_SWEBENCH_INSTANCES"
DEFAULT_INSTANCES = os.path.join(HERE, ".cache", "instances.json")
DEFAULT_OUT = common.DEFAULT_RESULTS_DIR
DEFAULT_TIMEOUT_S = 1800
ARMS = common.LOOP_ARMS
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_ARM_SPECS = common.load_llm_ab("arms").ARM_SPECS
_LLM = common.load_llm_ab("llm_client")
ARM_KEY_NAMES = _LLM.ARM_KEY_NAMES
REAL_PROBES = {"which": shutil.which, "has_module": lambda name: importlib.util.find_spec(name) is not None}


class AgentTimeout(Exception):
    """The agent ran out of its time limit: a failed attempt, counted as a miss."""


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


# --- arms, models, plan ---------------------------------------------------------------------------------

def arm_prompt_prefix(arm: str) -> str:
    return _ARM_SPECS[arm]["prompt_prefix"]


def build_prompt(arm: str, instance: dict) -> str:
    """The text an arm sends for one instance: the arm's prefix (if any) plus the issue text."""
    return arm_prompt_prefix(arm) + instance["problem_statement"]


def parse_models(text: str) -> list[str]:
    return [m.strip() for m in (text or "").split(",") if m.strip()]


def validate_models(models: list[str]) -> list[str]:
    problems = []
    if len(models) < 2:
        problems.append(f"need at least 2 models, got {len(models)} (set {MODELS_ENV} or --models)")
    seen: set[str] = set()
    for m in models:
        if m in seen:
            problems.append(f"duplicate model {m!r}")
        seen.add(m)
        if not _MODEL_RE.match(m):
            problems.append(f"malformed model id {m!r}")
    return problems


def validate_arms(arms: list[str]) -> list[str]:
    problems = [f"unknown arm {a!r}; choose from {', '.join(ARMS)}" for a in arms if a not in ARMS]
    if not arms:
        problems.append("no arms selected")
    return problems


def build_plan(manifest: dict, models: list[str], arms: list[str], limit: int | None = None) -> list[dict]:
    """instances x models x arms, instance-major so both arms of one instance and model stay adjacent."""
    instances = list(manifest["instances"])
    if limit is not None:
        instances = instances[:limit]
    plan = []
    for inst in instances:
        for model in models:
            for arm in arms:
                plan.append({"run_key": f"{inst['instance_id']}@{arm}@{model}", "instance": inst,
                             "model": model, "arm": arm})
    return plan


def run_cost(totals: dict, pricing: dict | None) -> float | None:
    """Token-computed cost with llm_ab's cache-aware breakdown; None when there is no price table."""
    if not pricing or not pricing.get("available"):
        return None
    cost = common.load_llm_ab("cost")
    return cost.cost_breakdown(totals.get("prompt_tokens") or 0, totals.get("cached_tokens") or 0,
                               totals.get("completion_tokens") or 0, pricing)["computed_cost_usd"]


# --- executing a plan ------------------------------------------------------------------------------------------

def _zero_totals() -> dict:
    return {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0}


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _load_valid(path: Path):
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        doc = None
    if doc is None or common.validate_raw(doc):
        raise RuntimeError(f"{path} exists but is not a valid raw run; move it aside before resuming")
    return doc


def _run_one(job: dict, agent_fn, eval_fn) -> dict:
    out = {"status": "ok", "success": False, "totals": _zero_totals(), "turns": 0, "error": None, "tail": "",
           "final_text": None, "patch_sha256": None}
    try:
        res = agent_fn(job)
    except AgentTimeout as e:
        out.update(status="agent_timeout", error=str(e))
        return out
    except Exception as e:  # noqa: BLE001 - by design: provider, docker or harness trouble is an infra_error
        out.update(status="infra_error", error=f"agent: {e}")
        return out
    patch = res.get("patch") or ""
    out["totals"] = {**_zero_totals(), **(res.get("totals") or {})}
    out["turns"] = res.get("turns") or 0
    out["final_text"] = res.get("final_text")
    out["patch_sha256"] = common.sha256_hex(patch)
    try:
        verdict = eval_fn(job, patch)
    except Exception as e:  # noqa: BLE001 - by design: an evaluator crash is an infra_error, never a miss
        out.update(status="infra_error", error=f"evaluator: {e}")
        return out
    out["success"] = bool(verdict["resolved"])
    out["tail"] = str(verdict.get("tail", ""))[-2000:]
    return out


def execute_plan(plan: list[dict], *, out_dir, manifest: dict, run_id: str, main_commit: str,
                 pricing_by_model: dict, agent_fn, eval_fn, budget_usd: float,
                 clock=time.monotonic, now_iso=_utc_now_iso) -> dict:
    """Run every job not already on disk; stop before a job once the computed spend reaches the cap.

    Writes ``<out_dir>/raw/<instance>@<arm>@<model>.json`` per run and ``<out_dir>/run.json`` at the end.
    A rerun resumes: finished runs are read back (and counted toward the cap), never repeated.
    """
    out_dir = Path(out_dir)
    raw_dir = out_dir / "raw"
    models = list(dict.fromkeys(j["model"] for j in plan))
    for model in models:
        pricing = pricing_by_model.get(model)
        if not pricing or not pricing.get("available"):
            raise RuntimeError(f"no price table for {model}: refusing to start, because the budget cap and the "
                               "recorded cost cannot be computed without it")
    raw_dir.mkdir(parents=True, exist_ok=True)
    dataset = {"name": manifest["dataset"]["name"], "revision": manifest["dataset"]["revision"]}
    summary = {"planned": len(plan), "completed": 0, "skipped": 0, "stopped": None}
    spent = 0.0
    for job in plan:
        inst, arm, model = job["instance"], job["arm"], job["model"]
        pricing = pricing_by_model[model]
        path = raw_dir / common.raw_filename(inst["instance_id"], arm, model)
        existing = _load_valid(path)
        if existing is not None:
            summary["skipped"] += 1
            summary["completed"] += 1
            spent += run_cost(existing["arms"][arm]["tasks"][0]["totals"], pricing) or 0.0
            continue
        if spent >= budget_usd:
            summary["stopped"] = "budget"
            break
        t0 = clock()
        outcome = _run_one(job, agent_fn, eval_fn)
        t1 = clock()
        doc = common.build_raw_doc(
            run_id=run_id, date=now_iso()[:10], main_commit=main_commit, model=model, pricing=pricing,
            dataset=dataset, manifest_id=manifest["manifest_id"], instance=inst, arm=arm,
            status=outcome["status"], success=outcome["success"], wall_s=round(t1 - t0, 4),
            totals=outcome["totals"], turns=outcome["turns"], error=outcome["error"],
            check_output_tail=outcome["tail"], patch_sha256=outcome["patch_sha256"],
            final_text=outcome["final_text"])
        _write_atomic(path, sm.dumps(doc))
        spent += run_cost(outcome["totals"], pricing) or 0.0
        summary["completed"] += 1
    status = "complete" if summary["stopped"] is None else f"stopped: {summary['stopped']}"
    run_doc = {
        "schema": common.RUN_SCHEMA,
        "run_id": run_id,
        "harness_version": common.HARNESS_VERSION,
        "date": now_iso(),
        "main_commit": main_commit,
        "manifest_id": manifest["manifest_id"],
        "dataset": dataset,
        "models": models,
        "arms": list(dict.fromkeys(j["arm"] for j in plan)),
        "planned": summary["planned"],
        "completed": summary["completed"],
        "skipped": summary["skipped"],
        "status": status,
        "budget_usd": budget_usd,
        "spent_usd_computed": round(spent, 8),
    }
    _write_atomic(out_dir / "run.json", sm.dumps(run_doc))
    return summary


# --- evaluator report and patch helpers (pure parts of the live adapters) ----------------------------------------

def prediction_line(instance_id: str, model_name: str, patch: str) -> str:
    return json.dumps({"instance_id": instance_id, "model_name_or_path": model_name, "model_patch": patch})


def parse_eval_report(path, instance_id: str) -> bool:
    """Verdict from a swebench summary report (``<model>.<run_id>.json``: resolved_ids / unresolved_ids / error_ids)."""
    path = Path(path)
    if not path.exists():
        raise RuntimeError(f"no evaluator report at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if instance_id in (data.get("error_ids") or []):
        raise RuntimeError(f"{instance_id} is in error_ids: the evaluator gave no verdict")
    if instance_id in (data.get("resolved_ids") or []):
        return True
    if instance_id in (data.get("unresolved_ids") or []):
        return False
    raise RuntimeError(f"no verdict for {instance_id} in {path}")


def extract_patch(repo_dir: str, base: str = "HEAD") -> str:
    """The agent's change against ``base``, excluding the harness's own skill and state directories."""
    def git(*args):
        return subprocess.run(["git", "-C", repo_dir, *args], check=True, capture_output=True, text=True)
    git("add", "-A", "--", ".", ":(exclude).claude", ":(exclude).simplicio-loop")
    return git("diff", "--cached", "--binary", base).stdout


def fetch_instances(manifest: dict, out_path, loader=None) -> int:
    """Write the instance cache (problem statements, gitignored) for the manifest's IDs, in manifest order.

    Refuses if the dataset is missing an ID or disagrees with the manifest's base_commit. Nothing is written then.
    """
    loader = loader or _load_hf
    ds = manifest["dataset"]
    by_id = {r["instance_id"]: r for r in loader(ds["name"], ds["revision"])}
    missing, moved, rows = [], [], []
    for inst in manifest["instances"]:
        row = by_id.get(inst["instance_id"])
        if row is None:
            missing.append(inst["instance_id"])
            continue
        if row.get("base_commit") != inst.get("base_commit"):
            moved.append(inst["instance_id"])
        rows.append({"instance_id": row["instance_id"], "repo": row["repo"], "base_commit": row["base_commit"],
                     "problem_statement": row["problem_statement"]})
    if missing:
        raise RuntimeError(f"dataset is missing {len(missing)} manifest IDs, e.g. {missing[:3]}")
    if moved:
        raise RuntimeError(f"base_commit differs from the manifest for {moved[:3]}")
    _write_atomic(Path(out_path), json.dumps(rows, indent=1) + "\n")
    return len(rows)


def _load_hf(name: str, revision: str) -> list[dict]:
    """LIVE ONLY: downloads the dataset at the pinned revision (needs network and the ``datasets`` package)."""
    from datasets import load_dataset
    ds = load_dataset(name, split=sm.DATASET_SPLIT, revision=revision)
    return [dict(r) for r in ds]


# --- live adapters (UNVERIFIED: not exercised by the test suite) -------------------------------------------------

def _checkout(instance: dict, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{instance['repo']}.git"], cwd=dest,
                   check=True)
    subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", instance["base_commit"]], cwd=dest, check=True)
    subprocess.run(["git", "checkout", "-q", "-f", "FETCH_HEAD"], cwd=dest, check=True)


def _live_agent(job: dict, *, keys: dict, workroot: Path, opencode_bin: str, timeout_s: int) -> dict:
    oa = common.load_llm_ab("opencode_agent")
    measure = common.load_llm_ab("measure")
    inst, arm, model = job["instance"], job["arm"], job["model"]
    key = keys[ARM_KEY_NAMES[arm]]
    slug = common.model_slug(model)
    repo = workroot / "repos" / f"{inst['instance_id']}@{arm}@{slug}"
    _checkout(inst, repo)
    cfg = workroot / "config" / f"{arm}@{slug}"
    cfg.mkdir(parents=True, exist_ok=True)
    oa.write_opencode_provider_config(str(cfg), arm)
    if arm == "simplicio":
        oa.install_skill(str(repo))
    prompt = oa.build_prompt(arm, inst["problem_statement"])
    env = oa.build_env(arm, key, str(cfg))
    cmd = oa.build_command(opencode_bin, str(repo), prompt, model=f"{oa.OPENCODE_PROVIDER}/{model}")
    baseline = oa.poll_settled_usage(lambda: oa.fetch_key_usage_usd(key))["value"]
    out, metrics = measure.run_subprocess(cmd, cwd=str(repo), timeout=timeout_s, env=env)
    if metrics.get("returncode") == -9:
        raise AgentTimeout(f"opencode exceeded {timeout_s}s")
    if metrics.get("returncode") != 0:
        raise RuntimeError(f"opencode exited {metrics.get('returncode')}")
    events = []
    for line in (out or "").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    parsed = oa.parse_run_events(events)
    totals = oa.summarize(parsed["llm_calls"], parsed["commands"])
    settled = oa.poll_settled_usage(lambda: oa.fetch_key_usage_usd(key))
    if baseline is not None and settled["settled"] and settled["value"] is not None:
        billed = round(settled["value"] - baseline, 8)
        totals.update(billed_cost_usd=billed, cost_usd=billed, cost_source="billed-settled")
    return {"patch": extract_patch(str(repo), base=inst["base_commit"]), "turns": parsed["turns"],
            "final_text": parsed["final_text"], "totals": totals}


def _live_eval(job: dict, patch: str, *, dataset: dict, run_id: str, workroot: Path, timeout_s: int) -> dict:
    iid, model = job["instance"]["instance_id"], job["model"]
    slug = common.model_slug(model)
    run_tag = f"{run_id}-{job['arm']}-{slug}-{iid}".replace("/", "_")
    pred_dir = workroot / "eval" / f"{iid}@{job['arm']}@{slug}"
    pred_dir.mkdir(parents=True, exist_ok=True)
    model_name = f"openrouter/{model}"
    (pred_dir / "predictions.jsonl").write_text(prediction_line(iid, model_name, patch) + "\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "swebench.harness.run_evaluation", "--dataset_name", dataset["name"],
           "--split", sm.DATASET_SPLIT, "--predictions_path", str(pred_dir / "predictions.jsonl"),
           "--instance_ids", iid, "--run_id", run_tag, "--max_workers", "1", "--report_dir", str(pred_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, cwd=str(pred_dir), check=False)
    tail = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"swebench evaluator exited {proc.returncode}")
    report = pred_dir / f"{model_name.replace('/', '__')}.{run_tag}.json"
    return {"resolved": parse_eval_report(report, iid), "tail": tail[-2000:]}


# --- CLI ---------------------------------------------------------------------------------------------------------

def _key_names(path: str):
    """Names only, never values: the keys file is read for presence checks."""
    try:
        with open(path, encoding="utf-8") as f:
            return {line.split("=", 1)[0].strip() for line in f if "=" in line and not line.lstrip().startswith("#")}
    except OSError:
        return None


def _read_keys(path: str) -> dict:
    keys = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    return keys


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="SWE-bench Verified runner: loop on vs off, two or more models.")
    ap.add_argument("--manifest", default=sm.DEFAULT_MANIFEST)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--budget-usd", type=float, default=None, help="hard spend cap in USD (required, > 0)")
    ap.add_argument("--models", default=None, help=f"comma list; default ${MODELS_ENV}")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--limit", type=int, default=None, help="only the first N manifest instances")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--dry-run", action="store_true", help="validate and print the plan; write nothing")
    return ap


def _fetch_main(argv: list[str], env: dict) -> int:
    ap = argparse.ArgumentParser(description="Build the instance cache from the dataset (LIVE: needs network).")
    ap.add_argument("--manifest", default=sm.DEFAULT_MANIFEST)
    ap.add_argument("--out", default=env.get(INSTANCES_ENV) or DEFAULT_INSTANCES)
    args = ap.parse_args(argv)
    try:
        man = sm.load_manifest(args.manifest)
        sm.require_runnable(man)
        n = fetch_instances(man, args.out)
    except (OSError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"wrote {n} instances to {args.out}")
    return 0


def main(argv=None, *, env=None, probes=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ if env is None else env)
    probes = probes or REAL_PROBES
    if argv and argv[0] == "fetch":
        return _fetch_main(argv[1:], env)
    args = _parser().parse_args(argv)

    problems: list[str] = []
    if args.budget_usd is None or args.budget_usd <= 0:
        problems.append("--budget-usd is required: a hard spend cap in USD, greater than 0")
    models = parse_models(args.models if args.models is not None else env.get(MODELS_ENV, ""))
    problems += validate_models(models)
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    problems += validate_arms(arms)
    if env.get("SIMPLICIO_BENCH_TURBO") == "1":
        problems.append("SIMPLICIO_BENCH_TURBO=1 rewrites the simplicio prompt; unset it for a comparable run")

    man = None
    try:
        man = sm.load_manifest(args.manifest)
        sm.require_runnable(man)
    except (OSError, ValueError) as e:
        problems.append(str(e) if isinstance(e, sm.ManifestError) else f"cannot read manifest {args.manifest}: {e}")
        man = None

    keys_file = env.get(KEYS_ENV, "").strip()
    if not keys_file:
        problems.append(f"{KEYS_ENV} is not set (keys.env with OR_KEY_NORMAL and OR_KEY_SIMPLICIO)")
    else:
        names = _key_names(keys_file)
        if names is None:
            problems.append(f"{KEYS_ENV} points to no readable file")
        else:
            for arm in arms:
                if ARM_KEY_NAMES.get(arm) not in names:
                    problems.append(f"missing {ARM_KEY_NAMES.get(arm)} in the keys file (value not printed)")

    oc = env.get(OPENCODE_ENV, "")
    if not oc or not os.path.isfile(oc) or not os.access(oc, os.X_OK):
        problems.append(f"{OPENCODE_ENV} must point at an executable opencode binary")

    inst_path = env.get(INSTANCES_ENV) or DEFAULT_INSTANCES
    if not os.path.isfile(inst_path):
        problems.append(f"{INSTANCES_ENV} points to no file ({inst_path}); build it with: swe_runner.py fetch")
    elif man is not None:
        try:
            cached = {r["instance_id"] for r in json.loads(Path(inst_path).read_text(encoding="utf-8"))}
        except (OSError, ValueError, KeyError, TypeError):
            cached = set()
            problems.append(f"{INSTANCES_ENV} is not a readable instance cache")
        absent = [r["instance_id"] for r in man["instances"] if r["instance_id"] not in cached]
        if absent and cached:
            problems.append(f"instance cache lacks {len(absent)} manifest IDs, e.g. {absent[:3]}")

    if not probes["which"]("docker"):
        problems.append("docker is not on PATH (the SWE-bench evaluator runs each instance in a container)")
    if not probes["which"]("git"):
        problems.append("git is not on PATH")
    if not probes["has_module"]("swebench"):
        problems.append("the python package swebench is not installed")

    if problems:
        print("This run cannot start (BLOCKED):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    plan = build_plan(man, models, arms, limit=args.limit)
    n_inst = len({j["instance"]["instance_id"] for j in plan})
    if args.dry_run:
        print(f"DRY RUN: {len(plan)} runs = {n_inst} instances x {len(models)} models x {len(arms)} arms; "
              f"budget cap US$ {args.budget_usd}; manifest_id {man['manifest_id']}; writes nothing.")
        print("models: " + ", ".join(models) + "; arms: " + ", ".join(arms))
        return 0

    commit = subprocess.run(["git", "-C", REPO_ROOT, "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, check=False)
    if commit.returncode != 0:
        print("error: cannot read the main commit with git rev-parse", file=sys.stderr)
        return 2
    run_id = args.run_id or f"{datetime.datetime.now(datetime.UTC):%Y-%m-%d}-{commit.stdout.strip()}"
    out_dir = Path(args.out) / run_id
    keys = _read_keys(keys_file)
    pricing = {m: _LLM.fetch_model_pricing(m) for m in models}
    workroot = Path(tempfile.mkdtemp(prefix="swebench-work-"))
    agent_fn = functools.partial(_live_agent, keys=keys, workroot=workroot, opencode_bin=oc,
                                 timeout_s=args.timeout_s)
    eval_fn = functools.partial(_live_eval, dataset=man["dataset"], run_id=run_id, workroot=workroot,
                                timeout_s=args.timeout_s)
    try:
        summary = execute_plan(plan, out_dir=out_dir, manifest=man, run_id=run_id, main_commit=commit.stdout.strip(),
                               pricing_by_model=pricing, agent_fn=agent_fn, eval_fn=eval_fn,
                               budget_usd=args.budget_usd)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"run {run_id}: {summary}")
    return 0 if summary["stopped"] is None else 3


if __name__ == "__main__":
    sys.exit(main())
