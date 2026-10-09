"""Ten-task comparison: simplicio turbo versus no skill.

``hermetic`` never opens a socket. ``--live`` is the only entry that reaches
OpenRouter, and it does so through ``bench.llm_ab.run`` (the OpenCode driver).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import tasks as bench_tasks  # noqa: E402
from report import run_prefix_cache_miss  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from simplicio_loop.turbo import survey_tasks  # noqa: E402


def recorded_prefix_calls(count: int, prefix_tokens: int = 256) -> list[dict]:
    """Usage a stable prefix produces: miss on call 0, hit after that.

    ``prefix_tokens`` must be at least the provider cache block (64). A
    shorter prefix cannot be claimed as a hit.
    """
    calls = []
    for index in range(count):
        cached = 0 if index == 0 or prefix_tokens < 64 else prefix_tokens
        calls.append({
            "ok": True,
            "turn": index + 1,
            "prompt_tokens": prefix_tokens + 32,
            "cached_tokens": cached,
            "completion_tokens": 8,
            "reasoning_tokens": 0,
        })
    return calls


def hermetic(root: Path, *, index=None) -> dict:
    """Both arms, 10 tasks, one Mapper survey, no network."""
    tasks = bench_tasks.task_set(10)
    survey = asyncio.run(survey_tasks(root, tasks, index=index))
    calls = recorded_prefix_calls(len(tasks) + 1)
    miss = run_prefix_cache_miss(calls)
    generations = {row["generation"] for row in survey["tasks"]}
    return {
        "schema": "simplicio.turbo10/v1",
        "live": False,
        "task_count": len(tasks),
        "arms": ["normal", "simplicio"],
        "tasks": [{"index": task["index"], "target": task["target"]} for task in tasks],
        "survey": survey,
        "survey_reused": len(generations) == 1 and all(
            row["reused"] for row in survey["tasks"][1:]
        ),
        "llm_calls": calls,
        "prefix_cache_miss": miss,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--out", default="")
    parser.add_argument("--root", default="")
    args = parser.parse_args(argv)
    if args.live:
        os.environ["SIMPLICIO_BENCH_TURBO"] = "1"
        from run import main as run_main
        return run_main([
            "--arms", "normal,simplicio",
            "--tasks", "10",
            "--turbo",
            "--out", args.out or os.path.join(HERE, "results"),
            "--skip-report",
        ])
    root = Path(args.root) if args.root else Path(os.getcwd())
    payload = hermetic(root)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if payload["prefix_cache_miss"] is None else 3


if __name__ == "__main__":
    raise SystemExit(main())
