"""Shared driver for the two simplicio-loop arms (`simplicio-files` and
`simplicio-fast`): orient -> prepare (both tasks, ONE run) -> per task
(orient warm -> LLM edit-plan -> tick) -> verify.

Per SKILL.md, the host (this script, driven by the benchmarked LLM) decides
each change as an exact find/replace edit plan; simplicio-dev-cli /
simplicio-loop freeze, apply and verify it. The loop itself never calls a
provider to write code.

Both tasks run inside ONE `prepare`d run (`tasks.md` carries both task
blocks) -- task 2 depends on task 1 and is ticked only after task 1's
operator receipt is applied, on the very tree task 1 left. Mapper/Fast
generation state is therefore shared across both tasks of a run; the cache
table this driver records is exactly that sharing (cold orient once, warm
orient once per task, compared against the immediately preceding call).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import checker  # noqa: E402
import llm_client as lc  # noqa: E402
import measure  # noqa: E402
import orient as orient_mod  # noqa: E402
import tasks as bench_tasks  # noqa: E402

EDIT_SYSTEM_PROMPT = (
    "You are a careful senior front-end engineer operating through a "
    "mechanical find/replace edit-plan interface (simplicio-dev-cli). You do "
    "not write files directly. You will be given bounded repository context "
    "(from `simplicio-loop orient`), the CURRENT full content of the target "
    "file for this task, and one task. Reply with ONLY a single JSON object "
    'of the exact shape {"operations": [{"path": "relative/path", "find": '
    '"<exact text, unique in the file>", "replace": "<new text>"}]} '
    "describing the minimal find/replace edits needed. `find` must match the "
    "CURRENT file content exactly and uniquely (copy it verbatim from the "
    "file content given, including whitespace). The target file may "
    "currently contain only a single-line 'SIMPLICIO-PLACEHOLDER' HTML "
    "comment marker -- to create the file for real, target that exact "
    "placeholder line as `find` and replace it with the full new file "
    "content. No markdown fences, no prose outside the JSON."
)


def write_task_md(path: str) -> None:
    """Write both benchmark tasks as one multi-task tasks.md, in order --
    `System:` starts a new task block (simplicio_loop.task_contract's
    MULTI_TASK_SPLIT_RE), so this compiles to exactly 2 tasks, task 2 after
    task 1. Every lane's verifier command is the harness-owned
    `check_cadastro.py` at that task's stage; no Coverage verifier line is
    declared (there is no Python application code to measure coverage on --
    the coverage lane is left genuinely not-applicable rather than faked).

    ``./cadastro.html`` (path-shaped) plus a pre-existing placeholder file in
    the fixture are both required for Mapper's target corridor to authorize
    a repo-root file as this run's edit target -- see bench/llm_ab/README.md
    "Mapper target-corridor assumption".
    """
    blocks = []
    for task in bench_tasks.TASKS:
        stage = task["verify_stage"]
        verifier = checker.verifier_line(stage)
        task_type = "Create" if task["kind"] == "create" else "Feature"
        depends_line = ""
        if task["depends_on"]:
            dep_system = bench_tasks.TASKS[task["depends_on"][0] - 1]["target"]
            depends_line = f"\n6. Dependencies\n\nDepends on: task {task['depends_on'][0]} ({dep_system})\n"
        blocks.append(f"""System: cadastro-html-task-{task['index']}
Feature: cadastro.html stage {stage}
Type: {task_type}

AS an end user
I WANT the registration form to satisfy stage {stage}
SO THAT the acceptance criteria below hold

1. Acceptance Criteria

Scenario 1: stage {stage} fields
  Given the repository
  When ./cadastro.html is edited per the task
  Then `{verifier}` exits 0 [RN01]

2. Business Rules

RN01 - {task['text']}
{depends_line}
8. Additional Information

Target: ./cadastro.html
Independent verifier: `{verifier}`
Unit verifier: `{verifier}`
Integration verifier: `{verifier}`
System verifier: `{verifier}`
Regression verifier: `{verifier}`
Benchmark verifier: `python3 -c "print('n/a')"`
""")
    with open(path, "w") as f:
        f.write("\n".join(blocks))


def run_loop_cmd(loop_bin: str, repo: str, args: list[str], timeout: int = 120):
    out, m = measure.run_subprocess([loop_bin] + args, cwd=repo, timeout=timeout)
    return out, m


def try_parse_json(text: str):
    return orient_mod.try_parse_json(text)


def read_json_file(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def operator_receipt_applied(run_dir: str, idx: int) -> bool:
    receipt = read_json_file(os.path.join(run_dir, f"operator-receipt-{idx}.json"))
    if not receipt:
        return False
    return receipt.get("execution_state") == "applied" or receipt.get("status") == "applied"


def record_versions(loop_bin: str, loop_src: str) -> dict:
    pip = os.path.join(os.path.dirname(loop_bin), "pip")
    pip_out = subprocess.run([pip, "list"], capture_output=True, text=True, timeout=30).stdout
    versions = {
        line.split()[0]: line.split()[1]
        for line in pip_out.splitlines()
        if line.lower().startswith("simplicio")
    }
    commit = subprocess.run(
        ["git", "-C", loop_src, "log", "-1", "--format=%H %s"],
        capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    return {"pip_versions": versions, "main_commit": commit}


def run_arm(*, arm: str, include_fast: bool, fixture_dir: str, repo_dir: str,
           loop_bin: str, python_bin: str, loop_src: str) -> dict:
    """``arm`` is ``simplicio-files`` or ``simplicio-fast``; ``include_fast``
    controls whether the orient JSON handed to the model keeps its ``fast``
    block (True) or has it stripped (False -- Mapper-only context)."""
    checker.seed_repo(fixture_dir, repo_dir)
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "-c", "user.email=bench@example.com", "-c", "user.name=bench",
         "commit", "-q", "-m", "seed fixture"],
        cwd=repo_dir, check=True,
    )

    results = {
        "arm": arm, "model": lc.MODEL, "tasks": [], "steps": [],
        "venv_versions": record_versions(loop_bin, loop_src),
        "harness_note": (
            "Both tasks run inside ONE simplicio-loop run (single `prepare`, "
            "one `tick` per task index) -- the Mapper/Fast run state is "
            "shared across tasks, matching the `cache` table below."
        ),
    }
    total_wall_t0 = time.time()
    generations = {"mapper_generation": None, "fast_generation": None}
    cache_records = []

    # Step 0: orient ONCE, cold, before `prepare` -- surveys the freshly
    # seeded repo before any run exists.
    cold_record, _cold_json = orient_mod.orient_call_record(
        loop_bin, repo_dir, "survey the repository before any task", "cadastro.html",
        generations, label="cold",
    )
    cache_records.append(cold_record)
    results["steps"].append({"step": "orient-cold", "metrics": cold_record["metrics"]})

    task_md_path = os.path.join(repo_dir, "tasks.md")
    write_task_md(task_md_path)
    prep_out, prep_metrics = run_loop_cmd(loop_bin, repo_dir, ["prepare", "--task", "tasks.md", "--repo", "."])
    prep_json = try_parse_json(prep_out)
    results["steps"].append({"step": "prepare", "metrics": prep_metrics, "result": prep_json})
    if not prep_json or "run_id" not in prep_json:
        results["fatal_error"] = "prepare_failed"
        results["prepare_output_tail"] = "\n".join(prep_out.splitlines()[-60:])
        results["total_wall_s"] = round(time.time() - total_wall_t0, 3)
        results["cache"] = cache_records
        return results
    run_id = prep_json["run_id"]
    run_dir = prep_json["run_dir"]
    results["run_id"] = run_id

    for task in bench_tasks.TASKS:
        idx = task["index"]
        stage = task["verify_stage"]
        task_record = {"task_index": idx, "kind": task["kind"], "task_text": task["text"], "attempts": []}
        success = False
        prior_error = None

        # Step 1: orient WARM, once per task (not re-run inside the retry
        # loop -- re-orienting mid-retry against a live run has historically
        # invalidated the Mapper generation `tick` pinned; one warm call per
        # task, reused across its attempts, is the safe, validated pattern).
        warm_record, warm_json = orient_mod.orient_call_record(
            loop_bin, repo_dir, task["text"], task["target"], generations,
            label=f"warm-task-{idx}",
        )
        cache_records.append(warm_record)
        results["steps"].append({"step": "orient-warm", "task_index": idx, "metrics": warm_record["metrics"]})

        orient_prompt_json = orient_mod.orient_json_for_prompt(warm_json, include_fast=include_fast)

        for attempt in range(1, 4):
            attempt_record = {"attempt": attempt}
            attempt_record["orient_bytes_sent"] = len(orient_prompt_json)

            if include_fast:
                # simplicio-fast: no separate raw file dump -- only whatever
                # content Mapper's own survey already embedded in orient's
                # `targets.files` (part of the JSON already sent above).
                context_text = ""
            else:
                # simplicio-files: the host explicitly reads the CURRENT
                # on-disk target file content (SKILL.md requires the host
                # read the target before writing find/replace text).
                target_path = os.path.join(repo_dir, task["target"])
                try:
                    with open(target_path, errors="replace") as f:
                        content = f.read()
                except FileNotFoundError:
                    content = "<FILE DOES NOT EXIST YET>"
                context_text = f"--- FILE: {task['target']} ---\n{content}\n--- END FILE: {task['target']} ---"
            attempt_record["context_files_bytes_sent"] = len(context_text)

            user_content = f"ORIENT CONTEXT (from simplicio-loop orient):\n{orient_prompt_json}\n\n"
            if context_text:
                user_content += f"CURRENT FILE CONTENTS (ground truth for `find`):\n{context_text}\n\n"
            user_content += f"TASK:\n{task['text']}\n\n"
            if prior_error:
                user_content += f"PREVIOUS ATTEMPT FAILED. Reason/details:\n{prior_error}\n\nFix the edit plan and try again.\n\n"
            user_content += "Reply with ONLY the JSON edit-plan object described in the system prompt."

            messages = [
                {"role": "system", "content": EDIT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]

            def do_call():
                return lc.chat(arm, messages, temperature=0)

            llm_result, call_metrics = measure.measure_call(do_call)
            attempt_record["llm_call"] = {
                "ok": llm_result.get("ok"),
                "latency_s": llm_result.get("latency_s"),
                "prompt_tokens": llm_result.get("prompt_tokens"),
                "completion_tokens": llm_result.get("completion_tokens"),
                "reasoning_tokens": llm_result.get("reasoning_tokens"),
                "cached_tokens": llm_result.get("cached_tokens"),
                "cost_usd": llm_result.get("cost_usd"),
                "finish_reason": llm_result.get("finish_reason"),
                "error": llm_result.get("error"),
                "step_wall_s": call_metrics["wall_s"],
                "step_cpu_s": call_metrics["cpu_s"],
                "step_peak_rss_mb": call_metrics["peak_rss_mb"],
            }

            if not llm_result.get("ok"):
                attempt_record["outcome"] = "llm_error"
                task_record["attempts"].append(attempt_record)
                prior_error = f"llm_error: {llm_result.get('error')}"
                continue

            content = llm_result.get("content") or ""
            try:
                plan = lc.extract_json(content)
                assert "operations" in plan and isinstance(plan["operations"], list)
            except Exception as e:
                attempt_record["outcome"] = "plan_parse_error"
                attempt_record["parse_error"] = str(e)
                task_record["attempts"].append(attempt_record)
                prior_error = f"plan_parse_error: {e}. Raw (truncated): {content[:500]}"
                continue

            plan_path = os.path.join(run_dir, f"edit-plan-{idx}.json")
            with open(plan_path, "w") as f:
                json.dump(plan, f)
            attempt_record["plan_path"] = plan_path
            attempt_record["operations_count"] = len(plan["operations"])

            tick_out, tick_metrics = run_loop_cmd(
                loop_bin, repo_dir, ["tick", run_id, "--repo", ".", "--task-index", str(idx)], timeout=120
            )
            attempt_record["tick_step"] = tick_metrics
            receipt_applied = operator_receipt_applied(run_dir, idx)
            attempt_record["operator_receipt_applied"] = receipt_applied

            # The harness's own independent confirmation (not the loop's
            # quality-matrix, which merges lane commands across the whole
            # multi-task run and keeps task 1's verifier -- see README.md).
            check_passed, check_out, check_metrics = checker.run_check(repo_dir, stage, python_bin)
            attempt_record["check_step"] = check_metrics
            attempt_record["check_output_tail"] = "\n".join(check_out.splitlines()[-30:])

            task_record["attempts"].append(attempt_record)

            if receipt_applied and check_passed:
                attempt_record["outcome"] = "success"
                success = True
                break
            attempt_record["outcome"] = "tick_failed_or_check_failed"
            attempt_record["tick_output_tail"] = "\n".join(tick_out.splitlines()[-60:])
            prior_error = (
                f"operator_receipt_applied={receipt_applied}, check_passed={check_passed}. "
                f"check output (tail): {attempt_record['check_output_tail']}"
            )

        task_record["success"] = success
        results["tasks"].append(task_record)
        print(f"[{arm}] task {idx} success={success} attempts={len(task_record['attempts'])}", file=sys.stderr)
        if not success:
            # Task 2 depends on task 1's tree; do not attempt it against a
            # broken base.
            break

    results["total_wall_s"] = round(time.time() - total_wall_t0, 3)
    results["cache"] = cache_records

    verify_out, verify_metrics = run_loop_cmd(loop_bin, repo_dir, ["verify", run_id, "--repo", "."], timeout=120)
    verify_json = try_parse_json(verify_out)
    results["steps"].append({"step": "verify", "metrics": verify_metrics, "result": verify_json})
    results["verify"] = verify_json
    results["quality_matrix"] = read_json_file(os.path.join(run_dir, "quality-matrix.json"))

    final_stage = bench_tasks.TASKS[-1]["verify_stage"]
    final_passed, final_out, _ = checker.run_check(repo_dir, final_stage, python_bin)
    results["final"] = {
        "check_passed": final_passed,
        "check_output_tail": "\n".join(final_out.splitlines()[-30:]),
    }
    return results
