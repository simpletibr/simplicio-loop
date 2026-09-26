#!/usr/bin/env python3
"""Print receipt-backed metrics for the native Loop qualification probes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_NAMES = (
    "qualification-run-fresh-GH102",
    "qualification-run-current-GH102",
    "qualification-batch-psutil-GH102",
    "qualification-batch-auto-GH102",
    "qualification-batch-auto-current",
    "qualification-batch-serial-current",
    "qualification-batch-wave10-current",
    "qualification-batch-wave30-current",
    "qualification-tick-current",
    "qualification-resume-psutil-GH102",
    "qualification-tasks-release-dry",
    "qualification-tasks-checkout-entrypoint-dry",
    "qualification-prism-arm",
    "qualification-single-task-fast-JIRA201",
    "qualification-hub-drain-plan-current",
    "qualification-hub-drain-admit-plan-as-checkpoint",
    "qualification-drain-evaluate-empty",
    "qualification-drain-persist-empty",
    "qualification-drain-load-empty",
    "qualification-queue-status-mapper",
    "qualification-queue-top-mapper",
    "qualification-queue-doctor-mapper",
    "qualification-queue-status-legacy",
    "qualification-queue-doctor-legacy",
)


def _json_line(path: Path) -> dict[str, object] | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\t", " ").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(".simplicio-loop/benchmark"))
    parser.add_argument("--name", action="append", dest="names", help="receipt directory name (repeatable)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for name in tuple(args.names or DEFAULT_NAMES):
        directory = args.root / name
        receipt_path = directory / "receipt.json"
        if not receipt_path.exists():
            continue
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        stdout_path = directory / str(receipt.get("stdout", "stdout.txt"))
        payload = _json_line(stdout_path) if stdout_path.exists() else None
        rows.append(
            {
                "name": name,
                "exit": receipt.get("exit_code"),
                "wall_s": round(float(receipt.get("wall_ns", 0)) / 1_000_000_000, 3),
                "cpu_s": round(float(receipt.get("reaped_children_cpu_seconds", 0)), 3),
                "cpu_lb_s": round(float(receipt.get("cpu_seconds_observed_lower_bound", 0)), 3),
                "rss_mib": round(float(receipt.get("peak_tree_rss_bytes_sampled", 0)) / 1048576, 1),
                "measurement_schema": receipt.get("schema"),
                "payload_schema": payload.get("schema") if payload else None,
                "status": payload.get("status") if payload else None,
                "reason_code": payload.get("reason_code") if payload else None,
                "reason": payload.get("reason") if payload else None,
                "verdict": payload.get("verdict") if payload else None,
                "provider_metrics": any(
                    key in receipt for key in ("input_tokens", "output_tokens", "reasoning_tokens", "cost_usd")
                ),
            }
        )

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    print("name\texit\twall_s\tcpu_s\tcpu_lb_s\trss_mib\tpayload_schema\tstatus\treason_code\treason\tverdict")
    for row in rows:
        print(
            "\t".join(
                _text(row[key])
                for key in (
                    "name",
                    "exit",
                    "wall_s",
                    "cpu_s",
                    "cpu_lb_s",
                    "rss_mib",
                    "payload_schema",
                    "status",
                    "reason_code",
                    "reason",
                    "verdict",
                )
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
