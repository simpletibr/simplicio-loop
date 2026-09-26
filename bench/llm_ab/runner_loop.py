"""Driver for the `simplicio` arm, the SKILL.md wave flow: orient (once)
-> prepare (both tasks, ONE run) -> LLM writes EVERY edit plan up front
(plan N+1 against the content plan N leaves) -> ONE `wave` -> verify.

Per SKILL.md, the host (this script, driven by the benchmarked LLM) decides
each change as an exact find/replace edit plan; simplicio-dev-cli /
simplicio-loop freeze, apply and verify it. The loop itself never calls a
provider to write code.

Both tasks run inside ONE `prepare`d run and ONE `wave`: the wave freezes
each plan right before applying it, so task 2 binds to the tree task 1 left.
The prompt carries the orient JSON (Mapper + Fast) plus the target file as
the host reads it, which is what SKILL.md prescribes. Mapper/Fast state is
shared across both tasks; the cache table records the cold orient and one
warm orient before the wave.
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


def simulate_plan(files: dict, plan: dict) -> dict:
    """Apply a find/replace plan to an in-memory {path: content} map.

    The host knows what its own plan will leave on disk, so plan N+1 can be
    written against that content before the wave runs. A `find` that is
    missing or not unique raises ValueError (dev-cli would reject it too)."""
    out = dict(files)
    for op in plan.get("operations") or []:
        path, find = op.get("path", ""), op.get("find", "")
        current = out.get(path, "")
        if current.count(find) != 1:
            raise ValueError(f"find text must match exactly once in {path}")
        out[path] = current.replace(find, op.get("replace", ""), 1)
    return out


def _llm_plan(arm: str, orient_prompt_json: str, task: dict, content: str, prior_error):
    user_content = (
        f"ORIENT CONTEXT (from simplicio-loop orient, Mapper + Fast):\n{orient_prompt_json}\n\n"
        f"CURRENT FILE CONTENTS (ground truth for `find`):\n--- FILE: {task['target']} ---\n"
        f"{content}\n--- END FILE: {task['target']} ---\n\nTASK:\n{task['text']}\n\n"
    )
    if prior_error:
        user_content += f"PREVIOUS ATTEMPT FAILED. Reason/details:\n{prior_error}\n\nFix the edit plan.\n\n"
    user_content += "Reply with ONLY the JSON edit-plan object described in the system prompt."
    messages = [{"role": "system", "content": EDIT_SYSTEM_PROMPT}, {"role": "user", "content": user_content}]
    llm_result, call_metrics = measure.measure_call(lambda: lc.chat(arm, messages, temperature=0))
    record = {
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
    plan = None
    if llm_result.get("ok"):
        try:
            plan = lc.extract_json(llm_result.get("content") or "")
            assert isinstance(plan.get("operations"), list)
        except Exception as exc:  # noqa: BLE001 - recorded as the attempt's outcome
            record["parse_error"] = str(exc)
            plan = None
    return plan, record, len(orient_prompt_json), len(content)


def run_arm(*, arm: str, fixture_dir: str, repo_dir: str,
           loop_bin: str, python_bin: str, loop_src: str) -> dict:
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
            "SKILL.md wave flow: orient once, one `prepare` for both tasks, every "
            "edit plan written up front, ONE `wave` applies + verifies them."
        ),
    }
    t0 = time.time()
    generations = {"mapper_generation": None, "fast_generation": None}
    cache_records = []
    cold_record, _ = orient_mod.orient_call_record(
        loop_bin, repo_dir, "survey the repository before any task", "cadastro.html",
        generations, label="cold",
    )
    cache_records.append(cold_record)
    results["steps"].append({"step": "orient-cold", "metrics": cold_record["metrics"]})

    write_task_md(os.path.join(repo_dir, "tasks.md"))
    prep_out, prep_metrics = run_loop_cmd(loop_bin, repo_dir, ["prepare", "--task", "tasks.md", "--repo", "."])
    prep_json = try_parse_json(prep_out)
    results["steps"].append({"step": "prepare", "metrics": prep_metrics, "result": prep_json})
    if not prep_json or "run_id" not in prep_json:
        results["fatal_error"] = "prepare_failed"
        results["prepare_output_tail"] = "\n".join(prep_out.splitlines()[-60:])
        results["total_wall_s"] = round(time.time() - t0, 3)
        results["cache"] = cache_records
        return results
    run_id, run_dir = prep_json["run_id"], prep_json["run_dir"]
    results["run_id"] = run_id

    warm_record, warm_json = orient_mod.orient_call_record(
        loop_bin, repo_dir, " ".join(t["text"] for t in bench_tasks.TASKS), "cadastro.html",
        generations, label="warm-before-wave",
    )
    cache_records.append(warm_record)
    results["steps"].append({"step": "orient-warm", "metrics": warm_record["metrics"]})
    orient_prompt_json = orient_mod.orient_json_for_prompt(warm_json)

    task_records = {t["index"]: {"task_index": t["index"], "kind": t["kind"], "task_text": t["text"],
                                 "attempts": [], "success": False} for t in bench_tasks.TASKS}
    prior_errors: dict = {}
    for attempt in range(1, 4):
        pending = [t for t in bench_tasks.TASKS if not operator_receipt_applied(run_dir, t["index"])]
        if not pending:
            break
        files = {}
        for t in bench_tasks.TASKS:
            path = os.path.join(repo_dir, t["target"])
            if t["target"] not in files:
                with open(path, errors="replace") as fh:
                    files[t["target"]] = fh.read()
        wrote_all = True
        for t in pending:
            idx = t["index"]
            record = {"attempt": attempt}
            plan, llm_record, orient_bytes, file_bytes = _llm_plan(
                arm, orient_prompt_json, t, files[t["target"]], prior_errors.get(idx))
            record.update(llm_call=llm_record, orient_bytes_sent=orient_bytes, context_files_bytes_sent=file_bytes)
            task_records[idx]["attempts"].append(record)
            if plan is None:
                record["outcome"] = "plan_parse_error" if llm_record["ok"] else "llm_error"
                prior_errors[idx] = record["outcome"]
                wrote_all = False
                break
            try:
                files = simulate_plan(files, plan)
            except ValueError as exc:
                record["outcome"] = "plan_does_not_apply"
                prior_errors[idx] = str(exc)
                wrote_all = False
                break
            plan_path = os.path.join(run_dir, f"edit-plan-{idx}.json")
            with open(plan_path, "w") as fh:
                json.dump(plan, fh)
            record.update(plan_path=plan_path, operations_count=len(plan["operations"]))
        if not wrote_all:
            continue
        wave_out, wave_metrics = run_loop_cmd(loop_bin, repo_dir, ["wave", run_id, "--repo", "."], timeout=300)
        wave_json = try_parse_json(wave_out) or {}
        results["steps"].append({"step": "wave", "attempt": attempt, "metrics": wave_metrics,
                                 "status": wave_json.get("status"), "reason_code": wave_json.get("reason_code")})
        for t in pending:
            idx = t["index"]
            applied = operator_receipt_applied(run_dir, idx)
            check_passed, check_out, check_metrics = checker.run_check(repo_dir, t["verify_stage"], python_bin)
            record = task_records[idx]["attempts"][-1]
            record.update(wave_step=wave_metrics, wave_status=wave_json.get("status"),
                          operator_receipt_applied=applied, check_step=check_metrics,
                          check_output_tail="\n".join(check_out.splitlines()[-30:]))
            if applied and check_passed:
                record["outcome"] = "success"
                task_records[idx]["success"] = True
            else:
                record["outcome"] = "wave_failed_or_check_failed"
                record["wave_output_tail"] = "\n".join(wave_out.splitlines()[-60:])
                prior_errors[idx] = (f"operator_receipt_applied={applied}, check_passed={check_passed}. "
                                     f"wave status={wave_json.get('status')} reason={wave_json.get('reason_code')}")
        if all(r["success"] for r in task_records.values()):
            break
    for rec in task_records.values():
        results["tasks"].append(rec)
        print(f"[{arm}] task {rec['task_index']} success={rec['success']} attempts={len(rec['attempts'])}",
              file=sys.stderr)
    results["total_wall_s"] = round(time.time() - t0, 3)
    results["cache"] = cache_records
    verify_out, verify_metrics = run_loop_cmd(loop_bin, repo_dir, ["verify", run_id, "--repo", "."], timeout=120)
    verify_json = try_parse_json(verify_out)
    results["steps"].append({"step": "verify", "metrics": verify_metrics, "result": verify_json})
    results["verify"] = verify_json
    results["quality_matrix"] = read_json_file(os.path.join(run_dir, "quality-matrix.json"))
    final_passed, final_out, _ = checker.run_check(repo_dir, bench_tasks.TASKS[-1]["verify_stage"], python_bin)
    results["final"] = {"check_passed": final_passed, "check_output_tail": "\n".join(final_out.splitlines()[-30:])}
    return results
