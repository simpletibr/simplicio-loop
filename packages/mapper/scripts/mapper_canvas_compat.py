#!/usr/bin/env python3
"""Offline mapper-to-Canvas compatibility harness.

The harness intentionally validates stable interchange semantics (schema,
stable IDs, node/edge integrity, and fixture coverage) rather than byte-for-
byte generated timestamps or mapper-version strings.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "simplicio_mapper" / "contracts" / "mapper-canvas" / "v1" / "fixtures"
MATRIX = ROOT / "simplicio_mapper" / "contracts" / "mapper-canvas" / "v1" / "compatibility-matrix.json"
FIXTURE_NAMES = tuple(item["name"] for item in json.loads(MATRIX.read_text(encoding="utf-8"))["fixtures"])


def _run_mapper(root: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "simplicio_mapper.cli", "visualize", str(root), "--json"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    output = root / ".simplicio" / "visualization-bundle.json"
    if not output.is_file():
        raise RuntimeError(f"mapper did not produce {output}")
    return json.loads(output.read_text(encoding="utf-8"))


def _normalize(bundle: dict[str, Any]) -> dict[str, Any]:
    """Drop run-local metadata while preserving IDs and graph semantics."""
    normalized = copy.deepcopy(bundle)

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items() if k not in {"generated_at", "mapper_version"}}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(normalized)


def _check_bundle(name: str, bundle: dict[str, Any], golden: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if bundle.get("schema") != "simplicio.visualization-bundle/v1":
        errors.append(f"{name}: unsupported visualization schema")
    nodes = bundle.get("nodes")
    edges = bundle.get("edges")
    if not isinstance(nodes, list) or not nodes:
        errors.append(f"{name}: nodes must be a non-empty array")
    if not isinstance(edges, list):
        errors.append(f"{name}: edges must be an array")
    node_ids = {node.get("id") for node in nodes or [] if isinstance(node, dict)}
    golden_ids = {node.get("id") for node in golden.get("nodes", []) if isinstance(node, dict)}
    if not golden_ids.issubset(node_ids):
        errors.append(f"{name}: generated bundle lost golden node IDs")
    for edge in edges or []:
        if not isinstance(edge, dict) or edge.get("source") not in node_ids or edge.get("target") not in node_ids:
            errors.append(f"{name}: edge references a missing node")
            break
    return errors


def check() -> int:
    errors: list[str] = []
    for name in FIXTURE_NAMES:
        source = FIXTURES / name / "source"
        golden = json.loads((FIXTURES / name / "golden" / "visualization-bundle.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix=f"mapper-canvas-{name}-") as temp:
            clone = Path(temp) / "source"
            shutil.copytree(source, clone)
            first = _normalize(_run_mapper(clone))
            errors.extend(_check_bundle(name, first, golden))
            second = _normalize(_run_mapper(clone))
            if first != second:
                errors.append(f"{name}: repeated offline mapping is not deterministic")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print(f"Mapper-to-Canvas compatibility passed for {len(FIXTURE_NAMES)} fixtures")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.parse_args()
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
