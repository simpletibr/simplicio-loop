"""Observed cold/warm precompiled resolver cost; no network, LLM, or compilation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import statistics
import tempfile
import time

from simplicio_fast import __version__
from simplicio_fast.native_backend import ABI, RustBackend, resolve_packaged_backend


SCHEMA = "simplicio.fast-native-resolution-benchmark/v1"


def run(repetitions: int = 10) -> dict[str, object]:
    if repetitions < 10:
        raise ValueError("at least ten repetitions are required")
    with tempfile.TemporaryDirectory(
        prefix="simplicio-fast-native-bench-"
    ) as directory:
        root = Path(directory)
        bundle = root / "artifacts/linux-x86_64" / ABI.replace("/", "_")
        bundle.mkdir(parents=True)
        artifact = bundle / "simplicio-fast-native"
        artifact.write_bytes(b"precompiled-fixture" * 4096)
        manifest = {
            "abi": ABI,
            "platform": "linux-x86_64",
            "filename": artifact.name,
            "version": __version__,
            "source_commit": "a" * 40,
            "toolchain": "release-fixture",
            "size": artifact.stat().st_size,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
        (bundle / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        samples: list[float] = []
        selected = []
        for _ in range(repetitions):
            started = time.perf_counter_ns()
            backend, reason = resolve_packaged_backend(
                root, system="linux", machine="x86_64"
            )
            samples.append((time.perf_counter_ns() - started) / 1_000_000)
            selected.append(isinstance(backend, RustBackend) and reason is None)
    return {
        "schema": SCHEMA,
        "issue": 211,
        "repetitions": repetitions,
        "status": "pass" if all(selected) else "fail",
        "cold_resolution_ms": samples[0],
        "warm_resolution_median_ms": statistics.median(samples[1:]),
        "raw_resolution_ms": samples,
        "artifact_execution_ms": None,
        "artifact_execution_reason": "FIXTURE_IS_NOT_EXECUTED",
        "tokens": None,
        "tokens_reason": "NO_LLM_USED",
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, separators=(",", ":")))
