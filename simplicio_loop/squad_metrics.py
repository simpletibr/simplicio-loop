"""Squad metrics: escalation rate, dependency wait, measured-only.

A "measured" metric comes from actual event data; "UNVERIFIED" means the data was
missing (e.g., no steps recorded, ready_at was None, a dependency merge not observed).
UNVERIFIED fields are marked: their dict keys are present, their values are None,
and an explanation is recorded in the unverified dict.
"""

from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

MAX_FILE_BYTES = 8 * 1024 * 1024  # a report or summary bigger than this is skipped, never read whole
MAX_SECONDS = 10 ** 9  # a wait above ~31 years is not a measurement of one tick: UNVERIFIED, not a number in the percentiles
MAX_COUNT = 10 ** 9


def escalation_part(steps: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Escalation part: initial_role, final_role, escalations list, proof_kind, unverified.

    steps: list of {"role": str, "outcome": str, "reason"?: str, ...} in attempt order.
    When same role is repeated, it is NOT an escalation.
    When a step fails but has no reason, the reason in the escalation is "UNVERIFIED|reason_not_recorded".
    Empty or None steps -> UNVERIFIED with None fields.
    """
    if not steps:
        return {
            "initial_role": None,
            "final_role": None,
            "escalations": None,
            "proof_kind": {"escalations": "UNVERIFIED"},
            "unverified": {"escalations": "no_steps_recorded"},
        }

    initial_role = steps[0]["role"]
    final_role = steps[-1]["role"]
    escalations = []

    for i in range(1, len(steps)):
        prev_role = steps[i - 1]["role"]
        curr_role = steps[i]["role"]
        if curr_role != prev_role:
            # There is a role change: escalation
            reason = steps[i - 1].get("reason")
            if not reason:
                reason = "UNVERIFIED|reason_not_recorded"
            escalations.append({
                "from": prev_role,
                "to": curr_role,
                "reason": reason,
                "attempt": i + 1,  # 1-indexed attempt
            })

    return {
        "initial_role": initial_role,
        "final_role": final_role,
        "escalations": escalations,
        "proof_kind": {"escalations": "measured"},
        "unverified": {},
    }


def dependency_part(
    depends_on: Iterable[int],
    ready_at: Optional[float],
    merged_at: Mapping[int, float],
) -> dict[str, Any]:
    """Dependency part: dependency_wait_s, depends_on (sorted), proof_kind, unverified.

    depends_on: iterable of issue numbers that this task depends on.
    ready_at: monotonic timestamp when the task's PR became ready to merge.
    merged_at: mapping from issue number to merge timestamp.

    Rules (in order):
    1. No deps -> wait 0.0, measured.
    2. ready_at is None -> wait None, UNVERIFIED "task_never_ready".
    3. Any dep missing from merged_at -> wait None, UNVERIFIED "dependency_merge_not_observed: #1,#3" (sorted).
    4. Else wait = max(merged_at[d] for d in deps) - ready_at, rounded to 3 places, floored at 0.0, measured.
    """
    depends_on_list = sorted(list(depends_on))

    if not depends_on_list:
        return {
            "dependency_wait_s": 0.0,
            "depends_on": [],
            "proof_kind": {"dependency_wait": "measured"},
            "unverified": {},
        }

    if ready_at is None:
        return {
            "dependency_wait_s": None,
            "depends_on": depends_on_list,
            "proof_kind": {"dependency_wait": "UNVERIFIED"},
            "unverified": {"dependency_wait_s": "task_never_ready"},
        }

    # Check all deps are in merged_at
    missing = [d for d in depends_on_list if d not in merged_at]
    if missing:
        reason = "dependency_merge_not_observed: " + ",".join(f"#{d}" for d in missing)
        return {
            "dependency_wait_s": None,
            "depends_on": depends_on_list,
            "proof_kind": {"dependency_wait": "UNVERIFIED"},
            "unverified": {"dependency_wait_s": reason},
        }

    # Calculate wait: max merge time - ready_at, floored at 0
    max_merge = max(merged_at[d] for d in depends_on_list)
    wait = max_merge - ready_at
    wait = max(0.0, round(wait, 3))

    return {
        "dependency_wait_s": wait,
        "depends_on": depends_on_list,
        "proof_kind": {"dependency_wait": "measured"},
        "unverified": {},
    }


def task_record(
    steps: list[dict[str, Any]] | None,
    depends_on: Iterable[int],
    ready_at: Optional[float],
    merged_at: Mapping[int, float],
) -> dict[str, Any]:
    """Merge escalation and dependency parts into one record."""
    esc = escalation_part(steps)
    dep = dependency_part(depends_on, ready_at, merged_at)

    # Merge the two parts
    record = {
        "initial_role": esc["initial_role"],
        "final_role": esc["final_role"],
        "escalations": esc["escalations"],
        "depends_on": dep["depends_on"],
        "dependency_wait_s": dep["dependency_wait_s"],
        "proof_kind": {
            "escalations": esc["proof_kind"]["escalations"],
            "dependency_wait": dep["proof_kind"]["dependency_wait"],
        },
        "unverified": {**esc["unverified"], **dep["unverified"]},
    }
    return record


def unverified_record(reason: str) -> dict[str, Any]:
    """A record where nothing was measured (the recorder itself failed): both parts UNVERIFIED with the same reason."""
    return {
        "initial_role": None,
        "final_role": None,
        "escalations": None,
        "depends_on": [],
        "dependency_wait_s": None,
        "proof_kind": {"escalations": "UNVERIFIED", "dependency_wait": "UNVERIFIED"},
        "unverified": {"escalations": reason, "dependency_wait_s": reason},
    }


def collect(reports: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect tasks with a `squad_metrics` object from reports; anything else (no key, not an object) is ignored."""
    result = []
    for report in reports:
        tasks = report.get("tasks") if isinstance(report, dict) else None
        for task in tasks if isinstance(tasks, list) else []:
            if isinstance(task, dict) and isinstance(task.get("squad_metrics"), dict):
                record = {**task["squad_metrics"]}
                if "issue" in task:
                    record["issue"] = task["issue"]
                if "task_id" in task:
                    record["task_id"] = task["task_id"]
                result.append(record)
    return result


def percentile(sorted_values: list[float], q: float) -> Optional[float]:
    """NEAREST-RANK percentile: rank = ceil(q/100*n), value = sorted_values[rank-1].

    Empty list -> None.
    Always returns an observed value, never interpolated.
    """
    if not sorted_values:
        return None

    n = len(sorted_values)
    rank = math.ceil(q / 100.0 * n)
    if rank < 1:
        rank = 1
    if rank > n:
        rank = n

    return sorted_values[rank - 1]


def _proof(record: dict[str, Any], part: str) -> Any:
    proof = record.get("proof_kind")
    return proof.get(part) if isinstance(proof, dict) else None


def _measured_escalation(record: dict[str, Any]) -> bool:
    """Fail closed: measured only when it says so and the data has the shape the numbers are computed from."""
    escalations = record.get("escalations")
    return (_proof(record, "escalations") == "measured" and isinstance(record.get("initial_role"), str)
            and isinstance(record.get("final_role"), str) and isinstance(escalations, list)
            and all(isinstance(e, dict) and isinstance(e.get("from"), str) and isinstance(e.get("to"), str)
                    for e in escalations))


def _plausible(value: Any, upper: float) -> bool:
    """A real, finite number in [0, upper]; NaN, infinities, negatives, booleans and strings are not measurements."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= upper


def _measured_wait(record: dict[str, Any]) -> bool:
    return (_proof(record, "dependency_wait") == "measured" and isinstance(record.get("depends_on"), list)
            and _plausible(record.get("dependency_wait_s"), MAX_SECONDS))


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize task records. A record that is not measured, or not shaped as the numbers need, is UNVERIFIED and in no denominator.

    Measured records with empty depends_on are no_dependency_tasks (a measured 0, kept out of the percentile sample).
    """
    records = [r for r in records if isinstance(r, dict)]
    issues = {r["issue"] for r in records if isinstance(r.get("issue"), str) and r["issue"]}
    escalation_measured = [r for r in records if _measured_escalation(r)]
    waits_measured = [r for r in records if _measured_wait(r)]
    dependency_with_deps = [r for r in waits_measured if r["depends_on"]]
    no_dependency_tasks = len(waits_measured) - len(dependency_with_deps)

    escalation_n = len(escalation_measured)
    escalated = sum(1 for r in escalation_measured if r["escalations"])
    escalations_by_transition: dict[str, int] = {}
    by_initial_role: dict[str, dict[str, Any]] = {}
    for record in escalation_measured:
        for entry in record["escalations"]:
            key = f"{entry['from']}->{entry['to']}"
            escalations_by_transition[key] = escalations_by_transition.get(key, 0) + 1
        row = by_initial_role.setdefault(record["initial_role"], {"n": 0, "escalated": 0})
        row["n"] += 1
        row["escalated"] += 1 if record["escalations"] else 0
    for row in by_initial_role.values():
        row["escalation_rate"] = round(row["escalated"] / row["n"], 4)

    waits = sorted(r["dependency_wait_s"] for r in dependency_with_deps)
    return {
        "schema": "simplicio.squad-metrics/v1",
        "reports": None,
        "tasks": len(records),
        "issues": sorted(issues),
        "escalation_n": escalation_n,
        "escalation_unverified": len(records) - escalation_n,
        "escalated": escalated,
        "escalation_rate": round(escalated / escalation_n, 4) if escalation_n else None,
        "escalations_by_transition": dict(sorted(escalations_by_transition.items())),
        "by_initial_role": dict(sorted(by_initial_role.items())),
        "dependency_wait_n": len(waits),
        "no_dependency_tasks": no_dependency_tasks,
        "dependency_wait_unverified": len(records) - len(waits_measured),
        "dependency_wait_p50_s": percentile(waits, 50),
        "dependency_wait_p95_s": percentile(waits, 95),
        "dependency_wait_max_s": waits[-1] if waits else None,
    }


def summarize(reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Summarize reports: collect and summarize_records, add reports count."""
    reports_list = list(reports)
    records = collect(reports_list)
    summary = summarize_records(records)
    summary["reports"] = len(reports_list)
    return summary


def _short(value: Any) -> str:
    """A value echoed in a reason: bounded, whatever the file held."""
    text = str(value)
    return text if len(text) <= 80 else text[:77] + "..."


def _read_json(path: Path) -> Any:
    """Parse one JSON file. ValueError (short reason) for anything that is not a bounded regular file with valid JSON.

    The descriptor is opened non-blocking and checked with fstat, so a FIFO or a device never blocks or streams; at most
    MAX_FILE_BYTES + 1 bytes are ever read, so a file that grows after the check is capped too.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        raise ValueError(f"cannot open: {exc.strerror or type(exc).__name__}") from None
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("not a regular file")
        raw = handle.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"larger than {MAX_FILE_BYTES} bytes")
    try:
        return json.loads(raw.decode("utf-8"))
    except RecursionError:
        raise ValueError("JSON nested too deeply") from None
    except ValueError as exc:  # JSONDecodeError, UnicodeDecodeError, an integer with too many digits
        raise ValueError(_short(exc)) from None


def load_reports(paths: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Load execution-report/v1 files from paths (files or directories).

    Directories are searched recursively for *.json, excluding latest.json; a symlink found there is not followed.
    Duplicates by run_id are deduplicated. A file that cannot be used goes to `skipped` with a short reason; it never
    stops the others. Returns (reports sorted by run_id, skipped list).
    """
    all_reports: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen_run_ids: set[str] = set()

    def skip(path: Path, reason: str) -> None:
        skipped.append({"path": str(path), "reason": reason})

    for path_str in paths:
        path = Path(path_str)
        try:
            if path.is_dir():
                json_files = sorted(p for p in path.rglob("*.json") if p.name != "latest.json")
            elif path.exists():
                json_files = [path]
            else:
                json_files = []
        except OSError as exc:
            skip(path, f"cannot list: {exc.strerror or type(exc).__name__}")
            continue
        if not json_files and not path.is_dir():
            skip(path, "not a file or directory")

        for json_file in json_files:
            if json_file != path and json_file.is_symlink():
                skip(json_file, "symlink not followed")
                continue
            try:
                data = _read_json(json_file)
            except ValueError as exc:
                skip(json_file, str(exc))
                continue
            if not isinstance(data, dict) or data.get("schema") != "simplicio.execution-report/v1":
                skip(json_file, "wrong schema: " + _short(data.get("schema") if isinstance(data, dict) else type(data).__name__))
                continue
            run_id = data.get("run_id")
            if run_id is not None and not isinstance(run_id, str):
                skip(json_file, "run_id is not a string")
                continue
            if run_id:
                if run_id in seen_run_ids:
                    continue
                seen_run_ids.add(run_id)
            all_reports.append(data)

    all_reports.sort(key=lambda r: r.get("run_id") or "")
    return all_reports, skipped


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare two summaries.

    Returns dict with schema, rows (metric comparisons), and warnings.
    Warnings explain small n, different issue sets, and UNVERIFIED counts.
    """
    result = {
        "schema": "simplicio.squad-metrics-compare/v1",
        "rows": [],
        "warnings": [],
    }

    # Metrics to compare
    metrics = [
        ("escalation_rate", "escalation_n"),
        ("dependency_wait_p50_s", "dependency_wait_n"),
        ("dependency_wait_p95_s", "dependency_wait_n"),
        ("dependency_wait_max_s", "dependency_wait_n"),
    ]

    for metric, n_key in metrics:
        before_val = before.get(metric)
        after_val = after.get(metric)
        before_n = before.get(n_key, 0)
        after_n = after.get(n_key, 0)

        result["rows"].append({
            "metric": metric,
            "before": {"value": before_val, "n": before_n},
            "after": {"value": after_val, "n": after_n},
        })

    # Warnings
    before_esc_n = before.get("escalation_n", 0)
    after_esc_n = after.get("escalation_n", 0)
    before_dep_n = before.get("dependency_wait_n", 0)
    after_dep_n = after.get("dependency_wait_n", 0)

    if before_esc_n < 10:
        result["warnings"].append(
            f"before: n={before_esc_n} measured tasks for escalation rate (fewer than 10: do not read this as a trend)"
        )
    if after_esc_n < 10:
        result["warnings"].append(
            f"after: n={after_esc_n} measured tasks for escalation rate (fewer than 10: do not read this as a trend)"
        )

    if before_dep_n < 10:
        result["warnings"].append(
            f"before: n={before_dep_n} measured tasks for dependency wait (fewer than 10: do not read this as a trend)"
        )
    if after_dep_n < 10:
        result["warnings"].append(
            f"after: n={after_dep_n} measured tasks for dependency wait (fewer than 10: do not read this as a trend)"
        )

    before_issues = set(before.get("issues", []))
    after_issues = set(after.get("issues", []))
    if before_issues != after_issues:
        only_before = before_issues - after_issues
        only_after = after_issues - before_issues
        in_both = before_issues & after_issues
        result["warnings"].append(
            f"task sets differ: {len(only_before)} only in before, {len(only_after)} only in after, {len(in_both)} in both"
        )

    before_unv_esc = before.get("escalation_unverified", 0)
    after_unv_esc = after.get("escalation_unverified", 0)
    before_unv_dep = before.get("dependency_wait_unverified", 0)
    after_unv_dep = after.get("dependency_wait_unverified", 0)

    if before_unv_esc > 0 or after_unv_esc > 0 or before_unv_dep > 0 or after_unv_dep > 0:
        result["before_unverified"] = {
            "escalation": before_unv_esc,
            "dependency_wait": before_unv_dep,
        }
        result["after_unverified"] = {
            "escalation": after_unv_esc,
            "dependency_wait": after_unv_dep,
        }
        result["warnings"].append(
            f"before: {before_unv_esc + before_unv_dep} task(s) UNVERIFIED are excluded from the numbers"
        )
        result["warnings"].append(
            f"after: {after_unv_esc + after_unv_dep} task(s) UNVERIFIED are excluded from the numbers"
        )

    return result


def render_summary(summary: dict[str, Any]) -> str:
    """Render summary as plain-text table."""
    lines = []
    lines.append("Squad Metrics Summary")
    lines.append("=" * 50)
    lines.append(f"Reports: {summary.get('reports')}")
    lines.append(f"Tasks: {summary.get('tasks')}")
    lines.append(f"Issues: {', '.join(summary.get('issues', []))}")
    lines.append("")
    lines.append("Escalation:")
    lines.append(f"  Measured: {summary.get('escalation_n')}")
    lines.append(f"  Unverified: {summary.get('escalation_unverified')}")
    lines.append(f"  Escalated: {summary.get('escalated')}")
    rate = summary.get("escalation_rate")
    if rate is not None:
        lines.append(f"  Rate: {rate:.4f}")
    else:
        lines.append(f"  Rate: n/a")
    lines.append("")
    lines.append("Dependencies:")
    lines.append(f"  With deps (n): {summary.get('dependency_wait_n')}")
    lines.append(f"  Without deps: {summary.get('no_dependency_tasks')}")
    lines.append(f"  Unverified: {summary.get('dependency_wait_unverified')}")
    p50 = summary.get("dependency_wait_p50_s")
    p95 = summary.get("dependency_wait_p95_s")
    max_w = summary.get("dependency_wait_max_s")
    lines.append(f"  p50: {p50 if p50 is not None else 'n/a'}")
    lines.append(f"  p95: {p95 if p95 is not None else 'n/a'}")
    lines.append(f"  max: {max_w if max_w is not None else 'n/a'}")
    return "\n".join(lines)


def render_compare(result: dict[str, Any]) -> str:
    """Render compare result as plain-text table."""
    lines = []
    lines.append("Squad Metrics Comparison")
    lines.append("=" * 70)
    lines.append(f"{'Metric':<30} {'Before':<20} {'After':<20}")
    lines.append("-" * 70)

    for row in result.get("rows", []):
        metric = row.get("metric", "")
        before_val = row.get("before", {}).get("value")
        before_n = row.get("before", {}).get("n", 0)
        after_val = row.get("after", {}).get("value")
        after_n = row.get("after", {}).get("n", 0)

        before_str = f"{before_val:.4f} (n={before_n})" if before_val is not None else f"n/a (n={before_n})"
        after_str = f"{after_val:.4f} (n={after_n})" if after_val is not None else f"n/a (n={after_n})"

        lines.append(f"{metric:<30} {before_str:<20} {after_str:<20}")

    lines.append("")
    if result.get("warnings"):
        lines.append("Warnings:")
        for warning in result["warnings"]:
            lines.append(f"  WARNING: {warning}")

    return "\n".join(lines)


_SUMMARY_NUMBERS = (  # field -> upper bound; None is allowed (UNVERIFIED or no sample), anything else must be a plausible number
    ("escalation_rate", 1), ("dependency_wait_p50_s", MAX_SECONDS), ("dependency_wait_p95_s", MAX_SECONDS),
    ("dependency_wait_max_s", MAX_SECONDS))
_SUMMARY_COUNTS = ("escalation_n", "dependency_wait_n", "escalation_unverified", "dependency_wait_unverified")


def _check_summary(data: dict[str, Any], path: str) -> None:
    """A hand-edited summary: what `compare` reads must be None or a plausible number, a count or a list of strings."""
    for field, upper in _SUMMARY_NUMBERS:
        if data.get(field) is not None and not _plausible(data[field], upper):
            raise ValueError(f"{path}: {field} is not a plausible number: {_short(data[field])}")
    for field in _SUMMARY_COUNTS:
        value = data.get(field, 0)
        if not (isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_COUNT):
            raise ValueError(f"{path}: {field} is not a count: {_short(value)}")
    issues = data.get("issues", [])
    if not isinstance(issues, list) or not all(isinstance(i, str) for i in issues):
        raise ValueError(f"{path}: issues is not a list of strings")


def load_summary(path: str) -> dict[str, Any]:
    """Load a summary file (squad-metrics/v1 or execution-report/v1).

    If it is an execution-report/v1, summarize it.
    If it is a squad-metrics/v1, validate it and return it as-is.
    Otherwise, raise ValueError.
    """
    try:
        data = _read_json(Path(path))
    except ValueError as e:
        raise ValueError(f"Could not load {path}: {e}") from None

    if not isinstance(data, dict):
        raise ValueError(f"Unknown schema in {path}: not a JSON object")
    schema = data.get("schema")
    if schema == "simplicio.squad-metrics/v1":
        _check_summary(data, path)
        return data
    elif schema == "simplicio.execution-report/v1":
        return summarize([data])
    else:
        raise ValueError(f"Unknown schema {_short(schema)} in {path}")


def dispatch(args: Any) -> int:
    """CLI dispatch: --reports or --compare, with optional --json.

    Returns 0 on success, 2 on BLOCKED (error).
    Prints JSON or text output.
    """
    def emit_blocked(reason: str, skipped: Optional[list[dict[str, str]]] = None) -> int:
        output: dict[str, Any] = {
            "status": "BLOCKED",
            "error": "BlockedError",
            "reason": reason,
        }
        if skipped:
            output["skipped"] = skipped
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    # Check exclusivity: can't have both --reports and --compare
    if args.reports and args.compare:
        return emit_blocked("Cannot use --reports and --compare together")

    if args.compare:
        # Compare two summaries
        try:
            before = load_summary(args.compare[0])
            after = load_summary(args.compare[1])
            result = compare(before, after)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_compare(result))
            return 0
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError) as e:  # a hand-edited file: BLOCKED, not a traceback
            return emit_blocked(f"{type(e).__name__}: {e}")

    elif args.reports:
        # Load and summarize reports
        try:
            reports, skipped = load_reports(args.reports)
            if not reports:
                return emit_blocked(f"no execution-report/v1 found in {args.reports}", skipped)
            summary = summarize(reports)
            summary["skipped"] = skipped
            if args.json:
                print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(render_summary(summary))
            return 0
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError) as e:  # a hand-edited file: BLOCKED, not a traceback
            return emit_blocked(f"{type(e).__name__}: {e}")

    else:
        return emit_blocked("give --reports or --compare")
