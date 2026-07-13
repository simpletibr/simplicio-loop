#!/usr/bin/env python3
"""Warm runtime-scale benchmark for indexed retrieval vs legacy metadata selection.

The checked-in fixture is intentionally compact: it stores a deterministic
manifest, then materializes a ~5000-file synthetic/reference-scale tree in a
temporary directory for the real benchmark run. The indexed path measures the
warm query flow backed by ``retrieval-index.json``; the legacy comparator uses
the same metadata artifacts but ranks without the retrieval index so we can
compare calibrated warm-query cost honestly without touching production code.
"""

from __future__ import annotations

import argparse
import builtins
import io
import json
import os
import random
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_mapper import retrieval_index as ri  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "runtime-scale"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
SCHEMA = "simplicio.runtime-scale-benchmark/v1"


@dataclass(frozen=True)
class HotFile:
    path: str
    language: str
    roles: list[str]
    importance: float
    symbol: str
    exports: list[str]
    imports: list[str]
    body: str


@dataclass(frozen=True)
class QuerySpec:
    name: str
    goal: str
    target: str = ""


@dataclass(frozen=True)
class BenchmarkTargets:
    indexed_p95_ms: float
    indexed_vs_legacy_speedup_ratio: float


@dataclass(frozen=True)
class FixtureSpec:
    schema: str
    seed: int
    total_files: int
    measured_runs: int
    warmup_runs: int
    limit: int
    token_budget: int
    targets: BenchmarkTargets
    hot_files: list[HotFile]
    queries: list[QuerySpec]

    def with_overrides(self, **overrides: Any) -> FixtureSpec:
        payload = asdict(self)
        payload.update(overrides)
        if "targets" in overrides and isinstance(overrides["targets"], Mapping):
            payload["targets"] = {**asdict(self.targets), **dict(overrides["targets"])}
        return fixture_spec_from_dict(payload)


def fixture_spec_from_dict(payload: Mapping[str, Any]) -> FixtureSpec:
    return FixtureSpec(
        schema=str(payload["schema"]),
        seed=int(payload["seed"]),
        total_files=int(payload["total_files"]),
        measured_runs=int(payload["measured_runs"]),
        warmup_runs=int(payload["warmup_runs"]),
        limit=int(payload["limit"]),
        token_budget=int(payload["token_budget"]),
        targets=BenchmarkTargets(
            indexed_p95_ms=float(payload["targets"]["indexed_p95_ms"]),
            indexed_vs_legacy_speedup_ratio=float(payload["targets"]["indexed_vs_legacy_speedup_ratio"]),
        ),
        hot_files=[HotFile(**dict(item)) for item in payload["hot_files"]],
        queries=[QuerySpec(**dict(item)) for item in payload["queries"]],
    )


def load_fixture_spec(path: Path = MANIFEST_PATH) -> FixtureSpec:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return fixture_spec_from_dict(payload)


def _language_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".js": "javascript",
        ".md": "markdown",
        ".json": "json",
    }.get(suffix, "text")


def _role_for_path(path: str) -> list[str]:
    normalized = path.replace("\\", "/")
    if normalized.startswith("tests/"):
        return ["test"]
    if normalized.startswith("docs/"):
        return ["docs"]
    return ["domain"]


def _symbol_for_path(path: str, ordinal: int) -> str:
    stem = Path(path).stem
    parts = [piece.capitalize() for piece in stem.replace("-", "_").split("_") if piece]
    return "".join(parts) or f"GeneratedSymbol{ordinal}"


def _generated_body(path: str, ordinal: int, group: int) -> str:
    normalized = path.replace("\\", "/")
    if normalized.endswith(".py"):
        symbol = _symbol_for_path(path, ordinal)
        return (
            f"def generated_runtime_scale_{ordinal}(budget: int) -> int:\n"
            f"    \"\"\"Synthetic runtime scale file {ordinal} in group {group}.\"\"\"\n"
            f"    return budget + {ordinal % 17}\n\n"
            f"class {symbol}:\n"
            f"    def render(self) -> str:\n"
            f"        return \"runtime-scale-{group}-{ordinal}\"\n"
        )
    if normalized.endswith(".ts"):
        return (
            f"export function generatedRuntimeScale{ordinal}(budget: number): number {{\n"
            f"  return budget + {ordinal % 13};\n"
            "}\n"
        )
    if normalized.endswith(".md"):
        return f"# Runtime scale note {ordinal}\n\nSynthetic documentation shard {group}.\n"
    return json.dumps({"generated": ordinal, "group": group}, sort_keys=True)


def _generated_path(ordinal: int) -> str:
    group = ordinal % 40
    lane = ordinal % 7
    if ordinal % 19 == 0:
        return f"tests/generated/group_{group:02d}/test_runtime_scale_{ordinal:04d}.py"
    if ordinal % 23 == 0:
        return f"docs/generated/group_{group:02d}/runtime_scale_{ordinal:04d}.md"
    if ordinal % 29 == 0:
        return f"src/generated/group_{group:02d}/runtime_scale_{ordinal:04d}.ts"
    return f"src/generated/group_{group:02d}/lane_{lane}/runtime_scale_{ordinal:04d}.py"


def _write_file(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def generate_runtime_scale_corpus(root: Path, spec: FixtureSpec) -> dict[str, Any]:
    random.seed(spec.seed)
    root = root.resolve()
    hot_paths = {item.path for item in spec.hot_files}
    entries: list[dict[str, Any]] = []
    symbol_entries: list[dict[str, Any]] = []
    call_edges: list[dict[str, str]] = []

    for hot in spec.hot_files:
        destination = root / hot.path
        _write_file(destination, hot.body)
        size_bytes = destination.stat().st_size
        entries.append(
            {
                "path": hot.path,
                "roles": hot.roles,
                "importance": hot.importance,
                "language": hot.language,
                "size_bytes": size_bytes,
                "imports": hot.imports,
                "exports": hot.exports,
            }
        )
        line_count = len(destination.read_text(encoding="utf-8").splitlines()) or 1
        symbol_entries.append(
            {
                "defined_in": hot.path,
                "name": hot.symbol,
                "kind": "class" if "class " in hot.body else "function",
                "line": 1,
                "end_line": line_count,
                "qualified_name": f"{hot.path}::{hot.symbol}",
            }
        )

    generated_needed = max(0, spec.total_files - len(spec.hot_files))
    for ordinal in range(generated_needed):
        path = _generated_path(ordinal)
        if path in hot_paths:
            path = f"src/generated/collisions/runtime_scale_{ordinal:04d}.py"
        destination = root / path
        group = ordinal % 40
        body = _generated_body(path, ordinal, group)
        _write_file(destination, body)
        size_bytes = destination.stat().st_size
        language = _language_for_path(path)
        roles = _role_for_path(path)
        symbol = _symbol_for_path(path, ordinal)
        entries.append(
            {
                "path": path,
                "roles": roles,
                "importance": round(0.12 + ((ordinal % 9) * 0.01), 3),
                "language": language,
                "size_bytes": size_bytes,
                "imports": ["runtime_scale"] if language == "python" and "src/" in path else [],
                "exports": [symbol] if language in {"python", "typescript", "javascript"} else [],
            }
        )
        if language in {"python", "typescript", "javascript"}:
            line_count = len(body.splitlines()) or 1
            symbol_entries.append(
                {
                    "defined_in": path,
                    "name": symbol,
                    "kind": "function" if "def " in body or "function " in body else "class",
                    "line": 1,
                    "end_line": line_count,
                    "qualified_name": f"{path}::{symbol}",
                }
            )

    call_edges.extend(
        [
            {
                "from": "tests/test_runtime_scale_budget.py",
                "to": "src/runtime_scale/indexed_dispatch.py",
            },
            {
                "from": "src/runtime_scale/legacy_metadata.py",
                "to": "src/runtime_scale/indexed_dispatch.py",
            },
        ]
    )

    entries.sort(key=lambda item: str(item["path"]))
    symbol_entries.sort(key=lambda item: (str(item["defined_in"]), str(item["name"])))
    project_map = {
        "schema": "simplicio.project-map/v1",
        "files": entries,
        "recent_changes": [{"path": "src/runtime_scale/indexed_dispatch.py", "status": "modified"}],
    }
    symbol_index = {
        "schema": "simplicio.symbol-index/v1",
        "symbols": symbol_entries,
    }
    call_graph = {
        "schema": "simplicio.call-graph/v1",
        "edges": call_edges,
    }

    artifact_root = root / ".simplicio"
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "project-map.json").write_text(json.dumps(project_map, ensure_ascii=False), encoding="utf-8")
    (artifact_root / "symbol-index.json").write_text(json.dumps(symbol_index, ensure_ascii=False), encoding="utf-8")
    (artifact_root / "call-graph.json").write_text(json.dumps(call_graph, ensure_ascii=False), encoding="utf-8")

    retrieval_index = ri.build_retrieval_index(
        project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        root=str(root),
    )
    retrieval_index_path = Path(ri.write_retrieval_index(str(root), ".simplicio", retrieval_index))
    return {
        "root": str(root),
        "project_map": project_map,
        "symbol_index": symbol_index,
        "call_graph": call_graph,
        "retrieval_index_path": str(retrieval_index_path),
        "file_count": len(entries),
        "symbol_count": len(symbol_entries),
    }


class _CountingReader:
    def __init__(self, handle: Any, metrics: dict[str, Any], path: str) -> None:
        self._handle = handle
        self._metrics = metrics
        self._path = path

    def _tally(self, payload: Any) -> Any:
        if payload is None:
            return payload
        if isinstance(payload, str):
            amount = len(payload.encode("utf-8", errors="replace"))
        elif isinstance(payload, bytes):
            amount = len(payload)
        elif isinstance(payload, list):
            amount = sum(
                len(item.encode("utf-8", errors="replace")) if isinstance(item, str) else len(item)
                for item in payload
            )
        else:
            return payload
        self._metrics["bytes_read"] += amount
        self._metrics["paths"].add(self._path)
        return payload

    def read(self, *args: Any, **kwargs: Any) -> Any:
        return self._tally(self._handle.read(*args, **kwargs))

    def readline(self, *args: Any, **kwargs: Any) -> Any:
        return self._tally(self._handle.readline(*args, **kwargs))

    def readlines(self, *args: Any, **kwargs: Any) -> Any:
        return self._tally(self._handle.readlines(*args, **kwargs))

    def __iter__(self) -> Any:
        for item in self._handle:
            yield self._tally(item)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)

    def __enter__(self) -> _CountingReader:
        self._handle.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        return self._handle.__exit__(exc_type, exc, tb)


class FileOpenMeter:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.metrics: dict[str, Any] = {
            "open_calls": 0,
            "bytes_read": 0,
            "paths": set(),
        }
        self._orig_builtin = builtins.open
        self._orig_io = io.open

    def _wrap(self, opener: Callable[..., Any], file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        handle = opener(file, mode, *args, **kwargs)
        try:
            path = Path(file).resolve()
        except TypeError:
            return handle
        if "r" not in mode:
            return handle
        try:
            inside = os.path.commonpath([str(self.root), str(path)]) == str(self.root)
        except ValueError:
            inside = False
        if not inside:
            return handle
        self.metrics["open_calls"] += 1
        self.metrics["paths"].add(str(path))
        return _CountingReader(handle, self.metrics, str(path))

    def __enter__(self) -> FileOpenMeter:
        builtins.open = lambda file, mode="r", *args, **kwargs: self._wrap(  # type: ignore[assignment]
            self._orig_builtin, file, mode, *args, **kwargs
        )
        io.open = lambda file, mode="r", *args, **kwargs: self._wrap(  # type: ignore[assignment]
            self._orig_io, file, mode, *args, **kwargs
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        builtins.open = self._orig_builtin  # type: ignore[assignment]
        io.open = self._orig_io  # type: ignore[assignment]

    def snapshot(self) -> dict[str, int]:
        return {
            "open_calls": int(self.metrics["open_calls"]),
            "unique_files_opened": len(self.metrics["paths"]),
            "bytes_read": int(self.metrics["bytes_read"]),
        }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _legacy_metadata_query(
    root: Path,
    query: QuerySpec,
    *,
    limit: int,
    token_budget: int,
) -> dict[str, Any]:
    artifact_root = root / ".simplicio"
    project_map = _load_json(artifact_root / "project-map.json")
    symbol_index = _load_json(artifact_root / "symbol-index.json")
    plan = ri.build_query_plan(query.goal, target=query.target)
    symbol_map: dict[str, list[str]] = {}
    for symbol in symbol_index.get("symbols", []):
        if not isinstance(symbol, Mapping):
            continue
        symbol_map.setdefault(str(symbol.get("defined_in", "")), []).append(str(symbol.get("name", "")))
    candidates: list[dict[str, Any]] = []
    exact_terms = {term.lower() for term in plan.exact_identifiers}
    path_terms = {term.lower() for term in plan.path_terms + plan.domain_terms}
    symbol_terms = {term.lower() for term in plan.symbol_terms}
    target = query.target.replace("\\", "/")
    for entry in project_map.get("files", []):
        if not isinstance(entry, Mapping):
            continue
        path = str(entry.get("path", "")).replace("\\", "/")
        score = 0.0
        matched: set[str] = set()
        if target and path == target:
            score += 20.0
            matched.update({target, *plan.path_terms})
        path_tokens = set(ri.tokenize(path))
        for term in path_terms:
            if term in path_tokens:
                score += 1.1
                matched.add(term)
        symbols = symbol_map.get(path, [])
        for symbol in symbols:
            lowered = symbol.lower()
            if lowered in symbol_terms:
                score += 6.0
                matched.add(symbol)
            if lowered in exact_terms:
                score += 3.0
                matched.add(symbol)
        if score <= 0:
            continue
        candidates.append(
            {
                "path": path,
                "relevance_score": round(score + float(entry.get("importance", 0.0) or 0.0), 6),
                "matched_terms": sorted(matched),
                "reason_codes": ["legacy_metadata_overlap"],
                "roles": list(entry.get("roles", [])),
                "language": str(entry.get("language", "")),
            }
        )
    candidates.sort(key=lambda row: (-row["relevance_score"], row["path"]))
    candidates = candidates[:limit]
    payload = {
        "schema": "simplicio.runtime-scale-legacy-selection/v1",
        "query_terms": plan.all_terms,
        "targets": [
            {
                "path": row["path"],
                "relevance_score": row["relevance_score"],
                "matched_terms": row["matched_terms"],
                "reason_codes": row["reason_codes"],
            }
            for row in candidates
        ],
        "token_budget_fit": {
            "token_budget": token_budget,
            "estimated_tokens": ri.estimate_tokens(
                json.dumps(candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            ),
            "tokenizer_policy": ri.TOKENIZER_POLICY,
        },
    }
    return payload


def _indexed_query(
    root: Path,
    query: QuerySpec,
    *,
    limit: int,
    token_budget: int,
) -> dict[str, Any]:
    artifact_root = root / ".simplicio"
    project_map = _load_json(artifact_root / "project-map.json")
    symbol_index = _load_json(artifact_root / "symbol-index.json")
    call_graph = _load_json(artifact_root / "call-graph.json")
    retrieval_index = ri.load_retrieval_index(str(root))
    if retrieval_index is None:
        raise RuntimeError("retrieval-index.json missing")
    return ri.select_context_targets(
        str(root),
        project_map,
        goal=query.goal,
        target=query.target,
        limit=limit,
        symbol_index=symbol_index,
        call_graph=call_graph,
        retrieval_index=retrieval_index,
        token_budget=token_budget,
    )


def _percentile95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    return float(statistics.quantiles(values, n=100, method="inclusive")[94])


def _series_summary(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    durations = [float(item["duration_ms"]) for item in samples]
    files_opened = [float(item["unique_files_opened"]) for item in samples]
    bytes_read = [float(item["bytes_read"]) for item in samples]
    result_tokens = [float(item["result_tokens"]) for item in samples]
    return {
        "runs": len(samples),
        "duration_ms": {
            "mean": round(statistics.fmean(durations), 3),
            "p95": round(_percentile95(durations), 3),
            "min": round(min(durations), 3),
            "max": round(max(durations), 3),
        },
        "files_opened": {
            "mean": round(statistics.fmean(files_opened), 3),
            "p95": round(_percentile95(files_opened), 3),
            "total": int(sum(files_opened)),
        },
        "bytes_read": {
            "mean": round(statistics.fmean(bytes_read), 3),
            "p95": round(_percentile95(bytes_read), 3),
            "total": int(sum(bytes_read)),
        },
        "result_tokens": {
            "mean": round(statistics.fmean(result_tokens), 3),
            "p95": round(_percentile95(result_tokens), 3),
            "total": int(sum(result_tokens)),
        },
        "top_targets": [
            item.get("top_target", "")
            for item in samples[:3]
        ],
    }


def _measure_path(
    root: Path,
    spec: FixtureSpec,
    query: QuerySpec,
    selector: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    total_runs = spec.warmup_runs + spec.measured_runs
    for run_index in range(total_runs):
        with FileOpenMeter(root) as meter:
            start = time.perf_counter()
            payload = selector(root, query, limit=spec.limit, token_budget=spec.token_budget)
            duration_ms = (time.perf_counter() - start) * 1000.0
        metrics = meter.snapshot()
        tokens = ri.estimate_tokens(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        targets = payload.get("targets", [])
        top_target = str(targets[0]["path"]) if targets else ""
        sample = {
            "duration_ms": duration_ms,
            "open_calls": metrics["open_calls"],
            "unique_files_opened": metrics["unique_files_opened"],
            "bytes_read": metrics["bytes_read"],
            "result_tokens": tokens,
            "top_target": top_target,
        }
        if run_index >= spec.warmup_runs:
            samples.append(sample)
    return _series_summary(samples)


def _calibrated_status(indexed: Mapping[str, Any], legacy: Mapping[str, Any], targets: BenchmarkTargets) -> dict[str, Any]:
    indexed_p95 = float(indexed["duration_ms"]["p95"])
    legacy_p95 = float(legacy["duration_ms"]["p95"])
    speedup_ratio = (legacy_p95 / indexed_p95) if indexed_p95 > 0 else 0.0
    normalized_budget = {
        "indexed_p95_vs_target": round(indexed_p95 / targets.indexed_p95_ms, 6) if targets.indexed_p95_ms else 0.0,
        "speedup_vs_target": round(speedup_ratio / targets.indexed_vs_legacy_speedup_ratio, 6)
        if targets.indexed_vs_legacy_speedup_ratio
        else 0.0,
    }
    meets_absolute = indexed_p95 <= targets.indexed_p95_ms
    meets_relative = speedup_ratio >= targets.indexed_vs_legacy_speedup_ratio
    status = "MEASURED" if meets_absolute and meets_relative else "UNVERIFIED"
    reasons: list[str] = []
    if not meets_absolute:
        reasons.append(
            f"indexed p95 {indexed_p95:.3f}ms exceeds target {targets.indexed_p95_ms:.3f}ms"
        )
    if not meets_relative:
        reasons.append(
            f"legacy/indexed speedup {speedup_ratio:.3f}x below target {targets.indexed_vs_legacy_speedup_ratio:.3f}x"
        )
    return {
        "status": status,
        "indexed_p95_ms": round(indexed_p95, 3),
        "legacy_p95_ms": round(legacy_p95, 3),
        "indexed_vs_legacy_speedup_ratio": round(speedup_ratio, 6),
        "normalized_budget": normalized_budget,
        "reasons": reasons,
    }


def run_runtime_scale_benchmark(
    spec: FixtureSpec,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    cleanup: tempfile.TemporaryDirectory[str] | None = None
    if root is None:
        cleanup = tempfile.TemporaryDirectory(prefix="simplicio-runtime-scale-")
        root_path = Path(cleanup.name)
    else:
        root_path = root.resolve()
        root_path.mkdir(parents=True, exist_ok=True)
    try:
        corpus = generate_runtime_scale_corpus(root_path, spec)
        indexed_queries: list[dict[str, Any]] = []
        legacy_queries: list[dict[str, Any]] = []
        for query in spec.queries:
            indexed_summary = _measure_path(root_path, spec, query, _indexed_query)
            legacy_summary = _measure_path(root_path, spec, query, _legacy_metadata_query)
            indexed_queries.append({"name": query.name, **indexed_summary})
            legacy_queries.append({"name": query.name, **legacy_summary})

        indexed_aggregate = _series_summary(
            [
                {
                    "duration_ms": q["duration_ms"]["p95"],
                    "unique_files_opened": q["files_opened"]["p95"],
                    "bytes_read": q["bytes_read"]["p95"],
                    "result_tokens": q["result_tokens"]["p95"],
                    "top_target": q["top_targets"][0] if q.get("top_targets") else "",
                }
                for q in indexed_queries
            ]
        )
        legacy_aggregate = _series_summary(
            [
                {
                    "duration_ms": q["duration_ms"]["p95"],
                    "unique_files_opened": q["files_opened"]["p95"],
                    "bytes_read": q["bytes_read"]["p95"],
                    "result_tokens": q["result_tokens"]["p95"],
                    "top_target": q["top_targets"][0] if q.get("top_targets") else "",
                }
                for q in legacy_queries
            ]
        )
        calibration = _calibrated_status(indexed_aggregate, legacy_aggregate, spec.targets)
        return {
            "schema": SCHEMA,
            "fixture": {
                "manifest": str(MANIFEST_PATH.relative_to(ROOT)).replace("\\", "/"),
                "root": str(root_path),
                "file_count": corpus["file_count"],
                "symbol_count": corpus["symbol_count"],
                "retrieval_index_path": corpus["retrieval_index_path"],
            },
            "queries": [asdict(query) for query in spec.queries],
            "indexed": {
                "per_query": indexed_queries,
                "aggregate": indexed_aggregate,
            },
            "legacy_metadata": {
                "per_query": legacy_queries,
                "aggregate": legacy_aggregate,
            },
            "calibration": calibration,
        }
    finally:
        if cleanup is not None:
            cleanup.cleanup()


def _format_text_report(payload: Mapping[str, Any]) -> str:
    calibration = payload["calibration"]
    indexed = payload["indexed"]["aggregate"]
    legacy = payload["legacy_metadata"]["aggregate"]
    return "\n".join(
        [
            f"status={calibration['status']}",
            f"indexed_p95_ms={calibration['indexed_p95_ms']}",
            f"legacy_p95_ms={calibration['legacy_p95_ms']}",
            f"indexed_vs_legacy_speedup_ratio={calibration['indexed_vs_legacy_speedup_ratio']}",
            f"indexed_files_opened_p95={indexed['files_opened']['p95']}",
            f"legacy_files_opened_p95={legacy['files_opened']['p95']}",
            f"indexed_bytes_read_p95={indexed['bytes_read']['p95']}",
            f"legacy_bytes_read_p95={legacy['bytes_read']['p95']}",
            f"indexed_result_tokens_p95={indexed['result_tokens']['p95']}",
            f"legacy_result_tokens_p95={legacy['result_tokens']['p95']}",
            f"normalized_budget={json.dumps(calibration['normalized_budget'], sort_keys=True)}",
            f"reasons={'; '.join(calibration['reasons']) if calibration['reasons'] else 'none'}",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of the compact text report.")
    parser.add_argument("--root", type=Path, help="Optional persistent root for the generated corpus.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    spec = load_fixture_spec(args.manifest)
    payload = run_runtime_scale_benchmark(spec, root=args.root)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format_text_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
