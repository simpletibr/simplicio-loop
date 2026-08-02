"""Measure full versus causal-set source verification for issue #415."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from simplicio.plan_compiler.mapper_context import verify_context_sources  # noqa: E402

SCHEMA = "simplicio.dev-cli.issue-415-verification-benchmark/v1"
PACK_SIZES = {"small": 10, "medium": 100, "large": 1000}
REPEATS = 10


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


def _binding(root: Path, count: int) -> Any:
    entries = []
    for index in range(count):
        relative = f"src/file-{index:04d}.py"
        content = f"value = {index}\n".encode()
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        entries.append({"path": relative, "snapshot_hash": hashlib.sha256(content).hexdigest()})
    return SimpleNamespace(
        pack=SimpleNamespace(files=tuple(entries)),
        context_handle=SimpleNamespace(generation="benchmark-generation"),
    )


def _delta(path: str) -> dict[str, Any]:
    return {
        "schema": "simplicio.graph-delta/v1",
        "version": 1,
        "event_type": "delta",
        "mode": "incremental",
        "base_revision": "benchmark-generation",
        "scan_revision": "benchmark-generation-next",
        "full_rescan": False,
        "ordering": {"strategy": "op,entity_type,id", "deterministic": True},
        "events": [],
        "affected_paths": [path],
        "diagnostics": [],
        "snapshot": {},
    }


def _measure(fn: Any) -> dict[str, Any]:
    samples = []
    metrics = None
    for _ in range(REPEATS):
        started = time.perf_counter()
        metrics = fn()
        samples.append((time.perf_counter() - started) * 1000.0)
    assert metrics is not None
    ordered = sorted(samples)
    return {
        "repeats": REPEATS,
        "p50_ms": statistics.median(samples),
        "p95_ms": ordered[max(0, int(REPEATS * 0.95) - 1)],
        "files_hashed": metrics["files_hashed"],
        "bytes_read": metrics["bytes_read"],
    }


def _case(size_name: str, count: int, writers: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"issue-415-{size_name}-{writers}-") as raw_root:
        root = Path(raw_root)
        binding = _binding(root, count)
        causal_path = (f"src/file-{count - 1:04d}.py",)
        causal_delta = _delta(causal_path[0])

        def full() -> dict[str, Any]:
            return verify_context_sources(binding, source_root=str(root))

        def causal() -> dict[str, Any]:
            return verify_context_sources(
                binding, source_root=str(root), paths=causal_path, delta=causal_delta
            )

        def concurrent() -> dict[str, Any]:
            # Use detached Git worktrees rather than N threads over one
            # shared binding. This exercises independent roots and commits.
            if shutil.which("git") is None:
                raise RuntimeError("git is required for the worktree benchmark")
            with tempfile.TemporaryDirectory(prefix=f"issue-415-{size_name}-{writers}-git-") as raw_repo:
                repo = Path(raw_repo)
                _binding(repo, count)
                subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
                subprocess.run(
                    ["git", "config", "user.email", "issue-415@example.invalid"], cwd=repo, check=True
                )
                subprocess.run(["git", "config", "user.name", "issue-415-benchmark"], cwd=repo, check=True)
                subprocess.run(["git", "add", "src"], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-qm", "benchmark fixture"], cwd=repo, check=True)
                lanes = []
                for lane in range(writers):
                    lane_root = repo / f"worktree-{lane}"
                    subprocess.run(
                        ["git", "worktree", "add", "--detach", "-q", str(lane_root), "HEAD"],
                        cwd=repo,
                        check=True,
                    )
                    lanes.append((lane_root, _binding(lane_root, count)))
                with ThreadPoolExecutor(max_workers=writers) as pool:
                    results = list(
                        pool.map(
                            lambda pair: verify_context_sources(
                                pair[1],
                                source_root=str(pair[0]),
                                paths=causal_path,
                                delta=causal_delta,
                            ),
                            lanes,
                        )
                    )
            return {
                "files_hashed": sum(row["files_hashed"] for row in results),
                "bytes_read": sum(row["bytes_read"] for row in results),
            }

        return {
            "pack": size_name,
            "files": count,
            "writers": writers,
            "worktrees": writers,
            "worktree_kind": "git-detached",
            "full": _measure(full),
            "causal": _measure(causal),
            "causal_concurrent": _measure(concurrent),
        }


def run_benchmark() -> dict[str, Any]:
    rows = [_case(name, count, writers) for name, count in PACK_SIZES.items() for writers in (1, 5, 10)]
    return {
        "schema": SCHEMA,
        "commit_sha": _commit_sha(),
        "repeats": REPEATS,
        "python": sys.version.split()[0],
        "rows": rows,
        "limitations": [
            "The harness measures Dev CLI verification with a validated-shaped binding;",
            "it does not claim a fresh external Mapper or Rust provider.",
            "CPU/RSS are null because the public verification contract does not expose those counters.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(run_benchmark(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
