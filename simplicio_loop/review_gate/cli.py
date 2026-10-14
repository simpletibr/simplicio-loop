"""`python -m simplicio_loop.review_gate`: run the automatic review of one PR on a clone and print the comment it would post.

Exit 0 when approved, 1 when not. The report JSON is written under `<repo>/.simplicio-loop/review-gate/`.
The issue and PR bodies come from `gh` unless `--issue-body-file` / `--pr-body-file` is given.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import comment, gate, identity


def _gh_body(kind: str, number: int | None, repo: str | None) -> str:
    if number is None:
        return ""
    argv = ["gh", kind, "view", str(number), "--json", "body"] + (["--repo", repo] if repo else [])
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        raise SystemExit(f"gh {kind} view {number} failed: {done.stderr.strip()[-200:]}")
    return json.loads(done.stdout).get("body") or ""


def _text(path: str | None, kind: str, number: int | None, repo: str | None) -> str:
    return Path(path).read_text(encoding="utf-8") if path else _gh_body(kind, number, repo)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m simplicio_loop.review_gate", description=__doc__)
    p.add_argument("--repo", type=Path, required=True, help="clone with the objects of base and head")
    p.add_argument("--gh-repo", help="owner/name for gh (default: the clone's)")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--issue", type=int)
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--issue-body-file")
    p.add_argument("--pr-body-file")
    p.add_argument("--author", default="unknown", help="agent id of the PR author")
    p.add_argument("--author-role", default="worker")
    p.add_argument("--author-model", default="unknown")
    p.add_argument("--host", default="local")
    p.add_argument("--mutants", type=int, default=gate.DEFAULT_MUTANTS)
    p.add_argument("--min-kill", type=float, default=gate.DEFAULT_MIN_KILL)
    p.add_argument("--json", action="store_true", help="print the report JSON instead of the comment")
    args = p.parse_args(argv)
    author = identity.Agent(args.author, args.author_role, args.author_model, args.host)
    inp = gate.GateInput(repo=args.repo.resolve(), pr=args.pr, issue=args.issue,
                         issue_body=_text(args.issue_body_file, "issue", args.issue, args.gh_repo),
                         pr_body=_text(args.pr_body_file, "pr", args.pr, args.gh_repo), base=args.base, head=args.head,
                         author=author, n_mutants=args.mutants, min_kill=args.min_kill)
    report = gate.run_gate(inp)
    commands = [f"git diff {args.base[:7]}...{args.head[:7]}", "pytest dos testes novos no head e em main (worktrees)",
                f"mutacao: amostra de {args.mutants} mutantes", "AST de uso", "ste-lint dos docs"]
    print(report.to_json() if args.json else comment.render(report, author, inp.reviewer, inp.independent, commands))
    return 0 if report.approved else 1


if __name__ == "__main__":
    sys.exit(main())
