#!/usr/bin/env python3
"""Reproducible N-worktree benchmark: canonical-reuse vs full remap (issue #269).

Creates ``N`` real ``git worktree`` checkouts of the same small synthetic
repository (all sharing the same clean commit -- the common case this issue
targets: several ephemeral worktrees spun up from the same default-branch
commit before any local edits happen) and measures, for each worktree, the
real wall-clock cost of:

- ``full``: ``simplicio_mapper.mapper.emit.build_artifacts`` (the existing,
  unmodified full mapping pipeline) run directly against that worktree.
- ``canonical-reuse``: ``simplicio_mapper.mapper.canonical_reuse.attempt_canonical_reuse``
  opted in, run directly against that worktree.

Only the first worktree in the canonical-reuse group pays the real canonical
build cost (detached-checkout + full pipeline, done once, content-addressed);
every subsequent worktree in that group reuses the same on-disk manifest.

Honesty constraints this script follows (repo-wide "no unmeasured claims"
rule):

- Every number printed/written is a real ``time.perf_counter()`` measurement
  over this exact fixture on this exact machine -- never an assumption or
  extrapolation.
- CPU time and peak RSS are reported for **both** the measured Python
  process (``resource.getrusage(RUSAGE_SELF)`` / ``time.process_time()``)
  *and* its child processes (``resource.getrusage(RUSAGE_CHILDREN)``) --
  schema v2 (issue #236 epic closure). The distinction matters here: both
  the ``full`` and ``canonical-reuse`` code paths shell out to real ``git``
  subprocesses (``simplicio_mapper/mapper/canonical_builder.py::_run_git``,
  invoked via ``subprocess.run`` for ``ls-tree``/``worktree add`` on a
  canonical-build cache miss), so a self-only measurement silently drops
  that cost. ``None`` on platforms without the stdlib ``resource`` module
  (POSIX-only; see the "Limitations" section in
  ``docs/features/canonical-map-lifecycle.md`` for the Windows/macOS gap
  this implies).
- I/O is approximated with the stdlib-only proxy ``resource.getrusage``
  already exposes: ``ru_inblock``/``ru_oublock`` (block input/output
  operations), reported as a delta across the measured call, for both self
  and children. This is a real kernel-reported counter, not a new
  dependency (no ``psutil`` -- see the repo-wide "never add a dependency
  without asking" rule) and not a fabricated number, but it is coarser than
  a full strace-level I/O trace: it counts block I/O operations, not bytes,
  and on some kernels/filesystems reads served entirely from page cache may
  not increment it. Documented as exactly that, not oversold.
- The synthetic fixture is intentionally small (documented file count/size
  below) so the benchmark runs in seconds inside CI/local dev, not minutes --
  the ratio this measures is the *shape* of the reuse-vs-remap tradeoff for
  this repo's own pipeline cost profile, not a universal number that holds at
  every possible repo size. See ``docs/evidence/canonical-reuse-benchmark.json``
  for the last real run's raw numbers and this same caveat restated.

Usage::

    python3 scripts/canonical_reuse_benchmark.py --worktrees 5 --files 200
    python3 scripts/canonical_reuse_benchmark.py --update-doc   # also writes
                                                                 # the JSON doc
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.canonical_reuse import attempt_canonical_reuse  # noqa: E402
from simplicio_mapper.mapper.emit import build_artifacts  # noqa: E402

try:
    import resource

    _HAS_RESOURCE = True
except ImportError:  # pragma: no cover - resource is POSIX-only
    _HAS_RESOURCE = False

SCHEMA = "simplicio.canonical-reuse-benchmark/v2"
JSON_DOC_PATH = ROOT / "docs" / "evidence" / "canonical-reuse-benchmark.json"


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def _build_fixture_repo(repo: Path, *, files: int) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "--initial-branch", "main"], repo)
    _run_git(["config", "user.email", "bench@example.com"], repo)
    _run_git(["config", "user.name", "Benchmark"], repo)
    src = repo / "src"
    src.mkdir(exist_ok=True)
    for index in range(files):
        module = src / f"module_{index:04d}.py"
        module.write_text(
            "\n".join(
                [
                    "import os",
                    f"import module_{(index - 1) % files:04d} as _prev  # noqa: F401"
                    if index
                    else "import os",
                    "",
                    f"def handler_{index}(value: int) -> int:",
                    f'    """Deterministic synthetic handler #{index} for the benchmark fixture."""',
                    f"    return value + {index}",
                    "",
                    f"class Service{index}:",
                    "    def run(self) -> int:",
                    f"        return handler_{index}({index})",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    (repo / "README.md").write_text("Synthetic canonical-reuse benchmark fixture.\n", encoding="utf-8")
    _run_git(["add", "."], repo)
    _run_git(["commit", "-m", "init"], repo)


@dataclass(frozen=True)
class RunMeasurement:
    label: str
    worktree_index: int
    wall_s: float
    cpu_s: float | None
    peak_rss_kb: int | None
    files_mapped: int
    # -- schema v2 (issue #236 epic closure) --------------------------------
    # Child-process CPU/RSS: the mapper pipeline shells out to real `git`
    # subprocesses (canonical_builder._run_git); RUSAGE_SELF alone silently
    # drops that cost, so it is measured separately here rather than folded
    # into cpu_s/peak_rss_kb (keeps the v1 fields' meaning unchanged).
    cpu_s_children: float | None = None
    peak_rss_kb_children: int | None = None
    # I/O proxy: block input/output op counts (not bytes), delta across the
    # call, self and children. Coarser than a full I/O trace -- see the
    # module docstring's caveat on what this does/doesn't capture.
    io_in_blocks: int | None = None
    io_out_blocks: int | None = None
    io_in_blocks_children: int | None = None
    io_out_blocks_children: int | None = None


def _measure(label: str, worktree_index: int, fn) -> RunMeasurement:
    cpu_before = time.process_time() if _HAS_RESOURCE else None
    rusage_self_before = resource.getrusage(resource.RUSAGE_SELF) if _HAS_RESOURCE else None
    rusage_children_before = resource.getrusage(resource.RUSAGE_CHILDREN) if _HAS_RESOURCE else None
    wall_before = time.perf_counter()
    result = fn()
    wall_after = time.perf_counter()
    cpu_after = time.process_time() if _HAS_RESOURCE else None
    peak_rss_kb = None
    cpu_s_children = None
    peak_rss_kb_children = None
    io_in_blocks = None
    io_out_blocks = None
    io_in_blocks_children = None
    io_out_blocks_children = None
    if _HAS_RESOURCE:
        rusage_self_after = resource.getrusage(resource.RUSAGE_SELF)
        rusage_children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        # ru_maxrss is cumulative peak-so-far for the whole process (and,
        # separately, for its children) on Linux (KB) -- reported as-is, not
        # a per-call delta; see the module docstring for what this does/
        # doesn't isolate.
        peak_rss_kb = rusage_self_after.ru_maxrss
        peak_rss_kb_children = rusage_children_after.ru_maxrss
        cpu_s_children = round(
            (rusage_children_after.ru_utime + rusage_children_after.ru_stime)
            - (rusage_children_before.ru_utime + rusage_children_before.ru_stime),
            4,
        )
        io_in_blocks = rusage_self_after.ru_inblock - rusage_self_before.ru_inblock
        io_out_blocks = rusage_self_after.ru_oublock - rusage_self_before.ru_oublock
        io_in_blocks_children = rusage_children_after.ru_inblock - rusage_children_before.ru_inblock
        io_out_blocks_children = rusage_children_after.ru_oublock - rusage_children_before.ru_oublock
    return RunMeasurement(
        label=label,
        worktree_index=worktree_index,
        wall_s=round(wall_after - wall_before, 4),
        cpu_s=round(cpu_after - cpu_before, 4) if cpu_before is not None else None,
        peak_rss_kb=peak_rss_kb,
        files_mapped=result,
        cpu_s_children=cpu_s_children,
        peak_rss_kb_children=peak_rss_kb_children,
        io_in_blocks=io_in_blocks,
        io_out_blocks=io_out_blocks,
        io_in_blocks_children=io_in_blocks_children,
        io_out_blocks_children=io_out_blocks_children,
    )


def run_benchmark(*, worktrees: int, files: int) -> dict[str, Any]:
    base = Path(tempfile.mkdtemp(prefix="simplicio-canonical-reuse-bench-"))
    try:
        repo = base / "origin"
        _build_fixture_repo(repo, files=files)

        full_measurements: list[RunMeasurement] = []
        reuse_measurements: list[RunMeasurement] = []

        # --- full remap group: N independent worktrees, each maps from scratch.
        full_worktrees: list[Path] = []
        for index in range(worktrees):
            wt = base / f"full-wt-{index}"
            _run_git(["worktree", "add", "--detach", str(wt), "main"], repo)
            full_worktrees.append(wt)
        try:
            for index, wt in enumerate(full_worktrees):

                def _full_run(wt: Path = wt) -> int:
                    artifacts = build_artifacts(
                        str(wt), meta=None, incremental=False, output_dir=".simplicio-loop"
                    )
                    return len(artifacts["project_map"]["files"])

                full_measurements.append(_measure("full", index, _full_run))
        finally:
            for wt in full_worktrees:
                _run_git(["worktree", "remove", "--force", str(wt)], repo)

        # --- canonical-reuse group: N independent worktrees, opted in. Only
        # the first pays the real canonical-build cost; the rest hit cache.
        reuse_cache_root = base / "reuse-cache"
        os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = str(reuse_cache_root)
        reuse_worktrees: list[Path] = []
        try:
            for index in range(worktrees):
                wt = base / f"reuse-wt-{index}"
                _run_git(["worktree", "add", "--detach", str(wt), "main"], repo)
                reuse_worktrees.append(wt)

                def _reuse_run(wt: Path = wt) -> int:
                    outcome = attempt_canonical_reuse(str(wt), ".simplicio-loop", {})
                    if outcome.run_result is None:
                        raise RuntimeError(f"expected a hit, got fallback: {outcome.receipt}")
                    return len(outcome.run_result["project_map"]["files"])

                reuse_measurements.append(_measure("canonical-reuse", index, _reuse_run))
        finally:
            for wt in reuse_worktrees:
                _run_git(["worktree", "remove", "--force", str(wt)], repo)
            os.environ.pop("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)

        full_total_wall = sum(m.wall_s for m in full_measurements)
        reuse_total_wall = sum(m.wall_s for m in reuse_measurements)
        speedup = (full_total_wall / reuse_total_wall) if reuse_total_wall > 0 else None

        return {
            "schema": SCHEMA,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "fixture": {"worktrees": worktrees, "files_per_worktree": files},
            "full_remap": {
                "runs": [asdict(m) for m in full_measurements],
                "total_wall_s": round(full_total_wall, 4),
            },
            "canonical_reuse": {
                "runs": [asdict(m) for m in reuse_measurements],
                "total_wall_s": round(reuse_total_wall, 4),
                "note": (
                    "Only reuse_measurements[0] pays the real canonical-build "
                    "cost (detached checkout + full pipeline once); every "
                    "subsequent entry hits the same content-addressed manifest."
                ),
            },
            "wall_time_speedup_ratio": round(speedup, 3) if speedup is not None else None,
            "caveats": [
                "Wall time is a real perf_counter() measurement on this "
                "machine, this fixture size, this one run -- not averaged "
                "over multiple runs and not a guarantee of the same ratio "
                "at a different repo size.",
                "cpu_s is time.process_time() for the main process only; it "
                "does not include time spent in the `git worktree add` "
                "subprocess calls used to set up the fixture (those are "
                "outside the measured window) but does include the "
                "in-process `git` subprocess calls issued by the mapper "
                "pipeline itself (git status/diff, invoked via subprocess.run "
                "from this same process).",
                "peak_rss_kb is the whole process's cumulative peak-so-far "
                "(ru_maxrss), not an isolated delta for one call -- later "
                "measurements in the same process run never show a lower "
                "number than an earlier one even if that call itself used "
                "less memory.",
                "schema v2 (issue #236): cpu_s_children/peak_rss_kb_children "
                "are resource.getrusage(RUSAGE_CHILDREN) deltas covering the "
                "real `git` subprocesses the pipeline shells out to "
                "(canonical_builder._run_git) -- this is what v1 silently "
                "dropped by only measuring RUSAGE_SELF.",
                "io_in_blocks/io_out_blocks(_children) are "
                "resource.getrusage ru_inblock/ru_oublock deltas (block "
                "I/O operation counts, not bytes) -- a real stdlib-reported "
                "kernel counter, not a byte-accurate I/O trace; reads fully "
                "served from page cache may not increment it on every "
                "kernel/filesystem. No syscall-level tracing or page-cache "
                "hit/miss counters are collected here.",
                "All new v2 fields are POSIX-only (None on platforms "
                "without the stdlib `resource` module, e.g. Windows) -- "
                "this benchmark has only ever been run inside a Linux "
                "container; macOS/Windows numbers do not exist and this "
                "script cannot produce them from here.",
            ],
        }
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktrees", type=int, default=5)
    parser.add_argument("--files", type=int, default=150)
    parser.add_argument(
        "--update-doc",
        action="store_true",
        help=f"Also write the raw result to {JSON_DOC_PATH.relative_to(ROOT)}",
    )
    args = parser.parse_args(argv)

    report = run_benchmark(worktrees=args.worktrees, files=args.files)
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.update_doc:
        JSON_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        JSON_DOC_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"-> wrote {JSON_DOC_PATH.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
