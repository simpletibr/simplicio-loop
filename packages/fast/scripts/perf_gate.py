"""Validate reproducible Fast benchmark receipts against a prior baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


RECEIPT_SCHEMA = "simplicio.fast.e2e-benchmark/v1"
ENVIRONMENT_SCHEMA = "simplicio.fast.environment/v1"
ENVIRONMENT_FIELDS = (
    "python",
    "python_implementation",
    "platform",
    "machine",
    "processor",
    "executable",
    "cpu_count",
)


def _valid_environment(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("schema") != ENVIRONMENT_SCHEMA:
        return False
    if any(field not in value for field in ENVIRONMENT_FIELDS):
        return False
    if any(
        not isinstance(value[field], (str, type(None)))
        for field in ENVIRONMENT_FIELDS[:-1]
    ):
        return False
    return value["cpu_count"] is None or (
        isinstance(value["cpu_count"], int)
        and not isinstance(value["cpu_count"], bool)
        and value["cpu_count"] > 0
    )


GATE_SCHEMA = "simplicio.fast.perf-gate/v1"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"receipt_unreadable:{path}:{error}") from error
    if not isinstance(value, dict) or value.get("schema") != RECEIPT_SCHEMA:
        raise ValueError(f"receipt_schema_mismatch:{path}")
    return value


def _number(value: Any, name: str) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _check_repetitions(receipt: dict[str, Any], minimum: int) -> dict[str, Any]:
    scenarios = receipt.get("scenarios")
    if not isinstance(scenarios, dict):
        return {"status": "fail", "reason": "scenarios_missing"}
    relevant = (
        "without_fast_alteration",
        "fast_python_alteration",
        "fast_python_alteration_refresh",
    )
    checks: dict[str, Any] = {}
    overall = "pass"
    for name in relevant:
        scenario = scenarios.get(name)
        if not isinstance(scenario, dict):
            checks[name] = {"status": "fail", "reason": "scenario_missing"}
            overall = "fail"
            continue
        repetitions = scenario.get("repetitions")
        if isinstance(repetitions, int) and repetitions >= minimum:
            checks[name] = {"status": "pass", "repetitions": repetitions}
        else:
            checks[name] = {
                "status": "fail",
                "reason": "minimum_repetitions_not_met",
                "repetitions": repetitions,
                "required": minimum,
            }
            overall = "fail"
    return {"status": overall, "checks": checks}


def _check_percentiles(receipt: dict[str, Any], minimum: int) -> dict[str, Any]:
    scenarios = receipt.get("scenarios")
    if not isinstance(scenarios, dict):
        return {"status": "fail", "reason": "scenarios_missing"}
    relevant = (
        "without_fast_alteration",
        "fast_python_alteration",
        "fast_python_alteration_refresh",
    )
    checks: dict[str, Any] = {}
    overall = "pass"
    for name in relevant:
        scenario = scenarios.get(name)
        wall = scenario.get("wall_ms") if isinstance(scenario, dict) else None
        samples = wall.get("samples") if isinstance(wall, dict) else None
        p50 = _number(wall.get("median"), "median") if isinstance(wall, dict) else None
        p95 = _number(wall.get("p95"), "p95") if isinstance(wall, dict) else None
        p99 = _number(wall.get("p99"), "p99") if isinstance(wall, dict) else None
        repetitions = (
            scenario.get("repetitions") if isinstance(scenario, dict) else None
        )
        valid = (
            isinstance(samples, list)
            and isinstance(repetitions, int)
            and len(samples) == repetitions
            and repetitions >= minimum
            and p50 is not None
            and p95 is not None
            and p99 is not None
            and p50 <= p95 <= p99
            and all(_number(value, "sample") is not None for value in samples)
        )
        checks[name] = {
            "status": "pass" if valid else "fail",
            "sample_count": len(samples) if isinstance(samples, list) else None,
            "repetitions": repetitions,
            "median": p50,
            "p95": p95,
            "p99": p99,
        }
        if not valid:
            overall = "fail"
    return {"status": overall, "checks": checks}


def _metric_check(
    name: str,
    baseline: float | None,
    candidate: float | None,
    *,
    max_regression_ratio: float,
    higher_is_better: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "metric": name,
        "baseline": baseline,
        "candidate": candidate,
    }
    if baseline is None or candidate is None:
        result.update({"status": "inconclusive", "reason": "metric_unavailable"})
        return result
    if higher_is_better:
        threshold = baseline * (1.0 - max_regression_ratio)
        passed = candidate >= threshold
        improved = candidate > baseline
    else:
        threshold = baseline * (1.0 + max_regression_ratio)
        passed = candidate <= threshold
        improved = candidate < baseline
    result.update(
        {
            "status": "pass" if passed else "fail",
            "threshold": threshold,
            "improved": improved,
        }
    )
    if not passed:
        result["reason"] = "regression_budget_exceeded"
    return result


def evaluate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    minimum_repetitions: int = 10,
    max_regression_ratio: float = 0.10,
) -> dict[str, Any]:
    baseline_environment = baseline.get("environment")
    candidate_environment = candidate.get("environment")
    if not _valid_environment(baseline_environment) or not _valid_environment(
        candidate_environment
    ):
        return {
            "schema": GATE_SCHEMA,
            "status": "inconclusive",
            "reason": "environment_invalid",
            "baseline": baseline_environment,
            "candidate": candidate_environment,
        }
    if baseline_environment != candidate_environment:
        return {
            "schema": GATE_SCHEMA,
            "status": "inconclusive",
            "reason": "environment_mismatch",
            "baseline": baseline_environment,
            "candidate": candidate_environment,
        }
    if baseline.get("workload") != candidate.get("workload"):
        return {
            "schema": GATE_SCHEMA,
            "status": "inconclusive",
            "reason": "workload_mismatch",
        }
    baseline_reps = _check_repetitions(baseline, minimum_repetitions)
    candidate_reps = _check_repetitions(candidate, minimum_repetitions)
    if baseline_reps["status"] == "fail" or candidate_reps["status"] == "fail":
        return {
            "schema": GATE_SCHEMA,
            "status": "inconclusive",
            "reason": "minimum_repetitions_not_met",
            "repetitions": {"baseline": baseline_reps, "candidate": candidate_reps},
        }
    baseline_percentiles = _check_percentiles(baseline, minimum_repetitions)
    candidate_percentiles = _check_percentiles(candidate, minimum_repetitions)
    if (
        baseline_percentiles["status"] == "fail"
        or candidate_percentiles["status"] == "fail"
    ):
        return {
            "schema": GATE_SCHEMA,
            "status": "inconclusive",
            "reason": "percentile_metrics_invalid",
            "percentiles": {
                "baseline": baseline_percentiles,
                "candidate": candidate_percentiles,
            },
        }
    base_totals = baseline.get("totals", {})
    cand_totals = candidate.get("totals", {})
    if not isinstance(base_totals, dict) or not isinstance(cand_totals, dict):
        return {
            "schema": GATE_SCHEMA,
            "status": "inconclusive",
            "reason": "totals_missing",
        }
    checks = [
        _metric_check(
            "fast_python_alteration_wall_ms",
            _number(
                base_totals.get("fast_python_alteration_wall_ms"),
                "fast_python_alteration_wall_ms",
            ),
            _number(
                cand_totals.get("fast_python_alteration_wall_ms"),
                "fast_python_alteration_wall_ms",
            ),
            max_regression_ratio=max_regression_ratio,
            higher_is_better=False,
        ),
        _metric_check(
            "alteration_speedup_hot",
            _number(
                base_totals.get("alteration_speedup_hot"), "alteration_speedup_hot"
            ),
            _number(
                cand_totals.get("alteration_speedup_hot"), "alteration_speedup_hot"
            ),
            max_regression_ratio=max_regression_ratio,
            higher_is_better=True,
        ),
        _metric_check(
            "estimated_token_savings_percent",
            _number(
                base_totals.get("estimated_token_savings_percent"),
                "estimated_token_savings_percent",
            ),
            _number(
                cand_totals.get("estimated_token_savings_percent"),
                "estimated_token_savings_percent",
            ),
            max_regression_ratio=max_regression_ratio,
            higher_is_better=True,
        ),
    ]
    blocked = []
    for name in ("full_standalone", "loop_standalone"):
        scenario = candidate.get("scenarios", {}).get(name, {})
        if isinstance(scenario, dict) and scenario.get("status") == "blocked":
            blocked.append({"scenario": name, "reason": scenario.get("reason")})
    if any(check["status"] == "fail" for check in checks):
        status = "regressed"
    elif any(check["status"] == "inconclusive" for check in checks) or blocked:
        status = "inconclusive"
    elif any(check.get("improved") for check in checks):
        status = "improved"
    else:
        status = "neutral"
    return {
        "schema": GATE_SCHEMA,
        "status": status,
        "baseline": baseline.get("environment"),
        "candidate": candidate.get("environment"),
        "workload": candidate.get("workload"),
        "minimum_repetitions": minimum_repetitions,
        "max_regression_ratio": max_regression_ratio,
        "repetitions": {"baseline": baseline_reps, "candidate": candidate_reps},
        "checks": checks,
        "blocked_scenarios": blocked,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--minimum-repetitions", type=int, default=10)
    parser.add_argument("--max-regression-ratio", type=float, default=0.10)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(
            _read(args.baseline),
            _read(args.candidate),
            minimum_repetitions=args.minimum_repetitions,
            max_regression_ratio=args.max_regression_ratio,
        )
    except ValueError as error:
        result = {"schema": GATE_SCHEMA, "status": "inconclusive", "reason": str(error)}
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return {"improved": 0, "neutral": 0, "regressed": 1, "inconclusive": 2}[
        result["status"]
    ]


if __name__ == "__main__":
    raise SystemExit(main())
