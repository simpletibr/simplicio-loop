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
import shlex
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = REPO_ROOT / "bench" / "issue_eval" / "cases.json"
DEFAULT_REPO_SOURCE = "https://github.com/{repo}.git"
DEFAULT_TIMEOUT_S = 300.0
UNVERIFIED = "UNVERIFIED"


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
    engine_status: Optional[str] = None


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


class CaseFailure(Exception):
    """A case failed for a reportable reason (clone, checkout, engine output)."""


async def _run(cmd, cwd: str, timeout: float, shell: bool = False, env=None):
    """Run a command; return (returncode, stdout, stderr). Kills it on timeout."""
    if shell:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=cwd, env=env,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=cwd, env=env,
        )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return (
        proc.returncode,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )


async def run_case(
    case: dict,
    engine_cmd: str,
    semaphore: asyncio.Semaphore,
    repo_root: Path,
    dry_run: bool = False,
    repo_source: str = DEFAULT_REPO_SOURCE,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> CaseResult:
    """Run a single case: clone at base_commit, run engine, then verify.

    Success needs engine status == "ok" AND verify exit 0. repo_source is a
    git URL/path template; {repo} is replaced with the case's owner/name slug.
    """
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

        start = time.monotonic()
        work_dir = tempfile.mkdtemp(prefix=f"issue-{case['issue_number']}-")
        try:
            source = repo_source.replace("{repo}", case["repo"])
            rc, _, err = await _run(
                ["git", "clone", "--quiet", source, "."], work_dir, timeout
            )
            if rc != 0:
                raise CaseFailure(f"clone failed (exit {rc}): {err.strip()[:200]}")
            rc, _, err = await _run(
                ["git", "checkout", "--quiet", "--detach", case["base_commit"]],
                work_dir, timeout,
            )
            if rc != 0:
                raise CaseFailure(
                    f"checkout {case['base_commit']} failed (exit {rc}): {err.strip()[:200]}"
                )

            verify_cmd = case.get("verify_command") or ""
            cmd = (
                engine_cmd.replace("{repo}", shlex.quote(work_dir))
                .replace("{task}", shlex.quote(case["issue_title"]))
                .replace("{verify}", shlex.quote(verify_cmd))
            )

            env = os.environ.copy()
            env["SIMPLICIO_ISSUE_EVAL"] = "1"
            rc, output, err = await _run(cmd, work_dir, timeout, shell=True, env=env)
            result.engine_output = output

            engine = parse_engine_output(output)
            if engine is None:
                raise CaseFailure(
                    f"engine output has no simplicio.turbo-run/v1 JSON (exit {rc}): "
                    f"{err.strip()[:200]}"
                )
            result.engine_status = engine.get("status")
            result.tokens_in = engine.get("tokens_in")
            result.tokens_out = engine.get("tokens_out")
            if result.engine_status != "ok":
                raise CaseFailure(f"engine status {result.engine_status!r}, not 'ok'")

            if not verify_cmd:
                result.status = "unverified"
                result.verify_result = UNVERIFIED
                result.error = "no verify_command"
            else:
                rc, _, err = await _run(verify_cmd, work_dir, timeout, shell=True)
                if rc == 0:
                    result.status = "success"
                    result.verify_result = "pass"
                else:
                    result.status = "failed"
                    result.verify_result = "fail"
                    result.error = f"verify exit {rc}: {err.strip()[:200]}"
        except CaseFailure as e:
            result.status = "failed"
            result.error = str(e)
            result.verify_result = UNVERIFIED
        except asyncio.TimeoutError:
            result.status = "failed"
            result.error = f"timeout after {timeout}s"
            result.verify_result = UNVERIFIED
        except Exception as e:
            result.status = "failed"
            result.error = str(e)[:200]
            result.verify_result = UNVERIFIED
        finally:
            result.wall_time_s = time.monotonic() - start
            shutil.rmtree(work_dir, ignore_errors=True)

        return result


async def run_cases(
    cases: list,
    engine_cmd: str,
    repo_root: Path,
    concurrency: int = 4,
    limit: Optional[int] = None,
    dry_run: bool = False,
    repo_source: str = DEFAULT_REPO_SOURCE,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> list:
    """Run all cases concurrently, bounded by semaphore."""
    if limit:
        cases = cases[:limit]

    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        run_case(case, engine_cmd, semaphore, repo_root, dry_run, repo_source, timeout)
        for case in cases
    ]
    return await asyncio.gather(*tasks)


def _sum_reported(values) -> Optional[int]:
    """Sum of reported values; None when no case reported any (never invent 0)."""
    reported = [v for v in values if v is not None]
    return sum(reported) if reported else None


def build_execution_report(
    results: list,
    repo_root: Path,
) -> dict:
    """Build simplicio.execution-report/v1 from results."""
    total = len(results)
    all_tokens = bool(results) and all(
        r.tokens_in is not None and r.tokens_out is not None for r in results
    )
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
                "tokens_status": (
                    "MEASURED"
                    if r.tokens_in is not None and r.tokens_out is not None
                    else UNVERIFIED
                ),
                "engine_status": r.engine_status,
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
            "total_input_tokens": _sum_reported(r.tokens_in for r in results),
            "total_output_tokens": _sum_reported(r.tokens_out for r in results),
        },
        "measured_fields": ["wall_ms", "success"],
        "unverified_fields": [] if all_tokens else ["tokens_*"],
        "unavailable_reasons": (
            {}
            if all_tokens
            else {"tokens_*": "engine did not report tokens in simplicio.turbo-run/v1"}
        ),
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
        default=DEFAULT_CASES,
        help="Path to cases.json",
    )
    parser.add_argument(
        "--repo-source",
        default=DEFAULT_REPO_SOURCE,
        help="git URL/path template to clone from; {repo} = owner/name slug",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="Per-step timeout in seconds (clone, engine, verify)",
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
            repo_source=args.repo_source,
            timeout=args.timeout,
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
