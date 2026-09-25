"""Reproducible Fast hot-path benchmark for issue #419.

The benchmark compares the recoverable Python transaction with the official
Fast binary producer consumed by the Dev CLI's in-memory engine.  It exercises
one, five, and ten isolated worktrees and records the engine counters from the
actual receipts.  Missing optional Fast/Rust lanes remain ``UNAVAILABLE``;
the report never substitutes guessed timings.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from simplicio.changeset_v2 import execute_changeset, execute_changeset_bytes  # noqa: E402
from simplicio.fast_contracts import FastEngineError, FastEngineSession  # noqa: E402

SIZES = (1, 20, 200)
WORKTREE_COUNTS = (1, 5, 10)
MIN_REPEATS = 10
FAST_BINARY_SCHEMA = "simplicio.fast.binary-changeset/v1"
METRIC_KEYS = (
    "decode_calls",
    "bytes_decoded",
    "copies",
    "serializations",
    "subprocesses",
    "refresh_calls",
    "refresh_pending",
)


def _commit_sha() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _fast_binary_module() -> Any | None:
    try:
        return importlib.import_module("simplicio_fast.binary_changeset")
    except (ImportError, ModuleNotFoundError):
        return None


def _paths(size: int, run_id: str) -> tuple[str, ...]:
    return tuple(f"file-{run_id}-{index}.txt" for index in range(size))


def _json_changeset(size: int, run_id: str) -> dict[str, Any]:
    paths = _paths(size, run_id)
    return {
        "schema": "simplicio.fast.changeset/v2",
        "changeset_id": f"issue-419-json-{run_id}",
        "correlation_id": f"issue-419-json-{run_id}",
        "generation": "issue-419-generation",
        "allowlist": list(paths),
        "operations": [
            {"kind": "create", "path": path, "content": f"fast-hot-path-{index}\n"}
            for index, path in enumerate(paths)
        ],
    }


def _fast_payload(size: int, root: Path, module: Any, run_id: str) -> bytes:
    paths = _paths(size, run_id)
    operations = []
    for index, path in enumerate(paths):
        content = f"fast-hot-path-{index}\n".encode()
        operations.append(
            {
                "op": "create",
                "path": path,
                "content": content.decode("utf-8"),
                "after_sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    changeset = module.prepare_from_json(
        {"operations": operations},
        root=root,
        base_generation="issue-419-generation",
        overlay_generation="issue-419-overlay",
        attempt=f"issue-419-attempt-{run_id}",
        worktree_id=f"issue-419-worktree-{run_id}",
        lease_id="issue-419-lease",
        fencing_token="issue-419-fence",
        allowed_paths=paths,
    )
    return changeset.encode()


def _stats(samples: list[float], *, repeats: int, worktrees: int) -> dict[str, Any]:
    ordered = sorted(samples)
    return {
        "status": "PASS",
        "repeats": repeats,
        "worktrees": worktrees,
        "samples": len(samples),
        "p50_ms": statistics.median(samples),
        "p95_ms": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


def _empty_metrics() -> dict[str, int]:
    return {key: 0 for key in METRIC_KEYS}


def _sum_metrics(rows: list[dict[str, int]]) -> dict[str, int]:
    result = _empty_metrics()
    for row in rows:
        for key in METRIC_KEYS:
            result[key] += int(row.get(key, 0))
    return result


def _validate_fast_receipt(
    receipt: dict[str, Any],
    *,
    engine: str,
    expected_paths: tuple[str, ...],
) -> None:
    if receipt.get("status") != "ok":
        raise RuntimeError(f"Fast {engine} lane failed: {receipt}")
    if receipt.get("input_format") != FAST_BINARY_SCHEMA:
        raise RuntimeError(f"Fast {engine} lane did not consume binary input: {receipt}")
    if receipt.get("transaction", {}).get("state") != "COMMITTED":
        raise RuntimeError(f"Fast {engine} lane did not commit: {receipt}")
    fast_receipt = receipt.get("fast_engine", {})
    if fast_receipt.get("name") != engine:
        raise RuntimeError(f"Fast lane selected {fast_receipt.get('name')!r}, expected {engine!r}")
    refresh = receipt.get("refresh", {})
    if refresh.get("status") != "refreshed" or tuple(refresh.get("paths", ())) != expected_paths:
        raise RuntimeError(f"Fast {engine} selective refresh failed: {receipt}")


def _run_json_worker(root: Path, size: int, repeats: int, worker: int) -> dict[str, Any]:
    samples: list[float] = []
    for repeat in range(repeats):
        run_id = f"json-{worker}-{repeat}"
        started = time.perf_counter()
        receipt = execute_changeset(_json_changeset(size, run_id), root=root, apply=True)
        if receipt.get("status") != "ok" or receipt.get("transaction", {}).get("state") != "COMMITTED":
            raise RuntimeError(f"Python transaction lane failed: {receipt}")
        samples.append((time.perf_counter() - started) * 1000)
    return {"samples": samples, "metrics": _empty_metrics()}


def _run_fast_worker(
    root: Path,
    size: int,
    engine: str,
    repeats: int,
    worker: int,
    module: Any,
) -> dict[str, Any]:
    samples: list[float] = []
    session = FastEngineSession()
    try:
        for repeat in range(repeats):
            run_id = f"{engine}-{worker}-{repeat}"
            paths = _paths(size, run_id)

            def refresh(selected: tuple[str, ...]) -> dict[str, Any]:
                return {"selected_paths": list(selected)}

            started = time.perf_counter()
            receipt = execute_changeset_bytes(
                _fast_payload(size, root, module, run_id),
                root=root,
                apply=True,
                fast_engine=engine,
                engine_session=session,
                refresh_fn=refresh,
            )
            _validate_fast_receipt(receipt, engine=engine, expected_paths=paths)
            samples.append((time.perf_counter() - started) * 1000)
        final_receipt = receipt
        return {
            "samples": samples,
            "metrics": final_receipt["fast_engine"]["metrics"],
        }
    finally:
        session.close()


def _run_parallel(
    worker_fn: Callable[[Path, int], dict[str, Any]],
    *,
    worktrees: int,
    size: int,
    prefix: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"{prefix}-{size}-{worktrees}-") as directory:
        roots = []
        for index in range(worktrees):
            root = Path(directory) / f"worktree-{index}"
            root.mkdir()
            roots.append(root)
        with ThreadPoolExecutor(max_workers=worktrees) as pool:
            results = list(pool.map(lambda item: worker_fn(item[1], item[0]), enumerate(roots)))
    return {
        "samples": [sample for result in results for sample in result["samples"]],
        "metrics": _sum_metrics([result["metrics"] for result in results]),
    }


def _fast_lane_unavailable(engine: str, module: Any | None) -> str | None:
    if module is None:
        return "simplicio-fast binary producer is not installed"
    if engine == "rust":
        native = os.environ.get("SIMPLICIO_FAST_NATIVE", "").strip()
        if not native:
            return "SIMPLICIO_FAST_NATIVE is not configured"
        if not Path(native).is_file():
            return "SIMPLICIO_FAST_NATIVE does not point to a file"
    session = FastEngineSession()
    try:
        selected = session.select(engine)
    except FastEngineError as exc:
        return f"Fast {engine} decoder unavailable: {exc}"
    finally:
        session.close()
    if selected.name != engine:
        return f"Fast engine selection returned {selected.name!r}, expected {engine!r}"
    return None


def _run_row(
    size: int,
    worktrees: int,
    repeats: int,
    module: Any | None,
    engine: str,
    unavailable: str | None = None,
) -> dict[str, Any]:
    lane = "python_transaction" if engine == "transaction" else f"fast_{engine}_apply"
    if engine == "transaction":
        result = _run_parallel(
            lambda root, worker: _run_json_worker(root, size, repeats, worker),
            worktrees=worktrees,
            size=size,
            prefix="issue-419-python",
        )
        return {
            "size": size,
            "worktrees": worktrees,
            "lane": lane,
            **_stats(result["samples"], repeats=repeats, worktrees=worktrees),
        }

    reason = unavailable
    if reason is not None:
        return {
            "size": size,
            "worktrees": worktrees,
            "lane": lane,
            "status": "UNAVAILABLE",
            "repeats": 0,
            "samples": 0,
            "reason": reason,
        }
    assert module is not None
    result = _run_parallel(
        lambda root, worker: _run_fast_worker(root, size, engine, repeats, worker, module),
        worktrees=worktrees,
        size=size,
        prefix=f"issue-419-fast-{engine}",
    )
    return {
        "size": size,
        "worktrees": worktrees,
        "lane": lane,
        **_stats(result["samples"], repeats=repeats, worktrees=worktrees),
        "metrics": result["metrics"],
    }


def run_benchmark(*, repeats: int = MIN_REPEATS) -> dict[str, Any]:
    if repeats < MIN_REPEATS:
        raise ValueError(f"issue #419 benchmark requires at least {MIN_REPEATS} repetitions")
    module = _fast_binary_module()
    availability = {engine: _fast_lane_unavailable(engine, module) for engine in ("python", "rust")}
    rows: list[dict[str, Any]] = []
    for size in SIZES:
        for worktrees in WORKTREE_COUNTS:
            rows.append(_run_row(size, worktrees, repeats, module, "transaction", None))
            for engine in ("python", "rust"):
                rows.append(_run_row(size, worktrees, repeats, module, engine, availability[engine]))
    return {
        "schema": "simplicio.dev-cli.issue-419-fast-hot-path-benchmark/v1",
        "issue": 419,
        "commit_sha": _commit_sha(),
        "repeats": repeats,
        "sizes": list(SIZES),
        "worktrees": list(WORKTREE_COUNTS),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "fast_lanes": {
            engine: {
                "status": "READY" if availability[engine] is None else "UNAVAILABLE",
                **({} if availability[engine] is None else {"reason": availability[engine]}),
            }
            for engine in ("python", "rust")
        },
        "rows": rows,
        "limitations": [
            "timings include official Fast producer preparation and transaction execution",
            (
                "Rust lane starts one long-lived native decoder session per worktree; it must not scale with "
                "file count"
            ),
            "the benchmark proves local producer/consumer behavior only; Runtime and cross-platform lanes "
            "remain external",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=MIN_REPEATS)
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
