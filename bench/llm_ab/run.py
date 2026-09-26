#!/usr/bin/env python3
"""LLM A/B benchmark entry point: the SAME agentic coding loop, run twice --
once with no simplicio-loop skill (``normal``), once given the
simplicio-loop SKILL.md text and told to invoke it (``simplicio``) -- on 2
dependent HTML tasks (create, then edit).

Both arms are driven by ``agent.run_agent``: an OpenAI-style tool-calling
loop with exactly one tool, ``bash``. The ONLY difference between the arms
is the prompt (see ``build_prompts`` below); nothing about the loop, the
tool, or the fixture differs. The simplicio arm decides for itself, turn by
turn, whether and how to run ``simplicio-loop`` -- this harness never
scripts the wave flow directly.

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
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
SKILL_PATH = os.path.join(REPO_ROOT, ".claude", "skills", "simplicio-loop", "SKILL.md")
sys.path.insert(0, HERE)

import agent  # noqa: E402
import checker  # noqa: E402
import llm_client as lc  # noqa: E402
import tasks as bench_tasks  # noqa: E402

ARM_CHOICES = ("normal", "simplicio")

BASE_SYSTEM_PROMPT = (
    "You are a coding agent working in a git repository via a bash tool. "
    "Complete the task, then reply DONE with a one-line summary."
)


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


def _read_skill_text() -> str:
    with open(SKILL_PATH, encoding="utf-8") as f:
        return f.read()


def build_prompts(arm: str, task: dict) -> tuple[str, str]:
    """``(system_prompt, user_prompt)`` for one task in one arm.

    ``normal``: the base system prompt, plain task text as the user prompt.
    ``simplicio``: the base system prompt plus the full simplicio-loop
    SKILL.md text, and the user prompt prefixed with ``/simplicio-loop `` --
    the agent decides on its own whether/how to run the skill's commands.
    """
    if arm == "simplicio":
        system_prompt = BASE_SYSTEM_PROMPT + "\n\nSKILL (simplicio-loop):\n" + _read_skill_text()
        user_prompt = "/simplicio-loop " + task["text"]
    else:
        system_prompt = BASE_SYSTEM_PROMPT
        user_prompt = task["text"]
    return system_prompt, user_prompt


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
            max_turns: int, cmd_timeout: int) -> dict:
    import time

    checker.seed_repo(fixture_dir, repo_dir)
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True, timeout=15)
    _commit_if_changed(repo_dir, "seed fixture")

    results = {"arm": arm, "model": lc.MODEL, "tasks": []}
    total_wall_t0 = time.time()

    for task in bench_tasks.TASKS:
        idx = task["index"]
        stage = task["verify_stage"]
        system_prompt, user_prompt = build_prompts(arm, task)

        task_wall_t0 = time.time()
        agent_result = agent.run_agent(
            arm, system_prompt, user_prompt, repo_dir,
            max_turns=max_turns, cmd_timeout=cmd_timeout,
        )
        task_wall_s = round(time.time() - task_wall_t0, 3)

        _commit_if_changed(repo_dir, f"{arm}: task {idx}")

        passed, check_out, _check_metrics = checker.run_check(repo_dir, stage, python_bin)

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
    final_passed, final_out, _ = checker.run_check(repo_dir, bench_tasks.TASKS[-1]["verify_stage"], python_bin)
    results["final"] = {
        "check_passed": final_passed,
        "check_output_tail": "\n".join(final_out.splitlines()[-30:]),
    }
    return results


def default_work_dir() -> str:
    """A fresh temp dir OUTSIDE this repository, so an agent exploring its
    workspace can never wander into the simplicio-loop source tree."""
    return tempfile.mkdtemp(prefix="llm-ab-")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--arms", default=",".join(ARM_CHOICES),
        help=f"comma-separated arms to run, from {ARM_CHOICES} (default: both)",
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
        "--max-turns", type=int, default=30,
        help="max agent turns (LLM calls) per task before giving up (default: 30)",
    )
    ap.add_argument(
        "--cmd-timeout", type=int, default=180,
        help="timeout in seconds for each bash-tool command the agent runs (default: 180)",
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
    work_dir = args.work_dir or default_work_dir()
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)

    arms_results = {}
    for arm in arms:
        repo_dir = os.path.join(work_dir, f"{arm}-repo")
        arms_results[arm] = run_arm(
            arm, fixture_dir, repo_dir, args.python_bin, args.max_turns, args.cmd_timeout,
        )

    meta = {
        "model": lc.MODEL,
        "date": datetime.date.today().isoformat(),
        "main_commit": _short_sha(REPO_ROOT),
        "pip_versions": _pip_versions(sys.executable),
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
