"""Shadow rollout: compare the sync/async pipeline profiles side by side
without ever auto-promoting the candidate (issue #279 plan step 15:
"Shadow rollout: comparar resultado/tempo do perfil candidato sem
promover automaticamente"). See ADR-011 "Nao escopo" -- this closes that
one deferred item, buildable today with no Hub/Runtime dependency.

Design point, load-bearing for the "never auto-promotes" acceptance
criterion: this module is invoked ONLY by the explicit
``simplicio-mapper benchmark shadow-rollout`` CLI verb (see
``simplicio_mapper/cli/_benchmark.py``). It is never wired into
``build_artifacts``/``write_mapping_artifacts``'s normal dispatch, so a
real ``index``/``map``/``scan`` invocation never triggers a shadow run and
is completely unaffected by this module's existence. ``run_shadow_comparison`` always
returns a comparison payload built around the CONFIGURED profile's real
artifacts (the one ``build_artifacts()`` would have produced on its own,
via the existing execution planner); the candidate (the other) profile is
run only to measure and compare, forced via the existing
``SIMPLICIO_MAPPER_EXECUTION_PROFILE`` env var
into an isolated, throwaway temp output directory (same technique
``pipeline_calibration.py::_time_build`` already uses) so it never writes
into the real ``<output_dir>`` and never becomes the value any caller
actually uses. There is no code path in this module that could make the
candidate profile "win" and replace the configured one -- promotion would
require a separate, human/Hub-driven step this module deliberately does
not take.
"""

from __future__ import annotations

import copy
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

#: Schema id for the shadow-comparison artifact written by this module.
SHADOW_SCHEMA = "simplicio.pipeline-shadow/v1"

#: The planner's explicit profile override used for isolated comparison runs.
_ENV_PROFILE = "SIMPLICIO_MAPPER_EXECUTION_PROFILE"

#: Filename written under the target ``output_dir`` (``.simplicio`` by
#: default, matching every other mapper artifact's location).
SHADOW_REPORT_FILENAME = "pipeline-shadow.json"

#: Dict keys whose values are expected to differ across two independent
#: runs (wall-clock timestamps) and therefore excluded from the output-
#: equivalence comparison -- comparing them would always report a
#: (meaningless) diff.
_VOLATILE_KEYS = frozenset({"generated_at"})


def _strip_volatile(value: Any) -> Any:
    """Recursively drop ``_VOLATILE_KEYS`` so two runs taken seconds apart
    can be compared for genuine content equivalence."""
    if isinstance(value, dict):
        return {key: _strip_volatile(val) for key, val in value.items() if key not in _VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _diff_paths(left: Any, right: Any, path: str = "$", limit: int = 20) -> list[str]:
    """Bounded, human-readable list of differing JSON-Pointer-ish paths
    between *left* and *right*. Stops at *limit* entries (a full diff is
    not the point here -- a caller just needs to know equivalence held or
    where it broke)."""
    diffs: list[str] = []

    def _walk(a: Any, b: Any, p: str) -> None:
        if len(diffs) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if len(diffs) >= limit:
                    return
                if key not in a or key not in b:
                    diffs.append(f"{p}.{key} (present on only one side)")
                    continue
                _walk(a[key], b[key], f"{p}.{key}")
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                diffs.append(f"{p} (length {len(a)} != {len(b)})")
                return
            for index, (av, bv) in enumerate(zip(a, b, strict=True)):
                if len(diffs) >= limit:
                    return
                _walk(av, bv, f"{p}[{index}]")
        elif a != b:
            diffs.append(p)

    _walk(left, right, path)
    return diffs


def determine_configured_profile(cwd: str, output_dir: str = ".simplicio") -> str:
    """Which profile (``"sync"``/``"async"``) ``build_artifacts()`` would
    pick right now for *cwd*, without running the pipeline."""
    # Local import: avoids a module-load-time cycle with `emit.py` (which
    # imports `pipeline_calibration` lazily too; same pattern here).
    from .emit import _async_pipeline_min_files, _fast_file_count
    from .execution_planner import plan_execution

    abs_cwd = os.path.abspath(cwd)
    threshold = _async_pipeline_min_files(abs_cwd, output_dir)
    return plan_execution(_fast_file_count(abs_cwd, threshold), threshold).selected_profile


def run_shadow_comparison(
    cwd: str,
    meta: dict | None = None,
    incremental: bool = False,
    output_dir: str = ".simplicio",
) -> dict[str, Any]:
    """Run the configured profile for real, shadow-run the other profile
    for comparison only, and report equivalence/timing. Never promotes the
    candidate: the return value documents which profile was actually used
    (``returned_profile``, always equal to ``configured_profile``) and the
    candidate's artifacts are discarded after the comparison -- no caller
    of ``build_artifacts``/``write_mapping_artifacts`` ever sees them.
    """
    # Local import: same call-time-only dependency-direction reasoning as
    # `pipeline_calibration.py::_time_build`.
    from .emit import build_artifacts

    abs_cwd = os.path.abspath(cwd or os.getcwd())
    configured_profile = determine_configured_profile(abs_cwd, output_dir)
    candidate_profile = "sync" if configured_profile == "async" else "async"

    start = time.perf_counter()
    configured_artifacts = build_artifacts(abs_cwd, meta, incremental, output_dir)
    configured_wall_s = time.perf_counter() - start

    previous_env = os.environ.get(_ENV_PROFILE)
    # Force the other profile for this isolated measurement.
    os.environ[_ENV_PROFILE] = candidate_profile
    try:
        with tempfile.TemporaryDirectory(prefix="pipeline-shadow-out-") as shadow_out_dir:
            start = time.perf_counter()
            candidate_artifacts = build_artifacts(abs_cwd, meta, incremental, shadow_out_dir)
            candidate_wall_s = time.perf_counter() - start
    finally:
        if previous_env is None:
            os.environ.pop(_ENV_PROFILE, None)
        else:
            os.environ[_ENV_PROFILE] = previous_env

    diffs: dict[str, list[str]] = {}
    for key in configured_artifacts:
        if key == "execution_plan":
            continue
        left = _strip_volatile(configured_artifacts[key])
        right = _strip_volatile(candidate_artifacts.get(key))
        path_diffs = _diff_paths(left, right, path=f"${key}")
        if path_diffs:
            diffs[key] = path_diffs

    equivalent_output = not diffs
    if configured_wall_s <= candidate_wall_s:
        faster_profile = configured_profile
    else:
        faster_profile = candidate_profile

    return {
        "schema": SHADOW_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "configured_profile": configured_profile,
        "candidate_profile": candidate_profile,
        "configured_wall_s": round(configured_wall_s, 4),
        "candidate_wall_s": round(candidate_wall_s, 4),
        "faster_profile": faster_profile,
        "equivalent_output": equivalent_output,
        "diffs": diffs,
        # Structural, not just documentary: nothing above this line mutates
        # dispatch state or writes over the real `<output_dir>` artifacts --
        # `returned_profile` records what a real caller actually got.
        "returned_profile": configured_profile,
        "promoted": False,
    }


def write_shadow_report(cwd: str, payload: dict[str, Any], output_dir: str = ".simplicio") -> str:
    """Write *payload* atomically to ``<cwd>/<output_dir>/pipeline-shadow.json``.

    Matches the repo's existing atomic-write convention (tmp file +
    ``os.replace``, see ``emit.py::_write_json_stable`` /
    ``pipeline_calibration.py::write_calibration``) so a reader can never
    observe a partially-written shadow report. This report is a receipt of
    a past comparison run -- it is never read back by ``build_artifacts``'s
    dispatch (unlike ``pipeline-calibration.json``), so writing it can never
    change production behavior.
    """
    import json

    abs_cwd = os.path.abspath(cwd)
    target_dir = os.path.join(abs_cwd, output_dir)
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, SHADOW_REPORT_FILENAME)
    tmp_path = f"{path}.tmp-{os.getpid()}"
    # `payload` is deep-copied before serialization only to keep this
    # function side-effect-free with respect to the caller's dict (JSON
    # serialization itself would not mutate it, but a defensive copy keeps
    # this function's contract obviously safe under future edits).
    safe_payload = copy.deepcopy(payload)
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(safe_payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)
    return path
