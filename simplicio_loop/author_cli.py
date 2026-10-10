"""``simplicio-loop author``: run the author flow (``author_flow.run_author``) in a worktree and print the result as JSON.

Exit codes: 0 ok, 3 failed, 69 unsupported family, 2 usage error (bad flag, unreadable task file, ``--rounds`` outside 1 to 10).
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from pathlib import Path
from typing import Sequence

from .author_flow import AuthorResult, run_author

EXIT_STATUS = {"ok": 0, "failed": 3, "unsupported": 69}
EXIT_USAGE = 2


MAX_ROUNDS = 10


def _rounds(text: str) -> int:
    value = int(text)
    if not 1 <= value <= MAX_ROUNDS:
        raise argparse.ArgumentTypeError(f"must be from 1 to {MAX_ROUNDS}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simplicio-loop author",
        description="Open the LLM CLI with tools in a worktree, verify its edits and send failures back to the same session.")
    parser.add_argument("--repo", required=True, help="the worktree the CLI edits (use an isolated git worktree, not your main checkout)")
    parser.add_argument("--task-file", required=True, help="file with the task text")
    parser.add_argument("--verify", help="command run in the worktree after each round; its failure output is the next correction")
    parser.add_argument("--rounds", type=_rounds, default=3, help=f"author round plus corrections, at most this many (1 to {MAX_ROUNDS}, default 3)")
    parser.add_argument("--family", default="claude", help="CLI family (default claude; only claude is supported)")
    parser.add_argument("--allow-unsandboxed", action="store_true", help="run without bwrap (manual use only)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        task = Path(args.task_file).read_text(encoding="utf-8")
    except OSError as exc:
        print(json.dumps({"status": "error", "reason_code": "task_file_unreadable", "error": str(exc)}), file=sys.stderr)
        return EXIT_USAGE
    result: AuthorResult = asyncio.run(run_author(
        task, args.repo, family=args.family, verify=args.verify, rounds=args.rounds, allow_unsandboxed=args.allow_unsandboxed))
    print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, sort_keys=True))
    return EXIT_STATUS[result.status]
