#!/usr/bin/env python3
"""Benchmark: remapping cost of a small change -- canonical/overlay path vs
full from-scratch remap (issue #286 step 12 -- the first metric
`scripts/prototype_context_benchmark.py` explicitly deferred: "remapping-cost
comparison (needs a canonical-map/overlay lifecycle, issue #236/#263)").

That lifecycle (ADR-008) now exists: `canonical_builder.py` (build/reuse a
`CanonicalMapManifest` for a default-branch commit),
`canonical_overlay.py::compute_worktree_overlay` (git-diff-only delta of a
worktree against that commit) and `effective_view.py::compose_effective_view`
(pure, O(overlay size) composition -- see that module's docstring). This
script measures the real wall-clock cost of using them for a **small,
non-trivial change** (one file touched) against the naive baseline: rerun
the whole mapping pipeline (`build_artifacts`, `incremental=False`) from
scratch.

`prototype_context.py` itself does not wire the canonical/overlay path yet
(its own docstring lists this as future work depending on issue #236/#263
landing operationally) -- per this benchmark's task brief, when that wiring
is not yet present on this branch this script benchmarks the canonical
builder/overlay APIs directly, which is what a canonical-aware
`prototype_context` would call under the hood.

Two real, timed operations, both against the same tiny synthetic git fixture
(same shape `scripts/canonical_reuse_benchmark.py` already uses):

- ``full_remap``: `build_artifacts(worktree, incremental=False)` run against
  a worktree that has one file touched relative to the canonical commit --
  the naive "just remap everything again" baseline.
- ``incremental_overlay``: reuses the *already-built* canonical manifest
  (built once, out of band, and not counted in this number -- see
  ``canonical_build_seconds`` reported separately) and pays only
  `compute_worktree_overlay()` (git diff/status calls scoped to the delta)
  plus `compose_effective_view()` (pure, in-memory) for that same one-file
  change.

Honest scope limit, stated plainly (matches this module's own documented
limitation, `canonical_reuse.py`'s "Hit only for a *trivial* overlay"
section): `compose_effective_view()` does not re-derive `symbol-index.json`/
`call-graph.json` for the touched file -- it produces a lazy view that
resolves the touched path from the overlay and everything else verbatim from
the canonical manifest. That is *by design* cheaper than a full remap (it
never re-parses/re-derives cross-file relationships for unchanged files),
but it is not claimed to produce an identical `symbol_index`/`call_graph`
output to `full_remap` for the touched file's downstream call edges -- see
`canonical_reuse.py`'s own fallback-to-full-map behavior for a non-trivial
overlay, which is the documented, deliberate reason `attempt_canonical_reuse`
itself never uses this path for a real index/scan run today. This script
measures the primitive's *cost*, not its output-equivalence to a full remap.

`proof_kind: estimated` throughout, matching the ecosystem convention: every
number here is a real `time.perf_counter()` measurement on this run/machine/
fixture size, never an a-priori guess -- but it is one run on one small
fixture, not an average over repo sizes or hardware.

Run: ``python3 scripts/prototype_remap_cost_benchmark.py``
Run (bigger fixture): ``python3 scripts/prototype_remap_cost_benchmark.py --files 300``
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# ruff: noqa: E402, I001
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from simplicio_mapper.mapper.canonical_builder import build_canonical_manifest_with_diagnostics
from simplicio_mapper.mapper.canonical_overlay import compute_worktree_overlay
from simplicio_mapper.mapper.canonical_reuse import compute_config_fingerprint
from simplicio_mapper.mapper.effective_view import compose_effective_view
from simplicio_mapper.mapper.emit import build_artifacts

REPORT_SCHEMA = "simplicio.prototype-remap-cost-benchmark/v1"


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
                    (
                        f"import module_{(index - 1) % files:04d} as _prev  # noqa: F401"
                        if index
                        else "import os"
                    ),
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
    (repo / "README.md").write_text("Synthetic remap-cost benchmark fixture.\n", encoding="utf-8")
    _run_git(["add", "."], repo)
    _run_git(["commit", "-m", "init"], repo)


def _timed(fn) -> tuple[Any, float]:
    started = time.perf_counter()
    result = fn()
    elapsed = round(time.perf_counter() - started, 6)
    return result, elapsed


def run_benchmark(*, files: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="simplicio-remap-cost-bench-") as tmp:
        base = Path(tmp)
        repo = base / "repo"
        _build_fixture_repo(repo, files=files)
        storage_root = base / "canonical-cache"

        # Build the canonical manifest once, out of band -- this is the cost
        # a canonical-map-aware pipeline pays exactly once per default-branch
        # commit, amortized across every worktree/change after it. Not
        # counted in either of the two compared numbers below, but reported
        # so the full picture (amortized cost) is visible, not hidden.
        config_fingerprint = compute_config_fingerprint(None, ".simplicio")
        build_result, canonical_build_seconds = _timed(
            lambda: build_canonical_manifest_with_diagnostics(str(repo), str(storage_root), config_fingerprint)
        )
        manifest = build_result.manifest
        if manifest is None:
            raise SystemExit(f"canonical manifest build failed: reason_code={build_result.reason_code!r}")

        # Touch exactly one file -- the "small change" this metric targets.
        touched = repo / "src" / "module_0000.py"
        original_text = touched.read_text(encoding="utf-8")
        touched.write_text(
            original_text.replace(
                "def handler_0(value: int) -> int:",
                "def handler_0(value: int) -> int:  # remap-cost-benchmark: touched",
            ),
            encoding="utf-8",
        )

        # --- canonical/overlay path: only the delta against the already-built
        # canonical manifest, plus pure in-memory composition. Measured
        # *before* the full remap below writes its own output directory, so
        # that directory's untracked files never leak into this overlay
        # (compute_worktree_overlay sees real git status -- a stray
        # ".simplicio-full/" would otherwise show up as extra "added" noise
        # not caused by the one-file change this benchmark is measuring).
        overlay, overlay_seconds = _timed(
            lambda: compute_worktree_overlay(str(repo), manifest.key, config_fingerprint)
        )
        if overlay is None:
            raise SystemExit("compute_worktree_overlay failed against the benchmark fixture")

        _view, compose_seconds = _timed(lambda: compose_effective_view(manifest, overlay))
        incremental_overlay_seconds = round(overlay_seconds + compose_seconds, 6)

        # --- baseline: full remap of the touched worktree from scratch.
        full_result, full_remap_seconds = _timed(
            lambda: build_artifacts(str(repo), meta=None, incremental=False, output_dir=".simplicio-full")
        )
        full_file_count = len(full_result["project_map"]["files"])

        speedup = (
            round(full_remap_seconds / incremental_overlay_seconds, 3)
            if incremental_overlay_seconds > 0
            else None
        )
        pct_cheaper = (
            round((1 - incremental_overlay_seconds / full_remap_seconds) * 100, 2)
            if full_remap_seconds > 0
            else None
        )

        return {
            "schema": REPORT_SCHEMA,
            "fixture": {"files": files, "touched_file": "src/module_0000.py"},
            "canonical_build_seconds_amortized": canonical_build_seconds,
            "full_remap": {
                "seconds": full_remap_seconds,
                "files_mapped": full_file_count,
                "operation": "build_artifacts(incremental=False) on the touched worktree",
            },
            "incremental_overlay": {
                "seconds": incremental_overlay_seconds,
                "overlay_compute_seconds": overlay_seconds,
                "effective_view_compose_seconds": compose_seconds,
                "changed_files_in_overlay": len(overlay.changed_files),
                "operation": (
                    "compute_worktree_overlay() (git diff/status only) + "
                    "compose_effective_view() (pure, in-memory) against the "
                    "pre-built canonical manifest"
                ),
            },
            "wall_time_speedup_ratio": speedup,
            "pct_cheaper": pct_cheaper,
            "proof_kind": "estimated",
            "proof_kind_note": (
                "full_remap_seconds/incremental_overlay_seconds are real time.perf_counter() "
                "measurements from this exact run against this exact synthetic fixture -- not "
                "an a-priori guess -- but this is one run, one machine, one small fixture size; "
                "not averaged and not a universal ratio at every repo size (same caveat as "
                "scripts/canonical_reuse_benchmark.py)."
            ),
            "known_limitation": (
                "compose_effective_view() does not re-derive symbol_index/call_graph for the "
                "touched file -- it composes a lazy per-path view over the unchanged canonical "
                "manifest. Cheaper by design, but not output-equivalent to full_remap for the "
                "touched file's own downstream symbol/call-graph entries; this is exactly why "
                "canonical_reuse.py's attempt_canonical_reuse() only serves a *trivial* "
                "(no-change) overlay from this composition today and falls back to the full "
                "map for any real change, per its own documented scope."
            ),
        }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    files = 150
    if "--files" in argv:
        files = int(argv[argv.index("--files") + 1])

    report = run_benchmark(files=files)
    if "--json" in argv:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0

    print(f"fixture:                      {report['fixture']['files']} files, touched={report['fixture']['touched_file']}")
    print(f"canonical_build (amortized):  {report['canonical_build_seconds_amortized']}s")
    print(
        f"full_remap:                   {report['full_remap']['seconds']}s "
        f"({report['full_remap']['files_mapped']} files)"
    )
    print(
        f"incremental_overlay:          {report['incremental_overlay']['seconds']}s "
        f"(overlay={report['incremental_overlay']['overlay_compute_seconds']}s, "
        f"compose={report['incremental_overlay']['effective_view_compose_seconds']}s)"
    )
    print(f"wall_time_speedup_ratio:      {report['wall_time_speedup_ratio']}")
    print(f"pct_cheaper:                  {report['pct_cheaper']}%")
    print(f"proof_kind:                   {report['proof_kind']}")
    print(f"known_limitation:             {report['known_limitation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
