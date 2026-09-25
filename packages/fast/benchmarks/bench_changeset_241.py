"""Measured binary changeset transport benchmark for issue #241."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import platform
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from simplicio_fast.binary_changeset import (
    BinaryChangeJournal,
    DevCliAdapter,
    decode_binary,
    prepare_from_json,
)


SCHEMA = "simplicio.fast.changeset-benchmark/v1"


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _rss_kib() -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    try:
        return int(psutil.Process(os.getpid()).memory_info().rss // 1024)
    except (OSError, psutil.Error):
        return None


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    walls = [float(row["wall_ms"]) for row in rows]
    return {
        "repetitions": len(rows),
        "wall_ms_median": statistics.median(walls),
        "wall_ms_p95": _percentile(walls, 0.95),
        "wall_ms_p99": _percentile(walls, 0.99),
        "cpu_ms_median": statistics.median(float(row["cpu_ms"]) for row in rows),
        "bytes_median": statistics.median(int(row["bytes"]) for row in rows),
        "raw": rows,
    }


def run(*, repetitions: int = 30) -> dict[str, Any]:
    if repetitions < 10:
        raise ValueError("issue 241 benchmark requires at least 10 repetitions")
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-241-") as directory:
        root = Path(directory)
        content = b"def materialized():\n    return True\n"
        payload = {
            "operations": [
                {
                    "op": "create",
                    "path": "generated.py",
                    "content_b64": base64.b64encode(content).decode("ascii"),
                    "after_sha256": hashlib.sha256(content).hexdigest(),
                }
            ]
        }
        changeset = prepare_from_json(
            payload,
            root=root,
            base_generation="base-g1",
            overlay_generation="overlay-g1",
            attempt="attempt-1",
            worktree_id="wt-241",
            lease_id="lease-241",
            fencing_token="fence-241",
            allowed_paths=("generated.py",),
        )
        binary_rows: list[dict[str, Any]] = []
        json_rows: list[dict[str, Any]] = []
        journal_rows: list[dict[str, Any]] = []
        adapter_rows: list[dict[str, Any]] = []
        adapter = DevCliAdapter()
        for index in range(repetitions):
            started = time.perf_counter_ns()
            cpu = time.process_time_ns()
            encoded = changeset.encode()
            decoded = decode_binary(encoded)
            if decoded.changeset_id != changeset.changeset_id:
                raise AssertionError("binary changeset identity mismatch")
            binary_rows.append(
                {
                    "wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
                    "cpu_ms": (time.process_time_ns() - cpu) / 1_000_000,
                    "bytes": len(encoded),
                }
            )

            started = time.perf_counter_ns()
            cpu = time.process_time_ns()
            encoded_json = json.dumps(changeset.to_dict(), sort_keys=True).encode("utf-8")
            if prepare_from_json(
                json.loads(encoded_json),
                root=root,
                base_generation="base-g1",
                overlay_generation="overlay-g1",
                attempt="attempt-1",
                worktree_id="wt-241",
                lease_id="lease-241",
                fencing_token="fence-241",
                allowed_paths=("generated.py",),
            ).changeset_id != changeset.changeset_id:
                raise AssertionError("JSON changeset identity mismatch")
            json_rows.append(
                {
                    "wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
                    "cpu_ms": (time.process_time_ns() - cpu) / 1_000_000,
                    "bytes": len(encoded_json),
                }
            )

            journal_path = root / f"journal-{index}.bin"
            started = time.perf_counter_ns()
            cpu = time.process_time_ns()
            journal = BinaryChangeJournal(
                journal_path,
                worktree_id="wt-241",
                lease_id="lease-241",
                fencing_token="fence-241",
            )
            journal.append(changeset, "prepared", evidence={"repetition": index})
            if len(journal.read()) != 1:
                raise AssertionError("journal round trip failed")
            journal_rows.append(
                {
                    "wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
                    "cpu_ms": (time.process_time_ns() - cpu) / 1_000_000,
                    "bytes": journal_path.stat().st_size,
                }
            )

            started = time.perf_counter_ns()
            cpu = time.process_time_ns()
            materialized = adapter.materialize(changeset, root)
            if materialized.get("schema") != "simplicio.fast.dev-cli-adapter/v1":
                raise AssertionError("adapter schema mismatch")
            adapter_rows.append(
                {
                    "wall_ms": (time.perf_counter_ns() - started) / 1_000_000,
                    "cpu_ms": (time.process_time_ns() - cpu) / 1_000_000,
                    "bytes": len(json.dumps(materialized, sort_keys=True).encode()),
                }
            )
            (root / "generated.py").unlink(missing_ok=True)

        return {
            "schema": SCHEMA,
            "status": "pass",
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "repetitions": repetitions,
                "rss_kib": _rss_kib(),
                "rss_reason": None if _rss_kib() is not None else "psutil_unavailable",
            },
            "workload": {"operations": 1, "journal_events": 1},
            "binary": _summary(binary_rows),
            "json": _summary(json_rows),
            "journal": _summary(journal_rows),
            "dev_cli_adapter": _summary(adapter_rows),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(repetitions=args.repetitions)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
