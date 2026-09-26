"""Run-attributable savings reporting for the public ``simplicio`` command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _latest_run(repo: Path) -> Path | None:
    root = repo / ".simplicio-loop" / "loop-runs"
    runs = sorted(
        path for path in root.iterdir()
        if root.is_dir() and path.is_dir() and (path / "manifest.json").is_file()
    ) if root.is_dir() else []
    return runs[-1] if runs else None


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _report(repo: Path) -> dict[str, Any]:
    run_dir = _latest_run(repo.resolve())
    if run_dir is None:
        return {"status": "empty", "message": "no savings recorded yet"}

    records: list[dict[str, Any]] = []
    batch = run_dir / "operator-batch.jsonl"
    if batch.is_file():
        for line in batch.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(item, dict):
                records.append(item)

    input_tokens = output_tokens = reasoning_tokens = cost = 0
    measured = False
    cache_hits = 0
    for item in records:
        route = item.get("execution_route") or {}
        usage = route.get("token_usage") or {}
        values = [_number(usage.get("input_tokens")), _number(usage.get("output_tokens"))]
        if all(value is not None for value in values):
            measured = True
            input_tokens += int(values[0])
            output_tokens += int(values[1])
            reasoning = _number(usage.get("reasoning_tokens"))
            price = _number(usage.get("cost"))
            reasoning_tokens += int(reasoning or 0)
            cost += float(price or 0)
        if route.get("cache_hit") is True:
            cache_hits += 1

    run_id = run_dir.name
    if not measured:
        return {
            "status": "unmeasured",
            "run_id": run_id,
            "provider_backed": False,
            "input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "cache_hit": None,
            "cost": None,
            "message": "no provider-backed savings recorded; provider invocation was not measured",
        }
    return {
        "status": "measured",
        "run_id": run_id,
        "provider_backed": True,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cache_hit": cache_hits,
        "cost": cost,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio")
    sub = parser.add_subparsers(dest="command", required=True)
    savings = sub.add_parser("savings")
    savings_sub = savings.add_subparsers(dest="savings_command", required=True)
    report = savings_sub.add_parser("report")
    report.add_argument("--repo", type=Path, default=Path("."))
    report.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = _report(args.repo)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
