#!/usr/bin/env python3
"""Local, hash-bound performance evidence and regression gate for Mapper."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.mapper-perf-evidence/v1"
MIN_SAMPLES = 10


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = (len(ordered) - 1) * percentile / 100
    lower, upper = int(index), min(int(index) + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def source_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    value = (result.stdout or "").strip()
    return value or None


def build_evidence(*, root: str | Path, corpus: Mapping[str, Any], profile: str,
                   phase: str, samples: Sequence[Mapping[str, Any]],
                   fingerprint: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a receipt; unavailable metrics remain null with a reason."""
    rows = [dict(sample) for sample in samples]
    wall = [float(row["wall_ms"]) for row in rows if row.get("wall_ms") is not None]
    measured = {"wall_ms": {"p50": _percentile(wall, 50), "p95": _percentile(wall, 95),
                             "samples": len(wall)} if wall else None}
    payload = {"schema": SCHEMA, "profile": profile, "phase": phase,
               "corpus": dict(corpus), "fingerprint": dict(fingerprint or {}),
               "source_commit": source_commit(Path(root).resolve()),
               "environment": {"python": platform.python_version(), "platform": platform.platform()},
               "samples": rows, "metrics": measured,
               "optional_metrics": {"cpu_ms": None, "peak_rss_bytes": None, "read_bytes": None,
                                    "write_bytes": None, "cache_hits": None, "cache_misses": None,
                                    "unavailable_reason": "caller did not provide isolated counters"}}
    payload["evidence_hash"] = _hash(payload)
    return payload


def compare(baseline: Mapping[str, Any], candidate: Mapping[str, Any], *, p50_limit: float = 0.05,
            p95_limit: float = 0.10) -> dict[str, Any]:
    """Reject incompatible, under-sampled, or regressed evidence."""
    base_fp = baseline.get("fingerprint") or {}
    candidate_fp = candidate.get("fingerprint") or {}
    compatible = all(candidate_fp.get(key) == value for key, value in base_fp.items())
    base_metrics, candidate_metrics = baseline.get("metrics") or {}, candidate.get("metrics") or {}
    checks = []
    for percentile, limit in (("p50", p50_limit), ("p95", p95_limit)):
        base_value = (base_metrics.get("wall_ms") or {}).get(percentile)
        candidate_value = (candidate_metrics.get("wall_ms") or {}).get(percentile)
        base_samples = int((base_metrics.get("wall_ms") or {}).get("samples") or 0)
        candidate_samples = int((candidate_metrics.get("wall_ms") or {}).get("samples") or 0)
        if base_value in (None, 0) or candidate_value is None:
            checks.append({"metric": f"wall_ms.{percentile}", "status": "fail",
                           "unavailable_reason": "compatible sample is missing"})
            continue
        if base_samples < MIN_SAMPLES or candidate_samples < MIN_SAMPLES:
            checks.append({"metric": f"wall_ms.{percentile}", "status": "fail",
                           "unavailable_reason": f"at least {MIN_SAMPLES} samples required",
                           "baseline_samples": base_samples, "candidate_samples": candidate_samples})
            continue
        ratio = float(candidate_value) / float(base_value)
        checks.append({"metric": f"wall_ms.{percentile}", "baseline": base_value,
                       "candidate": candidate_value, "ratio": ratio, "limit": limit,
                       "status": "pass" if ratio <= 1 + limit else "fail"})
    return {"schema": "simplicio.mapper-perf-gate/v1", "compatible": compatible,
            "status": "pass" if compatible and all(row["status"] != "fail" for row in checks) else "fail",
            "checks": checks, "baseline_hash": baseline.get("evidence_hash"),
            "candidate_hash": candidate.get("evidence_hash")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args(argv)
    report = compare(json.loads(args.baseline.read_text(encoding="utf-8")),
                     json.loads(args.candidate.read_text(encoding="utf-8")))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
