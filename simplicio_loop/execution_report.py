"""simplicio.execution-report/v1 — mandatory super-detailed metrics (ADR 0010).

Same schema as Runtime `src/execution_report.rs`. Used when operators work alone
(operator-standalone) or when the loop package must write the report without the
Runtime binary. Never invent tokens/CPU/RAM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from . import model_roles

SCHEMA = "simplicio.execution-report/v1"
OWNER = "simplicio-loop"


def _unix() -> int:
    return int(time.time())


def _fp(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reports_dir(repo: Path) -> Path:
    d = repo / ".simplicio-loop" / "runtime" / "execution-reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sample_system_ram_mb() -> Optional[float]:
    env = os.environ.get("SIMPLICIO_MEASURED_SYSTEM_RAM_MB")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                parts = line.split()
                if len(parts) >= 2:
                    return float(parts[1]) / 1024.0
    return None


def new_report(
    repo: Path,
    *,
    execution_profile: str = "operator-standalone",
    loop_decision: Optional[dict[str, Any]] = None,
    provenance: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    run_id = f"run-{_unix()}-{_fp(str(repo))[:8]}"
    measured = ["run_id", "started_at_unix", "execution_profile"]
    if provenance:
        measured.append("provenance")
    unverified = ["cpu_percent", "tokens_*"]
    unavailable: dict[str, str] = {
        "cpu_percent": "continuous CPU sampler not wired this slice",
        "tokens_*": "tokens only filled from provider/usage receipts via record-task",
    }
    sys_ram = _sample_system_ram_mb()
    if sys_ram is not None:
        measured.append("system_ram_mb")
    else:
        unverified.append("system_ram_mb")
        unavailable["system_ram_mb"] = (
            "no MEASURED platform probe; set SIMPLICIO_MEASURED_SYSTEM_RAM_MB"
        )
    started = time.monotonic()
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "owner": OWNER,
        "run_id": run_id,
        "repo": str(repo.resolve()).replace("\\", "/"),
        "status": "OPEN",
        "started_at_unix": _unix(),
        "finished_at_unix": None,
        "wall_ms": 0,
        "execution_profile": execution_profile,
        "loop_decision": loop_decision,
        "provenance": dict(provenance or {}),
        "operators_used": [],
        "tasks": [],
        "consolidated": {},
        "measured_fields": measured,
        "unverified_fields": unverified,
        "unavailable_reasons": unavailable,
        "law": (
            "Every Loop/Runtime execution emits this report (ADR 0010 / ADR-2026-08-05). "
            "Tokens/CPU/RAM never fabricated."
        ),
        "_started_monotonic": started,
    }
    return report


def consolidate(report: dict[str, Any]) -> dict[str, Any]:
    tasks = report.get("tasks") or []
    tokens_in = 0
    tokens_out = 0
    tin_known = False
    tout_known = False
    cached_sum = cache_write_sum = 0
    cached_known = cache_write_known = False
    wall_sum = 0
    complete = fail = skip = other = 0
    peak_ram: Optional[float] = None
    issues: list[str] = []
    for t in tasks:
        if t.get("issue"):
            issues.append(str(t["issue"]))
        if t.get("wall_ms") is not None:
            wall_sum += int(t["wall_ms"])
        tok = t.get("tokens") or {}
        if tok.get("tokens_in") is not None:
            tokens_in += int(tok["tokens_in"])
            tin_known = True
        if tok.get("tokens_out") is not None:
            tokens_out += int(tok["tokens_out"])
            tout_known = True
        if tok.get("tokens_cached") is not None:
            cached_sum += int(tok["tokens_cached"])
            cached_known = True
        if tok.get("tokens_cache_write") is not None:
            cache_write_sum += int(tok["tokens_cache_write"])
            cache_write_known = True
        ram = (t.get("resources") or {}).get("ram_mb")
        if ram is not None:
            peak_ram = ram if peak_ram is None else max(peak_ram, float(ram))
        oc = str(t.get("outcome") or "")
        if oc in ("COMPLETE", "VERIFIED", "PASSED"):
            complete += 1
        elif oc in ("FAIL", "FAILED"):
            fail += 1
        elif oc in ("SKIP", "SKIPPED"):
            skip += 1
        else:
            other += 1
    started = report.get("_started_monotonic")
    wall_run = int((time.monotonic() - started) * 1000) if started else int(report.get("wall_ms") or 0)
    hours = wall_run / 3_600_000.0 if wall_run else 0.0
    speed = (len(tasks) / hours) if hours > 0 and tasks else None
    tasks_by_role: dict[str, int] = {}
    for t in tasks:
        role = (t.get("agent") or {}).get("role")
        if role:
            tasks_by_role[role] = tasks_by_role.get(role, 0) + 1
    return {
        "task_count": len(tasks),
        "tasks_by_role": dict(sorted(tasks_by_role.items())),
        "issues": issues,
        "outcomes": {
            "complete": complete,
            "fail": fail,
            "skip": skip,
            "other": other,
        },
        "wall_ms_run": wall_run,
        "wall_ms_tasks_sum": wall_sum,
        "speed_items_per_hour": speed,
        "tokens_in_sum": tokens_in if tin_known else None,
        "tokens_out_sum": tokens_out if tout_known else None,
        "tokens_total_sum": (tokens_in + tokens_out) if (tin_known or tout_known) else None,
        "tokens_cached_sum": cached_sum if cached_known else None,
        "tokens_cache_write_sum": cache_write_sum if cache_write_known else None,
        "tokens_rollup": (
            "complete"
            if (tin_known or tout_known)
            else "absent"
        ),
        "ram_mb_peak": peak_ram,
        "operators_used": list(report.get("operators_used") or []),
        "system_ram_mb": _sample_system_ram_mb(),
    }


def write_report(repo: Path, report: dict[str, Any]) -> Path:
    d = _reports_dir(repo)
    started = report.get("_started_monotonic")
    if started is not None:
        report["wall_ms"] = int((time.monotonic() - started) * 1000)
    report["consolidated"] = consolidate(report)
    public = {k: v for k, v in report.items() if not k.startswith("_")}
    body = json.dumps(public, indent=2, ensure_ascii=False) + "\n"
    path = d / f"{report['run_id']}.json"
    path.write_text(body, encoding="utf-8")
    (d / "latest.json").write_text(body, encoding="utf-8")
    index_line = json.dumps(
        {
            "run_id": report["run_id"],
            "status": report.get("status"),
            "wall_ms": report.get("wall_ms"),
            "task_count": len(report.get("tasks") or []),
            "path": str(path).replace("\\", "/"),
            "recorded_at_unix": _unix(),
        },
        ensure_ascii=False,
    )
    with (d / "index.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(index_line + "\n")
    return path


def load_latest(repo: Path) -> Optional[dict[str, Any]]:
    p = _reports_dir(repo) / "latest.json"
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    data["_started_monotonic"] = time.monotonic()  # approximate if reloaded
    return data


def record_task(
    report: dict[str, Any],
    *,
    task_id: str,
    title: str,
    issue: Optional[str] = None,
    wall_ms: Optional[int] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    cache_read: Optional[int] = None,
    cache_write: Optional[int] = None,
    outcome: str = "IN_PROGRESS",
    operators: Optional[list[str]] = None,
    agent: Optional[dict[str, str]] = None,
) -> None:
    operators = operators or []
    for name, value in (("cache_read", cache_read), ("cache_write", cache_write)):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("%s must be an integer >= 0, got %r" % (name, value))
        if tokens_in is None:
            raise ValueError("%s needs tokens_in, the new input count it belongs to" % name)
    if agent is not None:
        if agent.get("role") not in model_roles.ROLES:
            raise ValueError("agent role must be one of %s" % (model_roles.ROLES,))
        if agent.get("effort") not in model_roles.EFFORTS:
            raise ValueError("agent effort must be one of %s" % (model_roles.EFFORTS,))
        if not agent.get("model"):
            raise ValueError("agent model is required")
        agent = {"role": agent["role"], "model": agent["model"], "effort": agent["effort"]}
    for op in operators:
        if op not in report["operators_used"]:
            report["operators_used"].append(op)
    tok_source = "cli_measured" if (tokens_in is not None or tokens_out is not None) else "absent"
    if tokens_in is not None or tokens_out is not None:
        if "tokens_per_task" not in report["measured_fields"]:
            report["measured_fields"].append("tokens_per_task")
        report["unverified_fields"] = [f for f in report["unverified_fields"] if f != "tokens_*"]
    report["tasks"].append(
        {
            "task_id": task_id,
            "issue": issue,
            "title": title,
            "title_fingerprint": _fp(title)[:16],
            "wall_ms": wall_ms,
            "phase_latency_ms": {},
            "resources": {
                "cpu_percent": None,
                "ram_mb": None,
                "system_ram_mb": _sample_system_ram_mb(),
                "source": "unavailable" if _sample_system_ram_mb() is None else "platform_estimate",
            },
            "tokens": {
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tokens_cached": cache_read,
                "tokens_cache_write": cache_write,
                "tokens_reasoning": None,
                "tokens_total": (
                    (tokens_in or 0) + (tokens_out or 0)
                    if tokens_in is not None or tokens_out is not None
                    else None
                ),
                "source": tok_source,
            },
            "outcome": outcome,
            "operators_used": operators,
            "agent": agent,
            "notes": (
                ["UNVERIFIED|cpu_percent: sampler unavailable"]
                if True
                else []
            ),
        }
    )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="execution_report")
    p.add_argument("subcommand", choices=["start", "record-task", "finish", "show", "consolidate"])
    p.add_argument("--repo", default=".")
    p.add_argument("--json", action="store_true", default=True)
    p.add_argument("--profile", default="operator-standalone")
    p.add_argument("--task-id")
    p.add_argument("--issue")
    p.add_argument("--title")
    p.add_argument("--outcome", default="IN_PROGRESS")
    p.add_argument("--wall-ms", type=int)
    p.add_argument("--tokens-in", type=int)
    p.add_argument("--tokens-out", type=int)
    p.add_argument("--cache-read", type=int, help="cache read tokens of the task, measured (needs --tokens-in)")
    p.add_argument("--cache-write", type=int, help="cache write tokens of the task, measured (needs --tokens-in)")
    p.add_argument("--operator", action="append", default=[])
    p.add_argument("--role", choices=model_roles.ROLES, help="agent role (with --model and --effort)")
    p.add_argument("--model")
    p.add_argument("--effort", choices=model_roles.EFFORTS)
    p.add_argument("--status", default="COMPLETE")
    args = p.parse_args(argv)
    repo = Path(args.repo).resolve()

    if args.subcommand == "start":
        report = new_report(repo, execution_profile=args.profile)
        path = write_report(repo, report)
        print(json.dumps({k: v for k, v in report.items() if not k.startswith("_")}, indent=2))
        return 0

    if args.subcommand == "show":
        latest = load_latest(repo)
        if not latest:
            print(json.dumps({"schema": SCHEMA, "present": False}))
            return 0
        print(json.dumps({k: v for k, v in latest.items() if not k.startswith("_")}, indent=2))
        return 0

    if args.subcommand == "consolidate":
        latest = load_latest(repo)
        if not latest:
            print(json.dumps({"present": False}))
            return 1
        print(json.dumps(consolidate(latest), indent=2))
        return 0

    if args.subcommand == "record-task":
        if not args.task_id or not args.title:
            print("record-task requires --task-id and --title", flush=True)
            return 2
        agent_flags = (args.role, args.model, args.effort)
        if any(agent_flags) and not all(agent_flags):
            print("--role, --model and --effort go together", flush=True)
            return 2
        report = load_latest(repo) or new_report(repo, execution_profile=args.profile)
        record_task(
            report,
            task_id=args.task_id,
            title=args.title,
            issue=args.issue,
            wall_ms=args.wall_ms,
            tokens_in=args.tokens_in,
            tokens_out=args.tokens_out,
            cache_read=args.cache_read,
            cache_write=args.cache_write,
            outcome=args.outcome,
            operators=args.operator,
            agent={"role": args.role, "model": args.model, "effort": args.effort} if args.role else None,
        )
        write_report(repo, report)
        print(json.dumps({k: v for k, v in report.items() if not k.startswith("_")}, indent=2))
        return 0

    if args.subcommand == "finish":
        report = load_latest(repo)
        if not report:
            print("no open report", flush=True)
            return 1
        report["status"] = args.status
        report["finished_at_unix"] = _unix()
        if "finished_at_unix" not in report["measured_fields"]:
            report["measured_fields"].append("finished_at_unix")
        write_report(repo, report)
        print(json.dumps({k: v for k, v in report.items() if not k.startswith("_")}, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
