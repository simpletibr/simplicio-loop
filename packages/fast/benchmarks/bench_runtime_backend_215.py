"""Measured Runtime-adapter admission and dispatch overhead, without build steps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from simplicio_fast.runtime_backend import (
    RuntimeArtifact,
    RuntimeBackendError,
    RuntimeFastBackend,
    select_runtime_backend,
)


def _measure(operation, repetitions: int) -> dict[str, object]:
    samples: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        operation()
        samples.append((time.perf_counter_ns() - started) / 1_000)
    ordered = sorted(samples)
    return {
        "repetitions": repetitions,
        "median_us": statistics.median(ordered),
        "p95_us": ordered[max(0, int(repetitions * 0.95) - 1)],
        "raw_us": samples,
    }


def run(
    repetitions: int = 10,
    *,
    runtime_binary: str | None = None,
    runtime_sha256: str | None = None,
    runtime_version: str = "3.5.5",
    runtime_platform: str = "linux-x86_64",
    launcher: tuple[str, ...] = (),
) -> dict[str, object]:
    if repetitions < 10:
        raise ValueError("repetitions must be at least 10")
    fallback = _measure(
        lambda: select_runtime_backend("auto", artifact=None), repetitions
    )
    runtime: dict[str, object]
    if runtime_binary and runtime_sha256:
        artifact = RuntimeArtifact(
            executable=Path(runtime_binary),
            sha256=runtime_sha256,
            version=runtime_version,
            platform=runtime_platform,
        )
        artifact_verification = RuntimeFastBackend(
            artifact, launcher=launcher, required_capabilities=("sha256",)
        ).verify_artifact()
        samples: list[float] = []
        reason: str | None = None
        selected: str | None = None
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            try:
                result = select_runtime_backend(
                    "auto",
                    artifact=artifact,
                    launcher=launcher,
                    required_capabilities=("sha256",),
                )
                selected = result.selected
                reason = result.reason_code
            except RuntimeBackendError as error:
                reason = error.reason_code
            samples.append((time.perf_counter_ns() - started) / 1_000)
        ordered = sorted(samples)
        runtime = {
            "measured": True,
            "selected": selected,
            "reason_code": reason,
            "repetitions": repetitions,
            "median_us": statistics.median(ordered),
            "p95_us": ordered[max(0, int(repetitions * 0.95) - 1)],
            "raw_us": samples,
            "artifact_verification": artifact_verification,
        }
    else:
        runtime = {
            "measured": False,
            "selected": None,
            "reason_code": "RUNTIME_MISSING",
            "repetitions": 0,
            "median_us": None,
            "p95_us": None,
            "raw_us": [],
            "artifact_verification": None,
        }
    return {
        "schema": "simplicio.fast.runtime-backend-benchmark/v1",
        "issue": 215,
        "fallback_selection": fallback,
        "runtime_admission": runtime,
        "tokens": None,
        "tokens_null_reason": "NO_LLM_USED",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--runtime-binary")
    parser.add_argument("--runtime-sha256")
    parser.add_argument("--runtime-version", default="3.5.5")
    parser.add_argument("--runtime-platform", default="linux-x86_64")
    parser.add_argument("--launcher", action="append", default=[])
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.repetitions,
                runtime_binary=args.runtime_binary,
                runtime_sha256=args.runtime_sha256,
                runtime_version=args.runtime_version,
                runtime_platform=args.runtime_platform,
                launcher=tuple(args.launcher),
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
