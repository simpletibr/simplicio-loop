"""Enforce coverage on the issue #415 source-verification guards.

Usage::

    python3 -m pytest --cov=simplicio.plan_compiler.mapper_context \
        --cov=simplicio.pipeline_integrated tests/python/...
    python3 scripts/issue_415_coverage_gate.py --report .coverage

The repository-wide gate intentionally remains separate. This gate selects
the executable lines of the issue-specific guard functions, so unrelated
legacy branches in the large context adapter cannot hide a missing #415
regression test.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

import coverage

TARGETS = {
    "simplicio/plan_compiler/mapper_context.py": {
        "verify_context_sources",
        "_admit_mapper_delta",
    },
    "simplicio/pipeline_integrated.py": {"_causal_verification_paths"},
}


def _function_ranges(source: str, names: set[str]) -> dict[str, tuple[int, int]]:
    tree = ast.parse(source)
    ranges: dict[str, tuple[int, int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            if node.end_lineno is not None:
                ranges[node.name] = (node.lineno, node.end_lineno)
    return ranges


def measure(report: Path, *, root: Path | None = None, floor: float = 95.0) -> dict[str, Any]:
    root = (root or Path.cwd()).resolve()
    data = coverage.Coverage(data_file=str(report))
    data.load()
    results: dict[str, Any] = {}
    failed = False
    for relative, names in TARGETS.items():
        path = root / relative
        filename, statements, _excluded, missing, _formatted = data.analysis2(str(path))
        statement_lines = set(statements)
        missing_lines = set(missing)
        ranges = _function_ranges(path.read_text(encoding="utf-8"), names)
        for name in sorted(names):
            if name not in ranges:
                raise ValueError(f"function not found: {relative}:{name}")
            start, end = ranges[name]
            selected = {line for line in statement_lines if start <= line <= end}
            covered = selected - missing_lines
            percent = 100.0 if not selected else (100.0 * len(covered) / len(selected))
            key = f"{relative}:{name}"
            results[key] = {
                "statements": len(selected),
                "covered": len(covered),
                "missing": sorted(selected - covered),
                "percent": round(percent, 2),
                "pass": percent >= floor,
            }
            failed = failed or percent < floor
    return {
        "schema": "simplicio.dev-cli.issue-415-coverage/v1",
        "floor": floor,
        "guards": results,
        "pass": not failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path(".coverage"), help="coverage.py data file")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--floor", type=float, default=95.0)
    args = parser.parse_args()
    result = measure(args.report, root=args.root, floor=args.floor)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
