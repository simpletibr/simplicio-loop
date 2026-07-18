"""Local, opt-in, machine-specific sync/async pipeline-dispatch calibration
(issue #279 Phase-0 increment; see
``.specs/architecture/ADR-011-adaptive-pipeline-threshold-calibration.md``).

ADR-009's own honest gap: ``simplicio_mapper.mapper.emit.build_artifacts``
routes below/above ``SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES`` (hardcoded
default **600**) based on a single Windows-only measurement
(``scripts/async_pipeline_dispatch_benchmark.py``), with no per-platform or
per-machine tuning. Issue #279 asks for a genuinely adaptive, Hub-governed
threshold; this module is the safe, additive Phase-0 slice of that: a local
one-time calibration a user can run on THEIR machine/filesystem, which
writes a cached override that :func:`simplicio_mapper.mapper.emit
._async_pipeline_min_files` prefers over the hardcoded default -- but ONLY
when present. No calibration file: behavior is byte-for-byte identical to
before this module existed (the hardcoded default, unchanged).

Method (reuses the same measurement shape as
``scripts/async_pipeline_dispatch_benchmark.py``'s crossover table, not its
code -- that script lives outside the installed package and is not a
runtime dependency): at each configured synthetic-tree size, force the
plain synchronous pipeline and the bounded-concurrency async pipeline
explicitly via the existing ``SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES``
env var (bypassing the dispatcher, like-for-like on this revision), time
both, and pick the smallest measured size where async's median wall time
beats sync's as the recommended dispatch threshold for THIS machine. If
async never wins at any measured size, the hardcoded default is kept
(fail-safe: calibration never invents an unmeasured win).

This module never changes ``emit.py``'s existing default behavior on its
own -- it only ever *adds* an optional, explicit opt-in artifact
(``.simplicio/pipeline-calibration.json`` by default) that a caller must
have actively generated via ``simplicio-mapper benchmark pipeline-threshold``
(see ``simplicio_mapper/cli/_benchmark.py``).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Schema id for the calibration artifact written by this module.
CALIBRATION_SCHEMA = "simplicio.pipeline-calibration/v1"

#: Filename written under the target ``output_dir`` (``.simplicio`` by
#: default, matching every other mapper artifact's location).
CALIBRATION_FILENAME = "pipeline-calibration.json"

#: Same env var `simplicio_mapper.mapper.emit` already reads to force the
#: sync/async dispatch explicitly -- reused here, not duplicated, so
#: calibration measures the exact same forcing mechanism production uses.
_ENV_THRESHOLD = "SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES"

#: Default synthetic-tree sizes probed by ``run_calibration`` -- chosen to
#: bracket the shipped hardcoded default (600) without this command itself
#: taking minutes to run on a typical machine.
DEFAULT_CALIBRATION_SIZES: tuple[int, ...] = (200, 600, 1200)

_MIN_VALID_THRESHOLD = 1

_MODULE_TEMPLATE = (
    "\"\"\"Synthetic calibration module {index} (pkg_{group}).\"\"\"\n"
    "import os\n\n\n"
    "def fn_{index}():\n"
    "    return os.path.join('a', 'b_{index}')\n"
)


def calibration_file_path(cwd: str, output_dir: str = ".simplicio") -> str:
    """Absolute path where a calibration artifact for *cwd* would live."""
    abs_cwd = os.path.abspath(cwd)
    return os.path.join(abs_cwd, output_dir, CALIBRATION_FILENAME)


def load_calibrated_threshold(cwd: str, output_dir: str = ".simplicio") -> int | None:
    """Read a previously written calibration file and return its threshold.

    Fail-safe by design: ANY problem reading/parsing/validating the file
    (missing, unreadable, corrupt JSON, wrong/absent schema, non-int or
    non-positive threshold) returns ``None`` silently. Callers MUST treat
    ``None`` as "no calibration available" and fall back to the hardcoded
    default -- this function never raises, and a bad/tampered calibration
    artifact can never break or slow down a mapper run.
    """
    path = calibration_file_path(cwd, output_dir)
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != CALIBRATION_SCHEMA:
        return None
    threshold = payload.get("recommended_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        return None
    if threshold < _MIN_VALID_THRESHOLD:
        return None
    return threshold


def _materialize_tree(root: Path, file_count: int) -> int:
    """Deterministic synthetic Python tree, same shape family as
    ``scripts/async_pipeline_after_benchmark.py``'s generator (grouped
    packages, one module per requested file), kept intentionally smaller/
    simpler here since this only needs to reproduce the sync-vs-async
    crossover signal, not a full benchmark-grade corpus.
    """
    root.mkdir(parents=True, exist_ok=True)
    written = 0
    groups = max(1, file_count // 20)
    for index in range(file_count):
        group = index % groups
        pkg_dir = root / f"pkg_{group}"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        init_path = pkg_dir / "__init__.py"
        if not init_path.exists():
            init_path.write_text("", encoding="utf-8")
            written += 1
        module_path = pkg_dir / f"module_{index}.py"
        module_path.write_text(
            _MODULE_TEMPLATE.format(index=index, group=group), encoding="utf-8"
        )
        written += 1
    return written


def _time_build(source_dir: Path, mode: str) -> float:
    """Time one ``build_artifacts()`` call with the sync/async path forced
    via the existing env-var override, exactly as
    ``scripts/async_pipeline_dispatch_benchmark.py`` already does for its
    crossover table -- forcing (not the size-based dispatcher) is required
    here so each mode is measured deterministically regardless of where the
    hardcoded default currently sits.
    """
    # Local import: avoids a module-load-time cycle with `emit.py` (which
    # imports this module lazily too, see `emit._async_pipeline_min_files`).
    from .emit import build_artifacts

    previous = os.environ.get(_ENV_THRESHOLD)
    os.environ[_ENV_THRESHOLD] = "999999999" if mode == "sync" else "1"
    try:
        with tempfile.TemporaryDirectory(prefix="pipeline-calibration-out-") as out_dir:
            start = time.perf_counter()
            build_artifacts(str(source_dir), meta={}, incremental=False, output_dir=out_dir)
            return time.perf_counter() - start
    finally:
        if previous is None:
            os.environ.pop(_ENV_THRESHOLD, None)
        else:
            os.environ[_ENV_THRESHOLD] = previous


def run_calibration(
    sizes: tuple[int, ...] = DEFAULT_CALIBRATION_SIZES,
    runs: int = 1,
    default_threshold: int = 600,
) -> dict[str, Any]:
    """Measure this machine's real sync-vs-async pipeline crossover.

    Returns the calibration payload (not yet written to disk -- see
    :func:`write_calibration`). Never mutates any existing
    ``SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES`` the caller had set
    (restored in a ``finally`` per measurement).
    """
    runs = max(1, int(runs))
    measurements: list[dict[str, Any]] = []
    crossover: int | None = None
    with tempfile.TemporaryDirectory(prefix="pipeline-calibration-src-") as tmp:
        for size in sorted(set(int(s) for s in sizes if int(s) > 0)):
            source_dir = Path(tmp) / f"tree-{size}"
            written = _materialize_tree(source_dir, size)
            sync_times = [_time_build(source_dir, "sync") for _ in range(runs)]
            async_times = [_time_build(source_dir, "async") for _ in range(runs)]
            sync_median = statistics.median(sync_times)
            async_median = statistics.median(async_times)
            row = {
                "requested_file_count": size,
                "actual_file_count": written,
                "sync_wall_median_s": round(sync_median, 4),
                "async_wall_median_s": round(async_median, 4),
                "async_faster": async_median < sync_median,
            }
            measurements.append(row)
            if crossover is None and row["async_faster"]:
                crossover = written
            shutil.rmtree(source_dir, ignore_errors=True)

    recommended = crossover if crossover is not None else default_threshold
    return {
        "schema": CALIBRATION_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "sizes_measured": measurements,
        "recommended_threshold": recommended,
        "hardcoded_default_threshold": default_threshold,
        "calibrated": crossover is not None,
        "method": (
            "Forces the sync (_build_artifacts_sync) and async "
            "(async_pipeline.build_artifacts_async) dispatch paths "
            "explicitly via SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES, "
            "measured against synthetic Python trees at each configured "
            "size on this machine/filesystem, then picks the smallest "
            "measured size where async's median wall time beats sync's as "
            "the recommended dispatch threshold. Falls back to the "
            "hardcoded default (unchanged behavior) if async never wins at "
            "any measured size -- see 'calibrated': false in that case."
        ),
    }


def write_calibration(
    cwd: str, payload: dict[str, Any], output_dir: str = ".simplicio"
) -> str:
    """Write *payload* atomically to ``<cwd>/<output_dir>/pipeline-calibration.json``.

    Matches the repo's existing atomic-write convention (tmp file +
    ``os.replace``, see ``emit.py::_write_json_stable``) so a reader can
    never observe a partially-written calibration artifact.
    """
    abs_cwd = os.path.abspath(cwd)
    target_dir = os.path.join(abs_cwd, output_dir)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, CALIBRATION_FILENAME)
    tmp_path = f"{path}.tmp-{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)
    return path
