#!/usr/bin/env python3
"""LLM A/B benchmark entry point: the real OpenCode agent, run twice per task
-- once with no simplicio-loop skill in the repo (``normal``), once with
``.claude/skills/simplicio-loop`` installed and the prompt prefixed with
``/simplicio-loop `` (``simplicio``) -- on 2 dependent HTML tasks (create,
then edit).

Both arms are driven by ``opencode_agent.run_opencode``: the real
``opencode`` CLI (npm ``opencode-ai``), not a hand-rolled tool-calling loop
(issue #1325 -- the retired ``agent.py`` measured a minimal Python loop
instead of a real agent harness). The ONLY differences between the arms are
whether the skill directory is installed into the arm's repo and whether the
prompt is prefixed -- see ``opencode_agent.build_prompt``/``install_skill``.
The simplicio arm decides for itself, turn by turn, whether and how to
invoke the skill -- this harness never scripts the wave flow directly.

Usage::

    SIMPLICIO_BENCH_KEYS=/path/to/keys.env \\
      SIMPLICIO_BENCH_OPENCODE_BIN=/path/to/node_modules/.bin/opencode \\
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
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import arms as bench_arms  # noqa: E402
import checker  # noqa: E402
import cost as bench_cost  # noqa: E402
import llm_client as lc  # noqa: E402
import opencode_agent as oc  # noqa: E402
import tasks as bench_tasks  # noqa: E402

# The classic 2-arm run (issue #1325/#1335, still the default here and what
# `standard.py`'s non-ablation matrix passes explicitly) keeps its exact
# historical behavior: `opencode_agent.run_opencode(skill=(arm == "simplicio"))`
# with the venv `bin/`-prefixed (not fully isolated) PATH. `arms.ARM_SPECS`
# (issue #1337) adds 5 more single/pair-operator arms and generalizes the
# isolation for any of them; `--arms` accepts all 7 (`ARM_CHOICES`), but
# `_spec_for` only applies spec-driven isolation to a NON-legacy arm name,
# so this default flow is unaffected -- see `standard.py --ablation` for the
# uniform-isolation run across all 7, including normal/simplicio.
LEGACY_ARMS = ("normal", "simplicio")
ARM_CHOICES = bench_arms.ARM_NAMES


def _spec_for(arm: str, force_isolate: bool = False) -> dict | None:
    """The ``arms.ARM_SPECS`` entry to apply for ``arm``, or ``None`` to keep
    the legacy (non-isolated) ``run_opencode`` code path. ``force_isolate``
    (``standard.py --ablation``) applies the spec even to ``normal``/
    ``simplicio`` so all arms in that run share one isolation contract."""
    if force_isolate or arm not in LEGACY_ARMS:
        return bench_arms.spec(arm)
    return None


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


def _install_random_spec(repo_dir: str) -> None:
    """Copy the drawn spec into the seeded repo so the harness checker can read it."""
    spec = os.environ.get("SIMPLICIO_BENCH_RANDOM_SPEC")
    if not spec:
        return
    dest = os.path.join(repo_dir, "tests", "random_spec.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    import shutil
    shutil.copy(spec, dest)


def build_batch_prompt(task_list: list[dict]) -> str:
    """The single user-prompt text for ``--batch``: ALL of ``task_list`` in
    ONE prompt, one ``opencode run`` session per arm (issue #1310 follow-up,
    carried over to the real-OpenCode driver by issue #1325). Per-arm
    skill-install/prefix behavior is applied by ``opencode_agent.run_opencode``
    (``skill=True``), not here."""
    return "\n\n".join(f"Task {t['index']}: {t['text']}" for t in task_list)


def _commit_if_changed(repo_dir: str, message: str) -> None:
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True, timeout=15,
    ).stdout
    if not status.strip():
        return
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, timeout=15)
    subprocess.run(
        ["git", "-c", "user.email=bench@example.com", "-c", "user.name=bench",
         "commit", "-q", "-m", message],
        cwd=repo_dir, check=True, timeout=15,
    )


def run_arm(arm: str, fixture_dir: str, repo_dir: str, python_bin: str,
            task_timeout: int, task_list: list[dict] | None = None,
            config_dir: str | None = None, settle_reads: int = oc.DEFAULT_SETTLE_READS,
            settle_interval_s: float = oc.DEFAULT_SETTLE_INTERVAL_S,
            settle_max_wait_s: float = oc.DEFAULT_SETTLE_MAX_WAIT_S,
            arm_spec: dict | None = None) -> dict:
    """``arm_spec`` (``arms.ARM_SPECS[...]``, issue #1337): when given, this
    arm's skills are installed via ``oc.install_skills``, its task prompt is
    prefixed with ``arm_spec["prompt_prefix"]``, and it runs under a fully
    isolated PATH (``oc.build_arm_path(arm_spec["bins"])``) instead of the
    legacy ``skill=(arm == "simplicio")``/unisolated-PATH code path. ``None``
    (the default) preserves that legacy path exactly, unchanged."""
    import time

    task_list = task_list if task_list is not None else bench_tasks.TASKS
    config_dir = config_dir or (repo_dir + "-oc-home")

    checker.seed_repo(fixture_dir, repo_dir)
    _install_random_spec(repo_dir)
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True, timeout=15)
    _commit_if_changed(repo_dir, "seed fixture")

    key = lc.get_key(arm)
    # Settle the ledger BEFORE the first task too (issue #1335), so task 1's
    # baseline is a stable reading, never whatever was mid-flight when this
    # arm's key was last used.
    usage_baseline = oc.poll_settled_usage(
        lambda: oc.fetch_key_usage_usd(key), reads=settle_reads, interval_s=settle_interval_s,
        max_wait_s=settle_max_wait_s,
    )["value"]

    results = {"arm": arm, "model": lc.MODEL, "tasks": []}
    total_wall_t0 = time.time()

    for task in task_list:
        idx = task["index"]
        stage = task["verify_stage"]
        task_checker = task.get("checker", "check_cadastro.py")

        task_wall_t0 = time.time()
        if arm_spec is not None:
            oc.install_skills(repo_dir, arm_spec["skills"])
            isolated_path = oc.build_arm_path(arm_spec["bins"])
            full_text = arm_spec["prompt_prefix"] + task["text"]
            agent_result = oc.run_opencode(
                arm, full_text, repo_dir, key=key,
                config_dir=config_dir, timeout=task_timeout, skill=False,
                isolated_path=isolated_path,
                usage_baseline=usage_baseline, settle_reads=settle_reads,
                settle_interval_s=settle_interval_s, settle_max_wait_s=settle_max_wait_s,
            )
        else:
            agent_result = oc.run_opencode(
                arm, task["text"], repo_dir, key=key,
                config_dir=config_dir, timeout=task_timeout, skill=(arm == "simplicio"),
                usage_baseline=usage_baseline, settle_reads=settle_reads,
                settle_interval_s=settle_interval_s, settle_max_wait_s=settle_max_wait_s,
            )
        # Next task's baseline is THIS task's settled (or best-effort last
        # observed) usage -- never the pre-task baseline, so no cost leaks
        # across tasks either way.
        usage_baseline = agent_result.get("usage_settled_value", usage_baseline)
        task_wall_s = round(time.time() - task_wall_t0, 3)

        _commit_if_changed(repo_dir, f"{arm}: task {idx}")

        passed, check_out, _check_metrics = checker.run_check(repo_dir, stage, python_bin, checker=task_checker)

        task_record = {
            "index": idx,
            "kind": task["kind"],
            "task_text": task["text"],
            "success": passed,
            "turns": agent_result["turns"],
            "llm_calls": agent_result["llm_calls"],
            "commands": agent_result["commands"],
            "totals": agent_result["totals"],
            "final_text": agent_result["final_text"],
            "wall_s": task_wall_s,
            "check_output_tail": "\n".join(check_out.splitlines()[-30:]),
        }
        results["tasks"].append(task_record)
        print(f"[{arm}] task {idx} success={passed} turns={agent_result['turns']}", file=sys.stderr)

    results["total_wall_s"] = round(time.time() - total_wall_t0, 3)
    last_task = task_list[-1]
    final_passed, final_out, _ = checker.run_check(
        repo_dir, last_task["verify_stage"], python_bin, checker=last_task.get("checker", "check_cadastro.py")
    )
    results["final"] = {
        "check_passed": final_passed,
        "check_output_tail": "\n".join(final_out.splitlines()[-30:]),
    }
    return results


def run_arm_batch(arm: str, fixture_dir: str, repo_dir: str, python_bin: str,
                   task_timeout: int, task_list: list[dict],
                   config_dir: str | None = None, settle_reads: int = oc.DEFAULT_SETTLE_READS,
                   settle_interval_s: float = oc.DEFAULT_SETTLE_INTERVAL_S,
                   settle_max_wait_s: float = oc.DEFAULT_SETTLE_MAX_WAIT_S,
                   arm_spec: dict | None = None) -> dict:
    """``--batch``: ALL of ``task_list`` in ONE agent session for this arm
    (issue #1310 follow-up, carried over to the real-OpenCode driver by
    issue #1325) -- the same seeded repo, but a single
    ``opencode_agent.run_opencode`` call instead of one per task. Acceptance
    is still checked per task by the harness afterwards, running each
    task's own ``checker``/``verify_stage`` against the final tree the
    session left -- the per-task acceptance checks are cumulative (a later
    stage's checker is a superset of an earlier one's), so this is
    equivalent to checking each task right after the model would have
    finished it.

    Per-call metrics (tokens/cost/commands) belong to the ONE shared
    session, not to any single task -- they are attached in full to the
    first task's record (``tasks[0]``) and left empty on the rest, so every
    existing ``aggregate.py`` sum (which iterates ``tasks``) still counts
    each LLM call/command exactly once instead of once per task.
    """
    import time

    config_dir = config_dir or (repo_dir + "-oc-home")

    checker.seed_repo(fixture_dir, repo_dir)
    _install_random_spec(repo_dir)
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True, timeout=15)
    _commit_if_changed(repo_dir, "seed fixture")

    key = lc.get_key(arm)
    usage_baseline = oc.poll_settled_usage(
        lambda: oc.fetch_key_usage_usd(key), reads=settle_reads, interval_s=settle_interval_s,
        max_wait_s=settle_max_wait_s,
    )["value"]

    batch_prompt = build_batch_prompt(task_list)
    total_wall_t0 = time.time()
    if arm == "simplicio" and arm_spec is None and os.environ.get("SIMPLICIO_BENCH_TURBO", "1") != "0":
        from simplicio_loop.turbo import run_turbo
        from simplicio_loop import turbo_provider

        agent_result = run_turbo(Path(repo_dir), task_list, turbo_complete)
        losers = turbo_provider.drain_hedges()  # the losing side of a hedged call is billed too
        agent_result["llm_calls"] = list(agent_result["llm_calls"]) + losers
        for key_name in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens"):
            agent_result["totals"][key_name] += sum(c.get(key_name) or 0 for c in losers)
    elif arm_spec is not None:
        oc.install_skills(repo_dir, arm_spec["skills"])
        isolated_path = oc.build_arm_path(arm_spec["bins"])
        agent_result = oc.run_opencode(
            arm, arm_spec["prompt_prefix"] + batch_prompt, repo_dir, key=key,
            config_dir=config_dir, timeout=task_timeout * len(task_list), skill=False,
            isolated_path=isolated_path,
            usage_baseline=usage_baseline, settle_reads=settle_reads,
            settle_interval_s=settle_interval_s, settle_max_wait_s=settle_max_wait_s,
        )
    else:
        agent_result = oc.run_opencode(
            arm, batch_prompt, repo_dir, key=key,
            config_dir=config_dir, timeout=task_timeout * len(task_list), skill=(arm == "simplicio"),
            usage_baseline=usage_baseline, settle_reads=settle_reads,
            settle_interval_s=settle_interval_s, settle_max_wait_s=settle_max_wait_s,
        )
    total_wall_s = round(time.time() - total_wall_t0, 3)
    _commit_if_changed(repo_dir, f"{arm}: batch of {len(task_list)} tasks")

    results = {"arm": arm, "model": lc.MODEL, "tasks": [], "batch": True}
    for pos, task in enumerate(task_list):
        passed, check_out, _check_metrics = checker.run_check(
            repo_dir, task["verify_stage"], python_bin, checker=task.get("checker", "check_cadastro.py"),
        )
        shared = pos == 0
        task_record = {
            "index": task["index"],
            "kind": task["kind"],
            "task_text": task["text"],
            "success": passed,
            "turns": agent_result["turns"] if shared else 0,
            "llm_calls": agent_result["llm_calls"] if shared else [],
            "commands": agent_result["commands"] if shared else [],
            "totals": agent_result["totals"] if shared else oc.summarize([], []),
            "final_text": agent_result["final_text"] if shared else None,
            "wall_s": total_wall_s if shared else 0.0,
            "check_output_tail": "\n".join(check_out.splitlines()[-30:]),
        }
        results["tasks"].append(task_record)
        print(f"[{arm}] batch task {task['index']} success={passed}", file=sys.stderr)

    results["total_wall_s"] = total_wall_s
    last_task = task_list[-1]
    final_passed, final_out, _ = checker.run_check(
        repo_dir, last_task["verify_stage"], python_bin, checker=last_task.get("checker", "check_cadastro.py")
    )
    results["final"] = {
        "check_passed": final_passed,
        "check_output_tail": "\n".join(final_out.splitlines()[-30:]),
    }
    return results


def default_work_dir() -> str:
    """A STABLE dir OUTSIDE this repository, so an agent exploring its
    workspace can never wander into the simplicio-loop source tree.

    Issue #1336: this used to be a fresh ``tempfile.mkdtemp`` per invocation,
    so each arm's repo (and OpenCode's own config/data dirs, derived from
    the same work dir) lived at a different random path every run. OpenCode
    puts the working directory in its system prompt, so a random path made
    the first and largest call of every task -- system + skill prompt --
    unable to hit the model provider's prompt cache across sessions, even
    though nothing about the repo or skill content had changed. A fixed
    path makes that prefix byte-identical run over run; each arm's own
    subdirectory is still wiped and reseeded by ``checker.seed_repo`` before
    every ``run_arm``/``run_arm_batch`` call, so reuse is safe."""
    path = os.path.join(tempfile.gettempdir(), "llm-ab")
    os.makedirs(path, exist_ok=True)
    return path


def turbo_complete(arm: str, messages: list[dict], **kwargs) -> dict:
    """The turbo arm's model call is the product's own (``simplicio_loop.turbo_provider``),
    so the benchmark measures what ``simplicio-loop turbo`` sends: the arm's pinned
    OpenRouter session and reasoning off. ``SIMPLICIO_BENCH_TURBO_REASONING=on``
    (``--turbo-reasoning``) keeps the model's default reasoning on."""
    from simplicio_loop import turbo_provider

    reasoning_on = os.environ.get("SIMPLICIO_BENCH_TURBO_REASONING", "").lower() == "on"
    return turbo_provider.complete(arm, messages, api_key=lc.get_key(arm),
                                   session_id=oc.session_id_for_arm(arm), reasoning_off=not reasoning_on, **kwargs)


def result_filename(date: str, short_sha: str, task_count: int, batch: bool = False,
                    independent: bool = False, hard: bool = False, reasoning: bool = False) -> str:
    """``<date>-<short_sha>-t<task_count>[-batch].json`` -- the task count is
    part of the filename so ``aggregate.load_history``/report history
    diffing never mixes runs with a different task set (a 2-task run and a
    4-task run aren't comparable); ``-batch`` (issue #1310 follow-up) keeps a
    ``--batch`` run's history separate from a sequential run's, for the same
    reason -- one LLM session for all tasks measures something different
    from one session per task."""
    suffix = ("-batch" if batch else "") + ("-ind" if independent else "") + ("-hard" if hard else "")
    suffix += "-reason" if reasoning else ""
    return f"{date}-{short_sha}-t{task_count}{suffix}.json"


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--arms", default=",".join(LEGACY_ARMS),
        help=(
            f"comma-separated arms to run, from {ARM_CHOICES} (default: the classic "
            "normal,simplicio pair; the 5 single/pair-operator arms from arms.ARM_SPECS "
            "-- issue #1337 -- run isolated per --isolate-arms below)"
        ),
    )
    ap.add_argument(
        "--tasks", type=int, default=2, choices=bench_tasks.TASK_SET_CHOICES,
        help=(
            "how many benchmark tasks to run (default: 2). 1: cadastro.html "
            "create only. 2: cadastro.html create+edit. 4: cadastro.html "
            "create+edit, then login.html create+edit."
        ),
    )
    ap.add_argument(
        "--out", default=os.path.join(HERE, "results"),
        help="directory to write the append-only results.json history into",
    )
    ap.add_argument(
        "--work-dir", default=None,
        help=(
            "scratch directory for each arm's seeded repo (default: a STABLE "
            "path, `<tmpdir>/llm-ab`, reused and re-seeded every run -- issue "
            "#1336, so OpenCode's system prompt stays byte-identical across "
            "sessions for prompt-cache hits)"
        ),
    )
    ap.add_argument(
        "--python-bin", default=sys.executable,
        help="python interpreter used to run the harness-owned check_cadastro.py in each repo",
    )
    ap.add_argument(
        "--task-timeout", type=int, default=oc.DEFAULT_RUN_TIMEOUT,
        help=(
            "timeout in seconds for one `opencode run` invocation per task "
            f"(default: {oc.DEFAULT_RUN_TIMEOUT}; OpenCode manages its own internal "
            "turn loop, so this is the only cap this harness imposes -- there is no "
            "per-turn --max-turns/--cmd-timeout the way the retired Python loop had)"
        ),
    )
    ap.add_argument(
        "--skip-report", action="store_true",
        help="write results.json only; skip rendering REPORT.html (matplotlib not required)",
    )
    ap.add_argument(
        "--settle-reads", type=int, default=oc.DEFAULT_SETTLE_READS,
        help=(
            "consecutive equal key-usage reads required to call the OpenRouter ledger "
            f"settled after a task (default: {oc.DEFAULT_SETTLE_READS}; issue #1335)"
        ),
    )
    ap.add_argument(
        "--settle-interval", type=float, default=oc.DEFAULT_SETTLE_INTERVAL_S,
        help=f"seconds between settle-poll reads (default: {oc.DEFAULT_SETTLE_INTERVAL_S})",
    )
    ap.add_argument(
        "--settle-max-wait", type=float, default=oc.DEFAULT_SETTLE_MAX_WAIT_S,
        help=(
            "max seconds to wait for the ledger to settle before falling back to the "
            f"token-computed cost (default: {oc.DEFAULT_SETTLE_MAX_WAIT_S})"
        ),
    )
    ap.add_argument(
        "--batch", action="store_true",
        help=(
            "run ALL tasks in ONE user prompt / one agent session per arm, instead of one "
            "session per task; acceptance is still checked per task after the session finishes"
        ),
    )
    ap.add_argument(
        "--turbo", action="store_true",
        help=(
            "Simplicio surveys with Mapper once, then one OpenCode session "
            "that must run orient, prepare, edit plans, tick or wave, and "
            "verify. Normal stays one session per task."
        ),
    )
    ap.add_argument(
        "--independent", action="store_true",
        help=(
            "--tasks 10 only: the ten pages without the standard dependency chain, "
            "so the wave can fan them out; written as <date>-<sha>-t10-ind.json"
        ),
    )
    ap.add_argument(
        "--hard", action="store_true",
        help=(
            "--tasks 4 only: the hard Python set on fixture_hard/ (logic, bug fix, two-file "
            "refactor, parser) checked by hidden tests outside the arm repo; results ...-t4-hard.json"
        ),
    )
    ap.add_argument(
        "--turbo-reasoning", action="store_true",
        help=(
            "keep the model's default reasoning on the turbo calls (default: off); "
            "results get a -reason suffix"
        ),
    )
    ap.add_argument(
        "--random", action="store_true",
        help="Draw 2 tasks at run time and compare them with --turbo.",
    )
    ap.add_argument(
        "--isolate-arms", action="store_true",
        help=(
            "apply arms.ARM_SPECS-driven skill/PATH isolation (issue #1337) even to "
            "normal/simplicio, so every requested arm shares one isolation contract "
            "-- used by standard.py --ablation for a fair 7-arm comparison"
        ),
    )
    return ap


def main(argv=None) -> int:
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for arm in arms:
        if arm not in ARM_CHOICES:
            ap.error(f"unknown arm {arm!r}; choose from {ARM_CHOICES}")

    lc.keys_path()  # fail fast, before any work, if SIMPLICIO_BENCH_KEYS is unset/missing

    if args.random:
        from random_tasks import generate, write_spec
        drawn, spec = generate(2)
        spec_path = os.path.join(tempfile.gettempdir(), "simplicio-random-spec.json")
        write_spec(spec, Path(spec_path))
        os.environ["SIMPLICIO_BENCH_RANDOM_SPEC"] = spec_path
        os.environ["SIMPLICIO_BENCH_TURBO"] = "1"
        args.turbo = True
        task_list = drawn
        print("random tasks:", ", ".join(task["target"] for task in drawn), file=sys.stderr)
    else:
        if args.turbo and args.tasks != 10:
            ap.error("--turbo compares exactly 10 tasks")
        if args.turbo:
            os.environ["SIMPLICIO_BENCH_TURBO"] = "1"
        if args.independent and args.tasks != 10:
            ap.error("--independent applies to --tasks 10")
        if args.hard and args.tasks != 4:
            ap.error("--hard applies to --tasks 4")
        if args.hard:
            task_list = bench_tasks.hard_task_set()
        else:
            task_list = bench_tasks.task_set(args.tasks, independent=args.independent)
    if args.turbo_reasoning:
        os.environ["SIMPLICIO_BENCH_TURBO_REASONING"] = "on"

    fixture_dir = os.path.join(HERE, "fixture_hard" if args.hard else "fixture")
    work_dir = args.work_dir or default_work_dir()
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    pricing = lc.fetch_model_pricing()

    run_fn = run_arm_batch if args.batch else run_arm
    arms_results = {}
    for arm in arms:
        repo_dir = os.path.join(work_dir, f"{arm}-repo")
        config_dir = os.path.join(work_dir, f"{arm}-oc-home")
        # Turbo keeps the no-skill arm sequential (one cold session per task)
        # and folds the simplicio arm into one session after a single survey.
        # Turbo is the default simplicio arm: one Mapper read, then the model,
        # then dev-cli. Above three tasks that runs as an asyncio wave.
        arm_fn = run_arm_batch if arm == "simplicio" or args.batch else run_fn
        arms_results[arm] = arm_fn(
            arm, fixture_dir, repo_dir, args.python_bin, args.task_timeout,
            task_list=task_list, config_dir=config_dir,
            settle_reads=args.settle_reads, settle_interval_s=args.settle_interval,
            settle_max_wait_s=args.settle_max_wait,
            arm_spec=_spec_for(arm, force_isolate=args.isolate_arms),
        )

    # Token-computed cross-check (issue #1335): every task's totals gets
    # `computed_cost_usd`/`cost_divergence_pct`/`cost_flag` from its own
    # tokens and this run's pricing snapshot, and `cost_usd`/`cost_source`
    # fall back to the computed figure whenever the ledger never settled.
    for arm_data in arms_results.values():
        for task in arm_data.get("tasks", []):
            task["totals"] = bench_cost.finalize_task_cost(task.get("totals") or {}, pricing)

    meta = {
        "model": oc.OPENCODE_MODEL,
        "date": datetime.date.today().isoformat(),
        "main_commit": _short_sha(REPO_ROOT),
        "pip_versions": _pip_versions(sys.executable),
        "task_count": args.tasks,
        "pricing": pricing,
        "batch": args.batch,
        "agent": "opencode",
        "effort_policy": "opencode-managed (no per-call reasoning-effort control via the CLI)",
        "task_set": "hard" if args.hard else ("independent" if args.independent else "standard"),
        "turbo_reasoning": "on" if args.turbo_reasoning else "off",
    }
    results = {"meta": meta, "arms": arms_results}
    results["cost_report"] = {
        "pricing_table": bench_cost.pricing_table(pricing),
        "cost_table": bench_cost.cost_table(results, pricing),
    }

    short_sha = _short_sha(REPO_ROOT)
    out_path = os.path.join(args.out, result_filename(
        meta["date"], short_sha, args.tasks, batch=args.batch, independent=args.independent,
        hard=args.hard, reasoning=args.turbo_reasoning,
    ))
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
