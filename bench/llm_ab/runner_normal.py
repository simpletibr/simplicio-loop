"""ARM NORMAL: plain agent loop.

Per task: send the full file tree + full contents of every repo file (except
the harness-owned checker's own logic is never asked for) + the task text;
ask for JSON ``{"files": [{"path", "content"}]}``; write files; run the
harness-owned ``tests/check_cadastro.py --stage N``; on failure send the
failure output back and retry (max 3 attempts). One conversation per task so
provider prompt-caching can apply across retries. Task 2 runs on the tree
task 1 left (same repo, in order).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import checker  # noqa: E402
import llm_client as lc  # noqa: E402
import measure  # noqa: E402
import tasks as bench_tasks  # noqa: E402

IGNORE_DIRS = {".git", "__pycache__", ".pytest_cache"}

SYSTEM_PROMPT = (
    "You are a careful senior front-end engineer working directly on a small "
    "repository. You will be given the repository's full file tree and the "
    "full contents of every file, followed by one task. Some files contain "
    "only a 'SIMPLICIO-PLACEHOLDER' HTML comment marker; these are "
    "unimplemented placeholder files you must replace with real content as "
    "the task requires. Implement the task completely and correctly. Reply "
    "with ONLY a single JSON object of the exact shape "
    '{"files": [{"path": "relative/path", "content": "COMPLETE NEW FILE CONTENT"}]} '
    "listing the complete new content of every file you create or modify "
    "(not a diff, not partial). No markdown code fences, no prose outside the JSON."
)


def list_repo_files(repo: str) -> list[str]:
    files = []
    for root, dirs, fnames in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fn in fnames:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, repo)
            files.append(rel)
    return sorted(files)


def snapshot_text(repo: str) -> str:
    files = list_repo_files(repo)
    tree = "\n".join(files)
    parts = [f"FILE TREE:\n{tree}\n"]
    for rel in files:
        with open(os.path.join(repo, rel), "r", errors="replace") as f:
            content = f.read()
        parts.append(f"--- FILE: {rel} ---\n{content}\n--- END FILE: {rel} ---")
    return "\n\n".join(parts)


def write_files(repo: str, files: list[dict]) -> list[str]:
    written = []
    for entry in files:
        rel = entry["path"]
        content = entry["content"]
        full = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        written.append(rel)
    return written


def run_arm(fixture_dir: str, repo_dir: str, python_bin: str) -> dict:
    checker.seed_repo(fixture_dir, repo_dir)
    results = {"arm": "normal", "model": lc.MODEL, "tasks": []}
    import time

    total_wall_t0 = time.time()

    for task in bench_tasks.TASKS:
        idx = task["index"]
        stage = task["verify_stage"]
        task_record = {"task_index": idx, "kind": task["kind"], "task_text": task["text"], "attempts": []}
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        snap = snapshot_text(repo_dir)
        user_msg = f"{snap}\n\nTASK:\n{task['text']}\n\nReply with ONLY the JSON object described in the system prompt."
        messages.append({"role": "user", "content": user_msg})

        success = False
        for attempt in range(1, 4):
            attempt_record = {"attempt": attempt, "context_bytes_sent": len(user_msg)}

            def do_call():
                return lc.chat("normal", messages, temperature=0)

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
                break

            content = llm_result.get("content") or ""
            messages.append({"role": "assistant", "content": content})

            try:
                parsed = lc.extract_json(content)
                files = parsed["files"]
            except Exception as e:
                attempt_record["outcome"] = "parse_error"
                attempt_record["parse_error"] = str(e)
                task_record["attempts"].append(attempt_record)
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your reply could not be parsed as the required JSON: {e}. "
                        "Reply again with ONLY the JSON object, no prose, no fences."
                    ),
                })
                continue

            (written, write_metrics) = measure.measure_call(write_files, repo_dir, files)
            attempt_record["files_written"] = written
            attempt_record["write_step"] = write_metrics

            passed, check_out, check_metrics = checker.run_check(repo_dir, stage, python_bin)
            attempt_record["check_step"] = check_metrics
            attempt_record["check_output_tail"] = "\n".join(check_out.splitlines()[-30:])
            task_record["attempts"].append(attempt_record)

            if passed:
                attempt_record["outcome"] = "success"
                success = True
                break
            attempt_record["outcome"] = "check_failure"
            messages.append({
                "role": "user",
                "content": (
                    f"`{checker.verifier_line(stage)}` failed. Output (tail):\n"
                    f"{attempt_record['check_output_tail']}\n\n"
                    "Fix the issue. Reply again with ONLY the JSON object with the "
                    "complete new content of every file you create or modify."
                ),
            })

        task_record["success"] = success
        results["tasks"].append(task_record)
        print(f"[normal] task {idx} success={success} attempts={len(task_record['attempts'])}", file=sys.stderr)

    results["total_wall_s"] = round(time.time() - total_wall_t0, 3)
    final_passed, final_out, _ = checker.run_check(repo_dir, bench_tasks.TASKS[-1]["verify_stage"], python_bin)
    results["final"] = {
        "check_passed": final_passed,
        "check_output_tail": "\n".join(final_out.splitlines()[-30:]),
    }
    return results
