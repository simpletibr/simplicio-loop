#!/usr/bin/env python3
"""Run the reproducible structural A/B benchmark against a JSONL corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from simplicio_mapper.structural_benchmark import run_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure baseline vs structural context with a quality gate.")
    parser.add_argument("--input", required=True, help="JSONL corpus created from real captured runs")
    parser.add_argument("--output", required=True, help="JSON report path")
    parser.add_argument("--min-cases", type=int, default=30, help="minimum corpus size required for a publishable report")
    args = parser.parse_args()
    report = run_corpus(args.input)
    if report["case_count"] < args.min_cases:
        raise SystemExit(f"corpus has {report['case_count']} cases; {args.min_cases} required")
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"schema": report["schema"], "case_count": report["case_count"], "quality_gate": report["quality_gate"], "claim_99_percent_enabled": report["claim_99_percent_enabled"]}, sort_keys=True))
    return 0 if report["quality_gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
