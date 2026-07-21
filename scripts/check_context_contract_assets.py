#!/usr/bin/env python3
"""Deterministic, stdlib-only integrity gate for ContextSnapshot contract assets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "contracts" / "context-snapshot" / "v1"
MANIFEST = ROOT / "contract-manifest.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest() -> dict:
    files = sorted(p for p in ROOT.rglob("*.json") if p != MANIFEST)
    return {
        "contract": "simplicio.mapper-context-conformance/v1",
        "owner": "wesleysimplicio/simplicio-mapper",
        "schema_ids": ["simplicio.context-snapshot/v1", "simplicio.context-graph/v1"],
        "compatibility": {
            "current": "v1",
            "accept": ["v1"],
            "future": "fail-closed",
            "n_minus_1": "v1 while v2 is introduced",
        },
        "limits": {
            "source_set": 4096,
            "nodes": 100000,
            "edges": 200000,
            "payload_bytes": 16777216,
            "depth": 64,
        },
        "files": {str(p.relative_to(ROOT)): _digest(p) for p in files},
    }


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _asset_errors() -> list[str]:
    errors: list[str] = []
    required = {"schema", "schema_version", "snapshot_id", "repository_id", "graph", "task"}
    for name in ("minimal", "full", "graph-multi-scale", "delta-revision"):
        payload = _load(ROOT / "fixtures" / "valid" / name / "context-snapshot.json")
        if payload.get("schema") != "simplicio.context-snapshot/v1" or required - payload.keys():
            errors.append(f"valid/{name} has an invalid snapshot envelope")
            continue
        graph = payload["graph"]
        if graph.get("schema") != "simplicio.context-graph/v1" or not isinstance(graph.get("counts"), dict):
            errors.append(f"valid/{name} has an invalid graph envelope")
        for node in graph.get("nodes", []):
            source = node.get("source", {}).get("file", "")
            if source.startswith("/") or ".." in source.split("/") or "\\" in source:
                errors.append(f"valid/{name} has a non-reversible source path")
    invalid = ROOT / "fixtures" / "invalid"
    if _load(invalid / "hash-mismatch" / "context-snapshot.json").get("snapshot_id") == _load(
        ROOT / "fixtures" / "valid" / "minimal" / "context-snapshot.json"
    ).get("snapshot_id"):
        errors.append("hash-mismatch does not alter snapshot_id")
    if "repository_id" in _load(invalid / "missing-required" / "context-snapshot.json"):
        errors.append("missing-required still has repository_id")
    if _load(invalid / "future-schema" / "context-snapshot.json").get("schema_version") != "v2":
        errors.append("future-schema is not v2")
    if ".." not in _load(invalid / "source-traversal" / "context-graph.json")["nodes"][0]["source"]["file"]:
        errors.append("traversal fixture lost traversal")
    if "unexpected" not in _load(invalid / "unknown-property" / "context-snapshot.json"):
        errors.append("unknown-property lacks unexpected field")
    if (
        _load(invalid / "dev-cli-incompatible" / "context-snapshot.json").get("producer")
        != "simplicio-dev-cli"
    ):
        errors.append("dev-cli fixture lost shadow producer")
    if "4096" not in _load(invalid / "oversized-representable.json").get("limit", ""):
        errors.append("oversized descriptor lost limit")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args()
    expected = build_manifest()
    encoded = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    if args.print:
        print(encoded, end="")
        return 0
    errors = _asset_errors()
    if not MANIFEST.is_file() or json.loads(MANIFEST.read_text()) != expected:
        errors.append("contract-manifest.json differs from deterministic golden output")
    for name in ("minimal", "full", "graph-multi-scale", "delta-revision"):
        if not (ROOT / "fixtures" / "valid" / name / "context-snapshot.json").is_file():
            errors.append(f"missing valid fixture {name}")
    if errors:
        print("context-contract-assets: FAIL")
        print("\n".join("- " + x for x in errors))
        return 1
    print("context-contract-assets: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
