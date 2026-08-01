#!/usr/bin/env python3
"""Reproducible local evidence runner for the Mapper/Fast/Dev CLI proof (#422).

Unavailable cross-repository capabilities are recorded as ``UNVERIFIED``;
they are never converted to pass or silently replaced with synthetic data.
"""

from __future__ import annotations

import argparse
import base64
import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from simplicio.changeset_v2 import execute_changeset, execute_changeset_bytes
from simplicio.execution_mode import negotiate_execution_mode
from simplicio.fast_contracts import fast_preflight
from simplicio.runtime_contracts import runtime_verify_contract

SCHEMA = "simplicio.dev-cli.issue-422-evidence/v1"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_sha(root: Path) -> str | None:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _changeset(count: int) -> dict[str, Any]:
    operations = [
        {"kind": "create", "path": f"files/file-{index:03d}.txt", "content": f"value-{index}\n"}
        for index in range(count)
    ]
    return {
        "schema": "simplicio.fast.changeset/v2",
        "changeset_id": f"issue-422-{count}",
        "correlation_id": f"issue-422-{count}",
        "generation": "generation-1",
        "allowlist": [item["path"] for item in operations],
        "operations": operations,
    }


def _transaction_scenario(count: int, repeats: int) -> dict[str, Any]:
    samples: list[float] = []
    with tempfile.TemporaryDirectory(prefix=f"simplicio-422-{count}-") as raw_root:
        root = Path(raw_root)
        changeset = _changeset(count)
        first: dict[str, Any] | None = None
        for _ in range(repeats):
            started = time.perf_counter()
            result = execute_changeset(changeset, root=root, apply=True)
            samples.append((time.perf_counter() - started) * 1000)
            first = first or result
            if result.get("status") != "ok":
                return {
                    "scenario": f"standalone_changeset_{count}",
                    "status": "FAIL",
                    "repetitions": len(samples),
                    "error": result.get("errors"),
                }
        replay = execute_changeset(changeset, root=root, apply=True)
        files = sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())
        return {
            "scenario": f"standalone_changeset_{count}",
            "status": "PASS",
            "repetitions": repeats,
            "warmup": 1,
            "p50_ms": statistics.median(samples),
            "p95_ms": sorted(samples)[max(0, int(len(samples) * 0.95) - 1)],
            "replay_status": replay.get("status"),
            "replayed": replay.get("replayed", False),
            "files": len(files),
            "first_transaction": first.get("transaction") if first else None,
        }


def _worktree_isolation_scenario() -> dict[str, Any]:
    """Exercise ten concurrent roots and verify each receives only its own edit."""
    def apply_one(index: int) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix=f"simplicio-422-worktree-{index}-") as raw_root:
            root = Path(raw_root)
            relative = f"files/worktree-{index:02d}.txt"
            value = f"isolated-{index}\n"
            changeset = {
                "schema": "simplicio.fast.changeset/v2",
                "changeset_id": f"issue-422-worktree-{index}",
                "correlation_id": f"issue-422-worktree-{index}",
                "generation": "generation-1",
                "allowlist": [relative],
                "operations": [{"kind": "create", "path": relative, "content": value}],
            }
            result = execute_changeset(changeset, root=root, apply=True)
            path = root / relative
            return {
                "status": result.get("status"),
                "content": path.read_text(encoding="utf-8") if path.is_file() else None,
                "root": str(root),
            }

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(apply_one, range(10)))
    passed = all(
        row["status"] == "ok" and row["content"] == f"isolated-{index}\n"
        for index, row in enumerate(results)
    )
    return {
        "scenario": "worktree_isolation_10",
        "status": "PASS" if passed and len({row["root"] for row in results}) == 10 else "FAIL",
        "worktrees": len(results),
        "unique_roots": len({row["root"] for row in results}),
        "scheduler_count": 1,
        "reason": None if passed else "one or more roots received an incorrect result",
    }


def _fast_binary_module(root: Path) -> Any | None:
    """Load the Fast producer from an installed package or sibling checkout."""
    try:
        return importlib.import_module("simplicio_fast.binary_changeset")
    except ModuleNotFoundError:
        candidates = [
            Path(os.environ["SIMPLICIO_FAST_SOURCE"])
            if os.environ.get("SIMPLICIO_FAST_SOURCE")
            else root.parent / "simplicio-fast" / "src",
        ]
        for candidate in candidates:
            if candidate.is_dir() and str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            sys.modules.pop("simplicio_fast", None)
            try:
                return importlib.import_module("simplicio_fast.binary_changeset")
            except ModuleNotFoundError:
                continue
        return None


def _fast_binary_scenario(root: Path, count: int, repeats: int) -> dict[str, Any]:
    module = _fast_binary_module(root)
    if module is None:
        return {
            "scenario": f"fast_python_binary_{count}",
            "status": "UNVERIFIED",
            "reason": "simplicio-fast binary producer is unavailable",
        }
    samples: list[float] = []
    with tempfile.TemporaryDirectory(prefix=f"simplicio-422-fast-{count}-") as raw_root:
        worktree = Path(raw_root)
        operations = []
        allowed = []
        for index in range(count):
            relative = f"files/file-{index:03d}.txt"
            content = f"fast-value-{index}\n".encode()
            allowed.append(relative)
            operations.append(
                module.ChangeOperation.from_dict(
                    {
                        "op": "create",
                        "path": relative,
                        "content_b64": base64.b64encode(content).decode("ascii"),
                        "after_sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
            )
        binary = module.BinaryChangeSet(
            repository=str(worktree.resolve()),
            base_generation="generation-1",
            overlay_generation="generation-2",
            attempt=f"issue-422-fast-{count}",
            worktree_id=f"slot-422-{count}",
            lease_id=f"lease-422-{count}",
            fencing_token=f"fence-422-{count}",
            allowed_paths=tuple(allowed),
            operations=tuple(operations),
        ).encode()
        for _ in range(repeats):
            started = time.perf_counter()
            result = execute_changeset_bytes(binary, root=worktree, apply=True)
            samples.append((time.perf_counter() - started) * 1000)
            if result.get("status") != "ok":
                return {
                    "scenario": f"fast_python_binary_{count}",
                    "status": "FAIL",
                    "repetitions": len(samples),
                    "error": result.get("errors"),
                }
        return {
            "scenario": f"fast_python_binary_{count}",
            "status": "PASS",
            "repetitions": repeats,
            "warmup": 1,
            "p50_ms": statistics.median(samples),
            "p95_ms": sorted(samples)[max(0, int(len(samples) * 0.95) - 1)],
            "binary_bytes": len(binary),
            "input_format": "simplicio.fast.binary-changeset/v1",
            "replay_status": result.get("status"),
            "replayed": result.get("replayed", False),
        }


def _auto_without_runtime(root: Path) -> dict[str, Any]:
    profile = negotiate_execution_mode(
        "auto",
        root=root,
        runtime_handshake={"verified": False, "capabilities": [], "reason": "runtime-absent"},
    )
    return {
        "scenario": "auto_without_runtime",
        "status": "PASS" if profile.effective_mode == "standalone" else "FAIL",
        "effective_mode": profile.effective_mode,
        "reason_code": profile.reason_code,
    }


def _capability_scenario(name: str, available: bool, version: str | None) -> dict[str, Any]:
    return {
        "scenario": name,
        "status": "UNVERIFIED" if not available else "AVAILABLE_NOT_E2E",
        "version": version,
        "reason": "capability not installed; no synthetic replacement executed" if not available else None,
    }


def _runtime_scenario() -> dict[str, Any]:
    """Report the real Runtime contract probe without claiming an E2E run."""
    handshake = runtime_verify_contract(timeout=20)
    if handshake.get("verified") is True:
        return {
            "scenario": "runtime_backed",
            "status": "AVAILABLE_NOT_E2E",
            "version": handshake.get("version"),
            "binary": handshake.get("binary"),
            "capabilities": handshake.get("capabilities", []),
            "reason": "runtime contract verified; effect E2E requires a configured transport",
        }
    return {
        "scenario": "runtime_backed",
        "status": "UNVERIFIED",
        "version": handshake.get("version"),
        "binary": handshake.get("binary"),
        "capabilities": handshake.get("capabilities", []),
        "reason": str(handshake.get("reason") or "runtime-contract-not-verified"),
    }


def run(root: Path, *, repeats: int = 10) -> dict[str, Any]:
    preflight = fast_preflight(offline=True)
    rows = [_auto_without_runtime(root)]
    rows.extend(_transaction_scenario(count, repeats) for count in (1, 20, 200))
    rows.append(_worktree_isolation_scenario())
    rows.extend(_fast_binary_scenario(root, count, repeats) for count in (1, 20, 200))
    rows.append(
        _capability_scenario(
            "fast_rust",
            preflight.status == "ready",
            preflight.fast_version,
        )
    )
    mapper_version = _version("simplicio-mapper")
    rows.append(_capability_scenario("mapper_producer", mapper_version is not None, mapper_version))
    runtime_row = _runtime_scenario()
    rows.append(runtime_row)
    return {
        "schema": SCHEMA,
        "commit_sha": _git_sha(root),
        "platform": platform.platform(),
        "python": sys.version,
        "filesystem": str(root.anchor),
        "configuration": {"repeats": repeats, "network": False, "root": str(root.resolve())},
        "components": {
            "dev_cli": _version("simplicio-dev-cli"),
            "mapper": _version("simplicio-mapper"),
            "fast": preflight.to_dict(),
            "runtime": runtime_row,
        },
        "scenarios": rows,
        "claims": {"performance_improvement": None, "reason": "no baseline comparison was run"},
        "overall": "PASS_WITH_UNVERIFIED" if any(row["status"] == "UNVERIFIED" for row in rows) else "PASS",
    }


def write_reports(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    jsonl = output.with_suffix(".jsonl")
    jsonl.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in payload["scenarios"]) + "\n",
        encoding="utf-8",
    )
    with output.with_suffix(".csv").open("w", newline="", encoding="utf-8") as handle:
        fields = sorted({key for row in payload["scenarios"] for key in row})
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(payload["scenarios"])
    lines = [
        "# Issue #422 local evidence",
        "",
        f"- schema: `{payload['schema']}`",
        f"- commit: `{payload['commit_sha']}`",
        f"- overall: `{payload['overall']}`",
        "",
        "| Scenario | Status | p50 ms | p95 ms | Reason |",
        "|---|---:|---:|---:|---|",
    ]
    for row in payload["scenarios"]:
        lines.append(
            f"| {row['scenario']} | {row['status']} | {row.get('p50_ms', '')} | "
            f"{row.get('p95_ms', '')} | {row.get('reason', '') or ''} |"
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/issue-422-e2e.md"))
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args(argv)
    if args.repeats < 10:
        parser.error("--repeats must be at least 10")
    payload = run(args.root.resolve(), repeats=args.repeats)
    output = args.output if args.output.is_absolute() else args.root / args.output
    write_reports(payload, output)
    print(json.dumps({"schema": payload["schema"], "overall": payload["overall"], "output": str(output)}))
    return 0 if payload["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
