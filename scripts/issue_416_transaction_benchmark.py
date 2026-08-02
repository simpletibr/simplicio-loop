"""Reproducible transaction benchmark for issue #416.

The benchmark compares the legacy in-memory mechanical plan application with
the Dev CLI's recoverable Python transaction.  Optional Fast/Rust lanes are
reported as unavailable rather than being represented by guessed numbers.
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
from pathlib import Path
from typing import Any

# Keep the runner reproducible from a source checkout without requiring an
# editable install; installed-wheel smoke remains a separate gate.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from simplicio.changeset_transaction import changeset_digest  # noqa: E402
from simplicio.changeset_v2 import (  # noqa: E402
    adapt_changeset,
    execute_changeset,
    execute_changeset_bytes,
)
from simplicio.fast_contracts import FastEngineError, FastEngineSession  # noqa: E402
from simplicio.mechanical_edit import execute_plan  # noqa: E402

SIZES = (1, 20, 200)


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


def _changeset(size: int) -> dict[str, Any]:
    return {
        "schema": "simplicio.fast.changeset/v2",
        "changeset_id": f"issue-416-{size}",
        "correlation_id": f"issue-416-{size}",
        "generation": "benchmark-generation",
        "allowlist": [f"file-{index}.txt" for index in range(size)],
        "operations": [
            {
                "kind": "replace_range",
                "path": f"file-{index}.txt",
                "start_line": 1,
                "end_line": 1,
                "text": f"updated-{index}\n",
            }
            for index in range(size)
        ],
    }


def _prepare_root(root: Path, size: int) -> None:
    for index in range(size):
        (root / f"file-{index}.txt").write_text(f"original-{index}\n", encoding="utf-8")


def _direct_once(size: int) -> None:
    changeset = _changeset(size)
    plan = adapt_changeset(changeset)
    with tempfile.TemporaryDirectory(prefix=f"issue-416-direct-{size}-") as directory:
        root = Path(directory)
        _prepare_root(root, size)
        result = execute_plan(plan, root=root, apply=True, allow_native=False)
        if result.get("status") != "ok":
            raise RuntimeError(f"direct lane failed: {result}")


def _transaction_once(size: int) -> None:
    changeset = _changeset(size)
    digest = changeset_digest(changeset)
    with tempfile.TemporaryDirectory(prefix=f"issue-416-transaction-{size}-") as directory:
        root = Path(directory)
        _prepare_root(root, size)
        result = execute_changeset(changeset, root=root, apply=True)
        if result.get("status") != "ok" or result.get("transaction", {}).get("state") != "COMMITTED":
            raise RuntimeError(f"transaction lane failed: {result}")
        if result.get("transaction", {}).get("changeset_digest") != digest:
            raise RuntimeError("transaction lane returned an unexpected changeset digest")


def _fast_binary_module() -> Any | None:
    try:
        return importlib.import_module("simplicio_fast.binary_changeset")
    except (ImportError, ModuleNotFoundError):
        return None


def _fast_payload(size: int, root: Path, module: Any) -> bytes:
    operations = []
    for index in range(size):
        before = f"original-{index}\n".encode()
        after = f"updated-{index}\n".encode()
        operations.append(
            {
                "op": "replace-range",
                "path": f"file-{index}.txt",
                "before_sha256": hashlib.sha256(before).hexdigest(),
                "after_sha256": hashlib.sha256(after).hexdigest(),
                "content": after.decode("utf-8"),
                "line_map": {"start_line": 1, "end_line": 1},
            }
        )
    changeset = module.prepare_from_json(
        {"operations": operations},
        root=root,
        base_generation="benchmark-generation",
        overlay_generation="benchmark-overlay",
        attempt=f"issue-416-attempt-{size}",
        worktree_id=f"issue-416-worktree-{size}",
        lease_id="issue-416-lease",
        fencing_token="issue-416-fence",
        allowed_paths=tuple(f"file-{index}.txt" for index in range(size)),
    )
    return changeset.encode()


def _fast_once(size: int, engine: str, module: Any, session: FastEngineSession) -> None:
    with tempfile.TemporaryDirectory(prefix=f"issue-416-fast-{engine}-{size}-") as directory:
        root = Path(directory)
        _prepare_root(root, size)
        result = execute_changeset_bytes(
            _fast_payload(size, root, module),
            root=root,
            apply=True,
            fast_engine=engine,
            engine_session=session,
        )
        if (
            result.get("status") != "ok"
            or result.get("input_format") != "simplicio.fast.binary-changeset/v1"
            or result.get("fast_engine", {}).get("name") != engine
            or result.get("transaction", {}).get("state") != "COMMITTED"
        ):
            raise RuntimeError(f"Fast {engine} lane failed: {result}")


def _fast_lane_unavailable(engine: str, module: Any | None, session: FastEngineSession) -> str | None:
    if module is None:
        return "simplicio-fast binary producer is not installed"
    if engine == "rust":
        native = os.environ.get("SIMPLICIO_FAST_NATIVE", "").strip()
        if not native:
            return "SIMPLICIO_FAST_NATIVE is not configured"
        if not Path(native).is_file():
            return "SIMPLICIO_FAST_NATIVE does not point to a file"
    try:
        selected = session.select(engine)
    except FastEngineError as exc:
        return f"Fast {engine} decoder unavailable: {exc}"
    if selected.name != engine:
        return f"Fast engine selection returned {selected.name!r}, expected {engine!r}"
    return None


def _measure(fn: Callable[[int], None], size: int, repeats: int) -> dict[str, Any]:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn(size)
        samples.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples)
    return {
        "status": "PASS",
        "repeats": repeats,
        "p50_ms": statistics.median(samples),
        "p95_ms": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


def run_benchmark(*, repeats: int = 10) -> dict[str, Any]:
    if repeats < 10:
        raise ValueError("issue #416 benchmark requires at least 10 repetitions")
    rows: list[dict[str, Any]] = []
    module = _fast_binary_module()
    session = FastEngineSession()
    availability = {engine: _fast_lane_unavailable(engine, module, session) for engine in ("python", "rust")}
    try:
        for size in SIZES:
            for lane, function in (
                ("direct_mechanical", _direct_once),
                ("python_transaction", _transaction_once),
            ):
                rows.append({"size": size, "lane": lane, **_measure(function, size, repeats)})
            for lane, engine in (
                ("fast_python_apply", "python"),
                ("fast_rust_apply", "rust"),
            ):
                reason = availability[engine]
                if reason is None:
                    assert module is not None

                    def run_fast(value: int, selected: str = engine) -> None:
                        _fast_once(value, selected, module, session)

                    rows.append(
                        {
                            "size": size,
                            "lane": lane,
                            **_measure(run_fast, size, repeats),
                        }
                    )
                else:
                    rows.append(
                        {
                            "size": size,
                            "lane": lane,
                            "status": "UNAVAILABLE",
                            "reason": reason,
                            "repeats": 0,
                        }
                    )
    finally:
        session.close()
    return {
        "schema": "simplicio.dev-cli.issue-416-transaction-benchmark/v1",
        "issue": 416,
        "commit_sha": _commit_sha(),
        "repeats": repeats,
        "sizes": list(SIZES),
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "fast_lanes": {
            engine: {
                "status": "READY" if reason is None else "UNAVAILABLE",
                **({} if reason is None else {"reason": reason}),
            }
            for engine, reason in availability.items()
        },
        "rows": rows,
        "limitations": [
            "direct_mechanical is a baseline, not a production transaction",
            "Fast lanes use the official binary producer and Dev CLI transaction consumer; "
            "Rust is unavailable without SIMPLICIO_FAST_NATIVE",
            "fsync/rename/CPU/RSS counters are not exposed by the current transaction receipt",
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
