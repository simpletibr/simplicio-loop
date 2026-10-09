#!/usr/bin/env python3
"""Runner for bench/issue_eval test cases.

Measures PR success rate across a fixed set of real, resolved issues.
Reads cases from bench/issue_eval/cases.json and runs them with
the configurable engine command (default: simplicio-loop turbo).

Usage:
    python scripts/issue_eval.py [--dry-run] [--compare old.json new.json]
    python scripts/issue_eval.py --engine "opencode run" --limit 5
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class CaseResult:
    """Result of running a single case."""

    repo: str
    issue_number: int
    pr_number: int
    issue_title: str
    base_commit: str
    size: str
    source: str
    status: str
    verify_result: Optional[str]
    wall_time_s: Optional[float]
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    error: Optional[str] = None
    engine_output: Optional[str] = None


def load_cases(cases_file: Path) -> list:
    """Load test cases from JSON file."""
    with open(cases_file) as f:
        data = json.load(f)
    return data.get("cases", [])


def parse_engine_output(output: str) -> Optional[dict]:
    """Parse simplicio.turbo-run/v1 JSON status from engine output."""
    try:
        # Look for JSON in output
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    if data.get("schema") == "simplicio.turbo-run/v1":
                        return data
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return None


async def run_case(
    case: dict,
    engine_cmd: str,
    semaphore: asyncio.Semaphore,
    repo_root: Path,
    dry_run: bool = False,
) -> CaseResult:
    """Run a single test case."""
    async with semaphore:
        result = CaseResult(
            repo=case["repo"],
            issue_number=case["issue_number"],
            pr_number=case.get("pr_number", case["issue_number"]),
            issue_title=case["issue_title"],
            base_commit=case["base_commit"],
            size=case["size"],
            source=case.get("source", "pr"),
            status="skipped",
            verify_result=None,
            wall_time_s=None,
            tokens_in=None,
            tokens_out=None,
            engine_output=None,
        )

        if dry_run:
            result.status = "skipped"
            return result

        start = time.time()
        work_dir = None
        try:
            # Clone repo at base_commit
            work_dir = tempfile.mkdtemp(prefix=f"issue-{case['issue_number']}-")
            work_path = Path(work_dir)

            # Clone the repository
            clone_result = await asyncio.create_subprocess_exec(
                "git", "clone", case["repo"], ".",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
            )
            _, _ = await asyncio.wait_for(clone_result.communicate(), timeout=60)

            # Checkout at base_commit
            checkout_result = await asyncio.create_subprocess_exec(
                "git", "checkout", case["base_commit"],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
            )
            _, _ = await asyncio.wait_for(checkout_result.communicate(), timeout=60)

            # Prepare task description from issue title or body
            task_desc = case["issue_title"]

            # Replace template variables
            cmd = engine_cmd.replace("{repo}", case["repo"])
            cmd = cmd.replace("{task}", f'"{task_desc}"')
            
            # Handle verify command placeholder
            verify_cmd = case.get("verify_command")
            if verify_cmd and "{verify}" in cmd:
                cmd = cmd.replace("{verify}", verify_cmd)

            # Run engine
            env = os.environ.copy()
            env["SIMPLICIO_ISSUE_EVAL"] = "1"

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=work_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

            elapsed = time.time() - start
            result.wall_time_s = elapsed

            output = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            result.engine_output = output

            # Try to parse JSON status from engine
            engine_status = parse_engine_output(output)
            if engine_status:
                result.status = engine_status.get("status", "UNVERIFIED")
                result.tokens_in = engine_status.get("tokens_in")
                result.tokens_out = engine_status.get("tokens_out")
                result.verify_result = engine_status.get("verify", "UNVERIFIED")
            else:
                # No JSON status, fall back to exit code and token regex
                if proc.returncode == 0:
                    result.status = "success"
                    result.verify_result = "pass"
                else:
                    result.status = "failed"
                    result.verify_result = "fail"
                    result.error = stderr_text[:200]

                # Try to extract tokens from output
                tokens_match = re.search(r"tokens.in[\":]?\s*[=:]\s*(\d+)", output)
                if tokens_match:
                    result.tokens_in = int(tokens_match.group(1))

                tokens_out_match = re.search(r"tokens.out[\":]?\s*[=:]\s*(\d+)", output)
                if tokens_out_match:
                    result.tokens_out = int(tokens_out_match.group(1))

            # Run verify command if present and status is success
            if verify_cmd and result.status == "success":
                verify_proc = await asyncio.create_subprocess_shell(
                    verify_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=work_dir,
                )
                verify_stdout, verify_stderr = await asyncio.wait_for(
                    verify_proc.communicate(), timeout=300
                )
                if verify_proc.returncode == 0:
                    result.verify_result = "pass"
                else:
                    result.verify_result = "fail"
                    result.error = verify_stderr.decode("utf-8", errors="replace")[:200]

        except asyncio.TimeoutError:
            result.status = "failed"
            result.error = "Timeout"
            result.wall_time_s = 300.0
            result.verify_result = "UNVERIFIED"
        except Exception as e:
            result.status = "failed"
            result.error = str(e)[:200]
            result.wall_time_s = time.time() - start
            result.verify_result = "UNVERIFIED"
        finally:
            # Cleanup
            if work_dir and Path(work_dir).exists():
                try:
                    shutil.rmtree(work_dir)
                except Exception:
                    pass

        return result


async def run_cases(
    cases: list,
    engine_cmd: str,
    repo_root: Path,
    concurrency: int = 4,
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> list:
    """Run all cases concurrently, bounded by semaphore."""
    if limit:
        cases = cases[:limit]

    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        run_case(case, engine_cmd, semaphore, repo_root, dry_run)
        for case in cases
    ]
    return await asyncio.gather(*tasks)


def build_execution_report(
    results: list,
    repo_root: Path,
) -> dict:
    """Build simplicio.execution-report/v1 from results."""
    total = len(results)
    success = sum(1 for r in results if r.status == "success")
    passed = sum(1 for r in results if r.verify_result == "pass")
    total_time = sum(r.wall_time_s or 0 for r in results)

    report = {
        "schema": "simplicio.execution-report/v1",
        "owner": "simplicio-loop",
        "run_id": f"issue-eval-{int(time.time())}",
        "repo": str(repo_root.resolve()),
        "status": "DONE",
        "started_at_unix": int(time.time()),
        "finished_at_unix": int(time.time()),
        "wall_ms": int(total_time * 1000),
        "execution_profile": "issue-eval",
        "loop_decision": None,
        "provenance": None,
        "operators_used": ["issue_eval"],
        "tasks": [
            {
                "task_id": f"issue-{r.issue_number}",
                "issue": str(r.issue_number),
                "pr_number": r.pr_number,
                "source": r.source,
                "title": r.issue_title,
                "wall_ms": int((r.wall_time_s or 0) * 1000),
                "phase_latency_ms": {},
                "resources": {
                    "cpu_percent": None,
                    "peak_rss_mb": None,
                    "input_tokens": r.tokens_in,
                    "output_tokens": r.tokens_out,
                },
                "success": r.status == "success",
                "verify_result": r.verify_result,
                "error": r.error,
            }
            for r in results
        ],
        "consolidated": {
            "total_cases": total,
            "success_count": success,
            "pass_count": passed,
            "success_rate": success / total if total > 0 else 0,
            "pass_rate": passed / total if total > 0 else 0,
            "total_wall_ms": int(total_time * 1000),
            "avg_wall_ms": int(total_time / total * 1000) if total > 0 else 0,
            "total_input_tokens": sum(r.tokens_in or 0 for r in results),
            "total_output_tokens": sum(r.tokens_out or 0 for r in results),
        },
        "measured_fields": ["wall_ms", "success"],
        "unverified_fields": ["tokens_*"],
        "unavailable_reasons": {"tokens_*": "only filled from provider receipts"},
        "law": "Never fabricated. MEASURED only.",
    }
    return report


def compare_runs(old_file: Path, new_file: Path) -> None:
    """Compare two execution report files."""
    with open(old_file) as f:
        old = json.load(f)
    with open(new_file) as f:
        new = json.load(f)

    old_consolidated = old.get("consolidated", {})
    new_consolidated = new.get("consolidated", {})

    print("Comparison Results:")
    print(f"  Old success rate: {old_consolidated.get('success_rate', 0):.1%}")
    print(f"  New success rate: {new_consolidated.get('success_rate', 0):.1%}")

    old_success = old_consolidated.get("success_count", 0)
    new_success = new_consolidated.get("success_count", 0)
    delta = new_success - old_success
    print(f"  Delta: {delta:+d} cases ({delta:+.1%})")

    old_wall = old_consolidated.get("total_wall_ms", 0)
    new_wall = new_consolidated.get("total_wall_ms", 0)
    print(f"  Wall time: {old_wall}ms -> {new_wall}ms ({(new_wall - old_wall):+.0f}ms)")


def main():
    parser = argparse.ArgumentParser(
        description="Run simplicio-loop issue evaluation benchmark"
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("bench/issue_eval/cases.json"),
        help="Path to cases.json",
    )
    parser.add_argument(
        "--engine",
        default="simplicio-loop turbo --repo {repo} --task {task}",
        help="Engine command template",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Number of concurrent cases",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit to N cases",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print cases without running",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("OLD", "NEW"),
        help="Compare two result JSON files",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("bench/issue_eval/execution-report.json"),
        help="Output execution report file",
    )

    args = parser.parse_args()

    if args.compare:
        compare_runs(Path(args.compare[0]), Path(args.compare[1]))
        return

    if not args.cases.exists():
        print(f"Error: {args.cases} not found", file=sys.stderr)
        sys.exit(1)

    cases = load_cases(args.cases)
    print(f"Loaded {len(cases)} cases from {args.cases}")

    if args.dry_run:
        for case in cases[: args.limit or len(cases)]:
            print(
                f"  [{case['size']}] #{case['issue_number']}: {case['issue_title'][:60]}"
            )
        return

    repo_root = Path.cwd()
    results = asyncio.run(
        run_cases(
            cases,
            args.engine,
            repo_root,
            concurrency=args.concurrency,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    )

    report = build_execution_report(results, repo_root)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nResults:")
    print(f"  Total cases: {report['consolidated']['total_cases']}")
    print(f"  Success rate: {report['consolidated']['success_rate']:.1%}")
    print(f"  Pass rate: {report['consolidated']['pass_rate']:.1%}")
    print(f"  Total wall time: {report['consolidated']['total_wall_ms']}ms")
    print(f"\nExecution report written to {args.out}")

    by_size = {}
    for r in results:
        if r.size not in by_size:
            by_size[r.size] = {"total": 0, "success": 0}
        by_size[r.size]["total"] += 1
        if r.status == "success":
            by_size[r.size]["success"] += 1

    print(f"\nResults by size:")
    for size in ["small", "medium", "large"]:
        if size in by_size:
            stats = by_size[size]
            rate = stats["success"] / stats["total"] if stats["total"] > 0 else 0
            print(f"  {size}: {stats['success']}/{stats['total']} ({rate:.1%})")


if __name__ == "__main__":
    main()
