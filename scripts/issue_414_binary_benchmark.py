"""Benchmark the official Fast binary adapter against the legacy JSON adapter."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from simplicio.changeset_v2 import execute_changeset, execute_changeset_bytes  # noqa: E402

SIZES = (1, 20, 200)


def _json_changeset(size: int) -> dict[str, Any]:
    return {
        "schema": "simplicio.fast.changeset/v2",
        "changeset_id": f"issue-414-{size}",
        "correlation_id": f"issue-414-{size}",
        "generation": "benchmark-generation",
        "allowlist": [f"file-{index}.txt" for index in range(size)],
        "operations": [
            {"kind": "create", "path": f"file-{index}.txt", "content": f"binary-{index}\n"}
            for index in range(size)
        ],
    }


def _binary_payload(size: int, root: Path) -> bytes | None:
    try:
        from simplicio_fast.binary_changeset import BinaryChangeSet, ChangeOperation
    except (ImportError, ModuleNotFoundError):
        return None
    operations = tuple(
        ChangeOperation.from_dict(
            {
                "op": "create",
                "path": f"file-{index}.txt",
                "content_b64": base64.b64encode(f"binary-{index}\n".encode()).decode(),
                "after_sha256": hashlib.sha256(f"binary-{index}\n".encode()).hexdigest(),
            }
        )
        for index in range(size)
    )
    return BinaryChangeSet(
        repository=str(root.resolve()),
        base_generation="benchmark-generation",
        overlay_generation="benchmark-overlay",
        attempt="benchmark-attempt",
        worktree_id=f"benchmark-{size}",
        lease_id="benchmark-lease",
        fencing_token="benchmark-fence",
        allowed_paths=tuple(f"file-{index}.txt" for index in range(size)),
        operations=operations,
    ).encode()


def _measure(fn: Callable[[], dict[str, Any]], repeats: int) -> dict[str, Any]:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        result = fn()
        if result.get("status") != "ok":
            raise RuntimeError(f"benchmark lane failed: {result}")
        samples.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples)
    return {
        "status": "PASS",
        "repeats": repeats,
        "p50_ms": statistics.median(samples),
        "p95_ms": ordered[max(0, int(len(ordered) * 0.95) - 1)],
    }


def run_benchmark(*, repeats: int = 10) -> dict[str, Any]:
    if repeats < 10:
        raise ValueError("issue #414 benchmark requires at least 10 repetitions")
    rows: list[dict[str, Any]] = []
    for size in SIZES:
        for lane in ("json_legacy_adapter", "binary_fast_adapter", "binary_fast_rust_adapter"):
            if lane in {"binary_fast_adapter", "binary_fast_rust_adapter"}:
                if lane == "binary_fast_rust_adapter" and not os.environ.get("SIMPLICIO_FAST_NATIVE"):
                    rows.append(
                        {
                            "size": size,
                            "lane": lane,
                            "status": "UNAVAILABLE",
                            "repeats": 0,
                            "reason": "SIMPLICIO_FAST_NATIVE is not configured",
                        }
                    )
                    continue
                with tempfile.TemporaryDirectory(prefix=f"issue-414-probe-{size}-") as directory:
                    available = _binary_payload(size, Path(directory)) is not None
                if not available:
                    rows.append(
                        {
                            "size": size,
                            "lane": lane,
                            "status": "UNAVAILABLE",
                            "repeats": 0,
                            "reason": "simplicio-fast Python conformance decoder is not installed",
                        }
                    )
                    continue

                engine = "rust" if lane == "binary_fast_rust_adapter" else "python"

                def run_binary(size: int = size, engine: str = engine) -> dict[str, Any]:
                    with tempfile.TemporaryDirectory(prefix="run-") as run_dir:
                        payload = _binary_payload(size, Path(run_dir))
                        assert payload is not None
                        return execute_changeset_bytes(payload, root=run_dir, apply=True, fast_engine=engine)

                rows.append({"size": size, "lane": lane, **_measure(run_binary, repeats)})
            else:

                def run_json(size: int = size) -> dict[str, Any]:
                    with tempfile.TemporaryDirectory(prefix="run-") as run_dir:
                        return execute_changeset(_json_changeset(size), root=run_dir, apply=True)

                rows.append({"size": size, "lane": lane, **_measure(run_json, repeats)})
    return {
        "schema": "simplicio.dev-cli.issue-414-binary-benchmark/v1",
        "issue": 414,
        "repeats": repeats,
        "sizes": list(SIZES),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "rows": rows,
        "limitations": [
            "This measures adapter plus transaction execution, not parser-only latency",
            "copy/allocation/RSS counters are null because the current public contract does not expose them",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(repeats=args.repeats)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
