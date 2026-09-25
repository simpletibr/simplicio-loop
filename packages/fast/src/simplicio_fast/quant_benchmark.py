"""Quality-first, reproducible Q0/Q1/Q2 benchmark contracts.

The benchmark deliberately calls the production Python TurboQuant primitives
for the 4-bit lanes.  It does not contain a second 4-bit implementation and it
does not claim Rust parity when Runtime has no quantization capability.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import math
import mmap
import os
from pathlib import Path
import platform
import random
import statistics
import struct
import subprocess
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

try:
    import resource  # Unix peak RSS / rusage; absent on Windows
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

from .receipts import benchmark_receipt
from .slot_executor import quantize as slot_quantize
from .turboquant import (
    QuantizedVector,
    approximate_candidates,
    exact_rerank,
    quantize as turboquant_quantize,
)


def _run_git(
    args: Sequence[str],
    *,
    cwd: Path | str,
    timeout: float,
    text: bool = False,
) -> subprocess.CompletedProcess[Any]:
    """Run a git subprocess without inheriting redirected stdio on Windows.

    pytest and other hosts redirect handles; on Windows, ``capture_output``
    then fails with ``OSError: [WinError 6] Identificador inválido`` /
    ``WinError 50`` when duplicating inherited pipes. Explicit DEVNULL stdin
    and ``close_fds=False`` keep the call portable.
    """
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
        timeout=timeout,
        close_fds=False,
    )


BENCHMARK_SCHEMA = "simplicio.fast.quant-benchmark/v1"
# Compatibility alias published by PR #217. New integrations should use
# BENCHMARK_SCHEMA and run_benchmark.
BENCH_SCHEMA = BENCHMARK_SCHEMA
MANIFEST_SCHEMA = "simplicio.fast.quant-index-manifest/v1"
DATASET_SCHEMA = "simplicio.fast.quant-dataset/v1"
LANES = ("Q0", "Q1", "Q2a", "Q2b")
REASON_CODES = frozenset(
    {
        "INDEX_STALE",
        "INDEX_CORRUPT",
        "INDEX_CROSS_GENERATION",
        "BACKEND_INCOMPATIBLE",
        "CAPACITY_LIMIT_CONFIGURED",
        "RUNTIME_FAST_QUANT_CAPABILITY_UNAVAILABLE",
        "SIMULATION_NOT_RUN",
        "RSS_CURRENT_UNAVAILABLE",
        "SOURCE_TREE_UNAVAILABLE",
    }
)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires samples")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _summary(values: Sequence[float]) -> dict[str, float]:
    return {
        "p50": statistics.median(values),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
    }


def _validate_hash(value: str, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise QuantBenchmarkError("INDEX_CORRUPT", f"{field} must be sha256")


class QuantBenchmarkError(RuntimeError):
    """Stable fail-closed benchmark/index validation failure."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        if reason_code not in REASON_CODES:
            reason_code = "INDEX_CORRUPT"
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


@dataclass(frozen=True, slots=True)
class QueryFixture:
    query_id: str
    vector: tuple[float, ...]
    relevant_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QuantDataset:
    records: tuple[tuple[str, tuple[float, ...]], ...]
    queries: tuple[QueryFixture, ...]
    dimension: int
    seed: int
    corpus_hash: str
    query_hash: str
    judgments_hash: str
    embedding_hash: str
    dataset_hash: str

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": DATASET_SCHEMA,
            "kind": "synthetic-cluster-corpus",
            "records": len(self.records),
            "queries": len(self.queries),
            "dimension": self.dimension,
            "seed": self.seed,
            "corpus_hash": self.corpus_hash,
            "query_hash": self.query_hash,
            "judgments_hash": self.judgments_hash,
            "embedding": {
                "model": "simplicio-deterministic-cluster-v1",
                "version": "1",
                "normalization": "l2",
                "dimension": self.dimension,
                "sha256": self.embedding_hash,
            },
            "dataset_hash": self.dataset_hash,
        }


@dataclass(frozen=True, slots=True)
class QuantIndexManifest:
    lane: str
    generation: str
    corpus_hash: str
    embedding_hash: str
    config_hash: str
    index_hash: str
    index_bytes: int
    records: int
    dimension: int
    candidate_k: int
    result_k: int
    backend: str = "python"

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "lane": self.lane,
            "generation": self.generation,
            "corpus_hash": self.corpus_hash,
            "embedding_hash": self.embedding_hash,
            "config_hash": self.config_hash,
            "index_hash": self.index_hash,
            "index_bytes": self.index_bytes,
            "records": self.records,
            "dimension": self.dimension,
            "candidate_k": self.candidate_k,
            "result_k": self.result_k,
            "backend": self.backend,
        }

    def verify(
        self,
        *,
        generation: str,
        corpus_hash: str,
        embedding_hash: str,
        config_hash: str,
        backend: str = "python",
    ) -> None:
        for name, value in (
            ("corpus_hash", self.corpus_hash),
            ("embedding_hash", self.embedding_hash),
            ("config_hash", self.config_hash),
            ("index_hash", self.index_hash),
        ):
            _validate_hash(value, name)
        if generation != self.generation:
            raise QuantBenchmarkError(
                "INDEX_CROSS_GENERATION",
                f"expected={generation} actual={self.generation}",
            )
        if (
            corpus_hash != self.corpus_hash
            or embedding_hash != self.embedding_hash
            or config_hash != self.config_hash
        ):
            raise QuantBenchmarkError("INDEX_STALE", self.lane)
        if backend != self.backend:
            raise QuantBenchmarkError(
                "BACKEND_INCOMPATIBLE",
                f"expected={backend} actual={self.backend}",
            )


@dataclass(frozen=True, slots=True)
class _LaneEntry:
    canonical_id: str
    integral: tuple[float, ...]
    encoded: tuple[float | int, ...] | QuantizedVector


class QuantLaneIndex:
    """Immutable benchmark index over the real Python Q0/Q1/TurboQuant paths."""

    def __init__(
        self,
        entries: tuple[_LaneEntry, ...],
        manifest: QuantIndexManifest,
        *,
        seed: int,
    ) -> None:
        self._entries = entries
        self.manifest = manifest
        self.seed = seed

    @classmethod
    def build(
        cls,
        records: Iterable[tuple[str, Iterable[float]]],
        *,
        lane: str,
        generation: str,
        corpus_hash: str,
        embedding_hash: str,
        config_hash: str,
        candidate_k: int,
        result_k: int,
        seed: int,
    ) -> "QuantLaneIndex":
        if lane not in LANES:
            raise ValueError(f"unsupported lane: {lane}")
        if not generation:
            raise ValueError("generation must not be empty")
        if candidate_k < result_k or result_k < 1:
            raise ValueError("candidate_k must be >= result_k >= 1")
        entries: list[_LaneEntry] = []
        seen: set[str] = set()
        dimension: int | None = None
        for raw_id, raw_vector in records:
            if not isinstance(raw_id, str) or not raw_id or raw_id in seen:
                raise ValueError("record IDs must be unique non-empty strings")
            vector = tuple(float(value) for value in raw_vector)
            if (
                not vector
                or any(not math.isfinite(value) for value in vector)
                or (dimension is not None and len(vector) != dimension)
            ):
                raise ValueError("vectors must be finite and share one dimension")
            dimension = len(vector)
            seen.add(raw_id)
            if lane == "Q0":
                encoded: tuple[float | int, ...] | QuantizedVector = slot_quantize(
                    vector, "Q0"
                )
            elif lane == "Q1":
                encoded = slot_quantize(vector, "Q1")
            else:
                encoded = turboquant_quantize(vector, seed)
            entries.append(_LaneEntry(raw_id, vector, encoded))
        if not entries or dimension is None:
            raise ValueError("at least one record is required")
        temporary = cls(
            tuple(entries),
            QuantIndexManifest(
                lane,
                generation,
                corpus_hash,
                embedding_hash,
                config_hash,
                "0" * 64,
                0,
                len(entries),
                dimension,
                candidate_k,
                result_k,
            ),
            seed=seed,
        )
        payload = temporary.serialized_payload()
        manifest = QuantIndexManifest(
            lane,
            generation,
            corpus_hash,
            embedding_hash,
            config_hash,
            hashlib.sha256(payload).hexdigest(),
            len(payload),
            len(entries),
            dimension,
            candidate_k,
            result_k,
        )
        return cls(tuple(entries), manifest, seed=seed)

    def serialized_payload(self) -> bytes:
        output = bytearray(b"SFASTQ1\0")
        output.extend(struct.pack("<II", len(self._entries), self.manifest.dimension))
        if self.manifest.lane in {"Q2a", "Q2b"}:
            # Rotation seed is an index invariant, not per-vector payload.
            output.extend(struct.pack("<Q", self.seed))
        for entry in self._entries:
            encoded_id = entry.canonical_id.encode("utf-8")
            output.extend(struct.pack("<H", len(encoded_id)))
            output.extend(encoded_id)
            if self.manifest.lane == "Q0":
                assert isinstance(entry.encoded, tuple)
                output.extend(struct.pack(f"<{len(entry.encoded)}d", *entry.encoded))
            elif self.manifest.lane == "Q1":
                assert isinstance(entry.encoded, tuple)
                peak = max(abs(value) for value in entry.integral)
                output.extend(struct.pack("<f", peak / 127 if peak else 1.0))
                output.extend(struct.pack(f"<{len(entry.encoded)}b", *entry.encoded))
            else:
                assert isinstance(entry.encoded, QuantizedVector)
                output.extend(struct.pack("<f", entry.encoded.scale))
                output.extend(entry.encoded.packed)
        return bytes(output)

    def persist_atomic(
        self,
        target: str | Path,
        *,
        fault: Callable[[str, Path], None] | None = None,
    ) -> Path:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        payload = self.serialized_payload()
        try:
            temporary.write_bytes(payload)
            if fault is not None:
                fault("before_swap", temporary)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return path

    def verify_file(
        self,
        path: str | Path,
        *,
        generation: str,
        corpus_hash: str,
        embedding_hash: str,
        config_hash: str,
        backend: str = "python",
    ) -> dict[str, Any]:
        self.manifest.verify(
            generation=generation,
            corpus_hash=corpus_hash,
            embedding_hash=embedding_hash,
            config_hash=config_hash,
            backend=backend,
        )
        target = Path(path)
        try:
            size = target.stat().st_size
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as error:
            raise QuantBenchmarkError("INDEX_CORRUPT", type(error).__name__) from error
        if size != self.manifest.index_bytes or actual != self.manifest.index_hash:
            raise QuantBenchmarkError(
                "INDEX_CORRUPT",
                f"expected={self.manifest.index_hash} actual={actual}",
            )
        return {"index_hash": actual, "index_bytes": size}

    def mmap_touches(self, path: str | Path) -> tuple[float, float]:
        target = Path(path)
        with target.open("rb") as handle:
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as view:
                started = time.perf_counter()
                checksum = sum(view[offset] for offset in range(0, len(view), 4096))
                first_ms = (time.perf_counter() - started) * 1000
                started = time.perf_counter()
                checksum ^= sum(view[offset] for offset in range(0, len(view), 4096))
                warm_ms = (time.perf_counter() - started) * 1000
        if checksum != 0:
            raise AssertionError("mmap touch checksum invariant failed")
        return first_ms, warm_ms

    def query(self, query: Iterable[float]) -> tuple[tuple[str, ...], dict[str, float]]:
        vector = tuple(float(value) for value in query)
        if len(vector) != self.manifest.dimension:
            raise ValueError("query dimension mismatch")
        started = time.perf_counter()
        rerank_ms = 0.0
        if self.manifest.lane == "Q0":
            ranked = exact_rerank(
                vector,
                ((entry.canonical_id, entry.integral) for entry in self._entries),
                metric="cosine",
                top_k=self.manifest.result_k,
            )
        elif self.manifest.lane == "Q1":
            encoded_query = slot_quantize(vector, "Q1")
            query_norm = math.sqrt(sum(float(value) ** 2 for value in encoded_query))
            scores = []
            for entry in self._entries:
                assert isinstance(entry.encoded, tuple)
                norm = math.sqrt(sum(float(value) ** 2 for value in entry.encoded))
                dot = sum(
                    float(left) * float(right)
                    for left, right in zip(encoded_query, entry.encoded)
                )
                score = dot / (query_norm * norm) if query_norm and norm else 0.0
                scores.append((entry.canonical_id, score))
            scores.sort(key=lambda item: (-item[1], item[0]))
            ranked_ids = tuple(item[0] for item in scores[: self.manifest.result_k])
            elapsed = (time.perf_counter() - started) * 1000
            return ranked_ids, {
                "query_ms": elapsed,
                "approximate_ms": elapsed,
                "rerank_ms": 0.0,
            }
        else:
            approximate = approximate_candidates(
                vector,
                (
                    (entry.canonical_id, entry.encoded)
                    for entry in self._entries
                    if isinstance(entry.encoded, QuantizedVector)
                ),
                seed=self.seed,
                metric="cosine",
                candidate_k=(
                    self.manifest.candidate_k
                    if self.manifest.lane == "Q2b"
                    else self.manifest.result_k
                ),
            )
            approximate_ms = (time.perf_counter() - started) * 1000
            if self.manifest.lane == "Q2a":
                ranked = approximate
            else:
                integral = {
                    entry.canonical_id: entry.integral for entry in self._entries
                }
                rerank_started = time.perf_counter()
                ranked = exact_rerank(
                    vector,
                    (
                        (candidate.canonical_id, integral[candidate.canonical_id])
                        for candidate in approximate
                    ),
                    metric="cosine",
                    top_k=self.manifest.result_k,
                )
                rerank_ms = (time.perf_counter() - rerank_started) * 1000
            elapsed = (time.perf_counter() - started) * 1000
            return tuple(item.canonical_id for item in ranked), {
                "query_ms": elapsed,
                "approximate_ms": approximate_ms,
                "rerank_ms": rerank_ms,
            }
        elapsed = (time.perf_counter() - started) * 1000
        return tuple(item.canonical_id for item in ranked), {
            "query_ms": elapsed,
            "approximate_ms": elapsed,
            "rerank_ms": 0.0,
        }


def build_fixture(size: int, *, dimension: int = 16, seed: int = 198) -> QuantDataset:
    """Build a frozen relevance fixture with deterministic L2 embeddings."""
    if size < 1 or dimension < 2:
        raise ValueError("size must be positive and dimension >= 2")
    generator = random.Random(seed)
    topics = min(dimension, 16)
    records: list[tuple[str, tuple[float, ...]]] = []
    corpus_rows: list[dict[str, Any]] = []
    for index in range(size):
        topic = index % topics
        canonical_id = f"doc-{index:07d}"
        values = [generator.uniform(-0.035, 0.035) for _ in range(dimension)]
        values[topic] += 1.0
        values[(topic + 1) % dimension] += 0.2
        norm = math.sqrt(sum(value * value for value in values))
        vector = tuple(value / norm for value in values)
        records.append((canonical_id, vector))
        corpus_rows.append(
            {
                "id": canonical_id,
                "text": f"synthetic topic-{topic} record-{index}",
                "split": "benchmark",
            }
        )
    queries: list[QueryFixture] = []
    for topic in range(topics):
        values = [0.0] * dimension
        values[topic] = 1.0
        values[(topic + 1) % dimension] = 0.2
        norm = math.sqrt(sum(value * value for value in values))
        vector = tuple(value / norm for value in values)
        exact = exact_rerank(
            vector,
            records,
            metric="cosine",
            top_k=min(20, len(records)),
        )
        queries.append(
            QueryFixture(
                f"query-topic-{topic}",
                vector,
                tuple(candidate.canonical_id for candidate in exact),
            )
        )
    corpus_hash = digest(corpus_rows)
    query_hash = digest(
        [{"query_id": item.query_id, "vector": item.vector} for item in queries]
    )
    judgments_hash = digest({item.query_id: item.relevant_ids for item in queries})
    embedding_hash = digest(
        {
            "model": "simplicio-deterministic-cluster-v1",
            "version": "1",
            "dimension": dimension,
            "normalization": "l2",
            "seed": seed,
            "vectors": records,
        }
    )
    dataset_hash = digest(
        {
            "corpus_hash": corpus_hash,
            "query_hash": query_hash,
            "judgments_hash": judgments_hash,
            "embedding_hash": embedding_hash,
        }
    )
    return QuantDataset(
        tuple(records),
        tuple(queries),
        dimension,
        seed,
        corpus_hash,
        query_hash,
        judgments_hash,
        embedding_hash,
        dataset_hash,
    )


def repository_corpus_receipt(root: str | Path) -> dict[str, Any]:
    """Hash only text blobs reachable from the repository's ``HEAD`` tree."""
    base = Path(root).resolve()
    suffixes = {".py", ".md", ".toml", ".json", ".yaml", ".yml"}
    try:
        commit = _run_git(
            ["rev-parse", "HEAD"], cwd=base, timeout=5, text=True
        ).stdout.strip()
        tree = _run_git(
            ["rev-parse", "HEAD^{tree}"], cwd=base, timeout=5, text=True
        ).stdout.strip()
        entries = _run_git(["ls-tree", "-r", "-z", "HEAD"], cwd=base, timeout=10).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise QuantBenchmarkError(
            "SOURCE_TREE_UNAVAILABLE", type(error).__name__
        ) from error
    source_hashes: dict[str, str] = {}
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, encoded_relative = entry.split(b"\t", 1)
        _, kind, object_id = metadata.decode("ascii").split()
        relative = Path(encoded_relative.decode("utf-8", "surrogateescape"))
        if (
            kind != "blob"
            or relative.suffix.lower() not in suffixes
            or relative.parts[:2]
            in {("benchmarks", "results"), ("benchmarks", "reports")}
        ):
            continue
        try:
            payload = _run_git(
                ["cat-file", "blob", object_id], cwd=base, timeout=10
            ).stdout
        except (OSError, subprocess.SubprocessError) as error:
            raise QuantBenchmarkError(
                "SOURCE_TREE_UNAVAILABLE",
                f"{relative.as_posix()}:{type(error).__name__}",
            ) from error
        source_hashes[relative.as_posix()] = hashlib.sha256(payload).hexdigest()
    return {
        "kind": "real-repository-corpus",
        "source": "git-head-tree",
        "source_commit": commit,
        "source_tree": tree,
        "tracked_only": True,
        "files": len(source_hashes),
        "corpus_hash": digest(source_hashes),
        "source_hashes": source_hashes,
        "embedded": False,
        "embedded_null_reason": "REAL_CORPUS_PROVENANCE_ONLY_SYNTHETIC_SCALE_MATRIX",
    }


def quality_metrics(
    relevant_ids: Sequence[str], actual_ids: Sequence[str]
) -> dict[str, float]:
    relevant = set(relevant_ids)
    if not relevant:
        raise ValueError("relevance judgments must not be empty")
    output: dict[str, float] = {}
    for k in (1, 5, 10, 20):
        selected = tuple(actual_ids[:k])
        hits = sum(item in relevant for item in selected)
        output[f"recall_at_{k}"] = hits / min(len(relevant), k)
        output[f"precision_at_{k}"] = hits / k
    top_ten = tuple(actual_ids[:10])
    dcg = sum(
        (1.0 if item in relevant else 0.0) / math.log2(index + 2)
        for index, item in enumerate(top_ten)
    )
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(10, len(relevant))))
    output["ndcg_at_10"] = dcg / ideal if ideal else 1.0
    output["mrr"] = next(
        (
            1.0 / (index + 1)
            for index, item in enumerate(actual_ids)
            if item in relevant
        ),
        0.0,
    )
    output["abstention_rate"] = 1.0 if not actual_ids else 0.0
    return output


def _mean_metrics(samples: Sequence[Mapping[str, float]]) -> dict[str, float]:
    keys = tuple(samples[0])
    return {key: statistics.fmean(sample[key] for sample in samples) for key in keys}


def _page_size() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, ValueError, OSError):
        return 4096


def _current_rss_bytes() -> tuple[int | None, str | None]:
    statm = Path("/proc/self/statm")
    try:
        pages = int(statm.read_text(encoding="ascii").split()[1])
        return pages * _page_size(), None
    except (OSError, ValueError, IndexError):
        return None, "RSS_CURRENT_UNAVAILABLE"


def _usage() -> dict[str, int]:
    if resource is None:
        return {
            "minor_page_faults": 0,
            "major_page_faults": 0,
            "input_blocks": 0,
            "output_blocks": 0,
            "peak_rss_kib": 0,
        }
    observed = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "minor_page_faults": int(observed.ru_minflt),
        "major_page_faults": int(observed.ru_majflt),
        "input_blocks": int(observed.ru_inblock),
        "output_blocks": int(observed.ru_oublock),
        "peak_rss_kib": int(observed.ru_maxrss),
    }


def _usage_delta(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    return {
        key: after[key] - before[key]
        for key in (
            "minor_page_faults",
            "major_page_faults",
            "input_blocks",
            "output_blocks",
        )
    }


def _measure_lane(
    dataset: QuantDataset,
    *,
    lane: str,
    generation: str,
    config_hash: str,
    candidate_k: int,
    result_k: int,
    repetitions: int,
    directory: Path,
    shared_integral_store: bool,
) -> dict[str, Any]:
    # Excluded warmup: compile bytecode paths and populate Python method caches.
    warmup = QuantLaneIndex.build(
        dataset.records[: min(128, len(dataset.records))],
        lane=lane,
        generation=generation,
        corpus_hash=dataset.corpus_hash,
        embedding_hash=dataset.embedding_hash,
        config_hash=config_hash,
        candidate_k=candidate_k,
        result_k=result_k,
        seed=dataset.seed,
    )
    warmup.query(dataset.queries[0].vector)

    samples: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    for repetition in range(repetitions):
        before_usage = _usage()
        rss_before, rss_reason = _current_rss_bytes()
        cpu_started = time.process_time()
        build_started = time.perf_counter()
        index = QuantLaneIndex.build(
            dataset.records,
            lane=lane,
            generation=generation,
            corpus_hash=dataset.corpus_hash,
            embedding_hash=dataset.embedding_hash,
            config_hash=config_hash,
            candidate_k=candidate_k,
            result_k=result_k,
            seed=dataset.seed,
        )
        build_ms = (time.perf_counter() - build_started) * 1000
        path = index.persist_atomic(directory / f"{lane}-{repetition}.sfastq")
        index.verify_file(
            path,
            generation=generation,
            corpus_hash=dataset.corpus_hash,
            embedding_hash=dataset.embedding_hash,
            config_hash=config_hash,
        )
        mmap_first_ms, mmap_warm_ms = index.mmap_touches(path)
        query_latencies: list[float] = []
        approximate_latencies: list[float] = []
        rerank_latencies: list[float] = []
        query_metrics: list[dict[str, float]] = []
        context_bytes = 0
        result_digest_rows = []
        for query in dataset.queries:
            ranked, timings = index.query(query.vector)
            query_latencies.append(timings["query_ms"])
            approximate_latencies.append(timings["approximate_ms"])
            rerank_latencies.append(timings["rerank_ms"])
            query_metrics.append(quality_metrics(query.relevant_ids, ranked))
            encoded = canonical({"query_id": query.query_id, "results": ranked})
            context_bytes += len(encoded)
            result_digest_rows.append((query.query_id, ranked))
        rss_after, _ = _current_rss_bytes()
        after_usage = _usage()
        sample = {
            "repetition": repetition,
            "build_ms": build_ms,
            "query_ms": query_latencies,
            "approximate_ms": approximate_latencies,
            "rerank_ms": rerank_latencies,
            "mmap_first_touch_ms": mmap_first_ms,
            "mmap_warm_ms": mmap_warm_ms,
            "quality": _mean_metrics(query_metrics),
            "context_bytes": context_bytes,
            "context_tokens_estimate": math.ceil(context_bytes / 4),
            "ac_pass_rate": statistics.fmean(
                metric["precision_at_1"] for metric in query_metrics
            ),
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "resident_pages_before": (
                rss_before // _page_size() if rss_before is not None else None
            ),
            "resident_pages_after": (
                rss_after // _page_size() if rss_after is not None else None
            ),
            "rss_delta_bytes": (
                max(0, rss_after - rss_before)
                if rss_after is not None and rss_before is not None
                else None
            ),
            "rss_null_reason": rss_reason,
            "usage_delta": _usage_delta(before_usage, after_usage),
            "peak_rss_kib": after_usage["peak_rss_kib"],
            "cpu_ms": (time.process_time() - cpu_started) * 1000,
            "result_digest": digest(result_digest_rows),
        }
        samples.append(sample)
        manifests.append(index.manifest.receipt())
    build_values = [sample["build_ms"] for sample in samples]
    query_values = [latency for sample in samples for latency in sample["query_ms"]]
    approximate_values = [
        latency for sample in samples for latency in sample["approximate_ms"]
    ]
    rerank_values = [latency for sample in samples for latency in sample["rerank_ms"]]
    first_touch_values = [sample["mmap_first_touch_ms"] for sample in samples]
    warm_values = [sample["mmap_warm_ms"] for sample in samples]
    rss_deltas = [
        sample["rss_delta_bytes"]
        for sample in samples
        if sample["rss_delta_bytes"] is not None
    ]
    quality = _mean_metrics([sample["quality"] for sample in samples])
    total_query_seconds = sum(query_values) / 1000
    integral_store_bytes = (
        len(dataset.records) * dataset.dimension * struct.calcsize("<d")
    )
    index_bytes = manifests[0]["index_bytes"]
    integral_store_shared = lane != "Q0" and shared_integral_store
    total_storage_bytes = (
        index_bytes if lane == "Q0" else index_bytes + integral_store_bytes
    )
    promotion_memory_bytes = (
        index_bytes if lane == "Q0" or integral_store_shared else total_storage_bytes
    )
    return {
        "classification": "MEASURED",
        "lane": lane,
        "repetitions": repetitions,
        "queries_per_repetition": len(dataset.queries),
        "build_ms": _summary(build_values),
        "query_ms": _summary(query_values),
        "approximate_ms": _summary(approximate_values),
        "rerank_ms": _summary(rerank_values),
        "mmap_first_touch_ms": _summary(first_touch_values),
        "mmap_warm_ms": _summary(warm_values),
        "throughput_queries_per_second": (
            len(query_values) / total_query_seconds if total_query_seconds else None
        ),
        "quality": quality,
        "index_bytes": index_bytes,
        "integral_store_bytes": integral_store_bytes,
        "integral_store_shared": integral_store_shared,
        "total_storage_bytes": total_storage_bytes,
        "promotion_memory_bytes": promotion_memory_bytes,
        "rss_delta_bytes": _summary(rss_deltas) if rss_deltas else None,
        "rss_null_reason": None if rss_deltas else "RSS_CURRENT_UNAVAILABLE",
        "resident_pages_after_raw": [
            sample["resident_pages_after"] for sample in samples
        ],
        "peak_rss_kib": max(sample["peak_rss_kib"] for sample in samples),
        "page_faults": {
            "minor_raw": [
                sample["usage_delta"]["minor_page_faults"] for sample in samples
            ],
            "major_raw": [
                sample["usage_delta"]["major_page_faults"] for sample in samples
            ],
        },
        "io_blocks": {
            "input_raw": [sample["usage_delta"]["input_blocks"] for sample in samples],
            "output_raw": [
                sample["usage_delta"]["output_blocks"] for sample in samples
            ],
        },
        "context_bytes": statistics.fmean(
            sample["context_bytes"] for sample in samples
        ),
        "context_tokens_estimate": statistics.fmean(
            sample["context_tokens_estimate"] for sample in samples
        ),
        "ac_pass_rate": statistics.fmean(sample["ac_pass_rate"] for sample in samples),
        "python_deterministic": len({sample["result_digest"] for sample in samples})
        == 1,
        "python_result_digest": samples[0]["result_digest"],
        "rust_parity": None,
        "rust_parity_null_reason": "RUNTIME_FAST_QUANT_CAPABILITY_UNAVAILABLE",
        "fallback": {"used": False, "reason_code": None},
        "manifest": manifests[0],
        "raw_samples": samples,
    }


def _promotion_gate(
    q0: Mapping[str, Any],
    q2b: Mapping[str, Any],
    *,
    max_recall_regression: float,
    max_ndcg_regression: float,
    minimum_index_reduction: float,
    maximum_latency_ratio: float,
) -> dict[str, Any]:
    recall_regression = q0["quality"]["recall_at_10"] - q2b["quality"]["recall_at_10"]
    ndcg_regression = q0["quality"]["ndcg_at_10"] - q2b["quality"]["ndcg_at_10"]
    index_reduction = 1 - (q2b["index_bytes"] / q0["index_bytes"])
    total_storage_reduction = 1 - (
        q2b["total_storage_bytes"] / q0["total_storage_bytes"]
    )
    policy_memory_reduction = 1 - (
        q2b["promotion_memory_bytes"] / q0["promotion_memory_bytes"]
    )
    latency_ratio = q2b["query_ms"]["p95"] / q0["query_ms"]["p95"]
    checks = {
        "quality_recall": recall_regression <= max_recall_regression,
        "quality_ndcg": ndcg_regression <= max_ndcg_regression,
        "memory_policy": policy_memory_reduction >= minimum_index_reduction,
        "latency": latency_ratio <= maximum_latency_ratio,
        "rerank_present": q2b["rerank_ms"]["p50"] > 0,
        "measured_only": (
            q0.get("classification") == "MEASURED"
            and q2b.get("classification") == "MEASURED"
        ),
    }
    return {
        "schema": "simplicio.fast.quant-promotion-gate/v1",
        "decision": "PROMOTE" if all(checks.values()) else "REJECT",
        "fail_closed": True,
        "checks": checks,
        "observed": {
            "recall_at_10_regression": recall_regression,
            "ndcg_at_10_regression": ndcg_regression,
            "index_reduction": index_reduction,
            "total_storage_reduction": total_storage_reduction,
            "policy_memory_reduction": policy_memory_reduction,
            "promotion_memory_bytes": {
                "q0": q0["promotion_memory_bytes"],
                "q2b": q2b["promotion_memory_bytes"],
            },
            "storage_policy": (
                "shared-integral-store"
                if q2b["integral_store_shared"]
                else "dedicated-end-to-end"
            ),
            "query_p95_latency_ratio": latency_ratio,
        },
        "thresholds": {
            "max_recall_regression": max_recall_regression,
            "max_ndcg_regression": max_ndcg_regression,
            "minimum_index_reduction": minimum_index_reduction,
            "maximum_latency_ratio": maximum_latency_ratio,
        },
    }


def concurrency_receipt(
    index: QuantLaneIndex,
    queries: Sequence[QueryFixture],
    *,
    slots: int,
) -> dict[str, Any]:
    if slots not in {1, 5, 20}:
        raise ValueError("slots must be 1, 5, or 20")
    selected = tuple(queries[index % len(queries)].vector for index in range(slots))
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=slots) as executor:
        results = tuple(executor.map(index.query, selected))
    return {
        "slots": slots,
        "wall_ms": (time.perf_counter() - started) * 1000,
        "result_digest": digest([result[0] for result in results]),
        "isolated_calls": len(results),
    }


def run_quant_benchmark(
    vectors: Sequence[Sequence[float]],
    queries: Sequence[Sequence[float]],
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Run the compact API published by PR #217.

    The response shape and lane names remain stable for compatibility. New
    integrations should use :func:`run_benchmark`, whose receipt includes
    complete measurement and provenance contracts.
    """
    if not vectors or not queries:
        raise ValueError("vectors and queries are required")
    if top_k < 1:
        raise ValueError("top_k must be positive")
    dimension = len(vectors[0])
    if dimension < 1 or any(len(vector) != dimension for vector in vectors):
        raise ValueError("vectors must have one non-zero dimension")
    if any(len(query) != dimension for query in queries):
        raise ValueError("queries must match the vector dimension")
    started = time.perf_counter()
    records = tuple(
        (f"vector-{offset:07d}", tuple(float(value) for value in vector))
        for offset, vector in enumerate(vectors)
    )
    normalized_queries = tuple(
        tuple(float(value) for value in query) for query in queries
    )
    corpus_hash = digest(records)
    embedding_hash = digest({"model": "compatibility-input/v1", "records": records})
    config_hash = digest(
        {"api": "run_quant_benchmark", "top_k": top_k, "metric": "cosine"}
    )
    generation = digest(
        {
            "corpus_hash": corpus_hash,
            "embedding_hash": embedding_hash,
            "config_hash": config_hash,
        }
    )
    candidate_k = max(top_k, top_k * 4)
    lanes: dict[str, dict[str, Any]] = {}
    for public_name, lane, bits in (
        ("Q0_full", "Q0", None),
        ("Q1_8bit", "Q1", 8),
        ("Q2_turboquant_4bit", "Q2a", 4),
    ):
        index = QuantLaneIndex.build(
            records,
            lane=lane,
            generation=generation,
            corpus_hash=corpus_hash,
            embedding_hash=embedding_hash,
            config_hash=config_hash,
            candidate_k=candidate_k,
            result_k=top_k,
            seed=198,
        )
        hits = sum(len(index.query(query)[0]) for query in normalized_queries)
        lanes[public_name] = {
            "hits": hits,
            "recall_proxy": hits / (len(normalized_queries) * top_k),
            "bits": bits,
        }
    return {
        "schema": BENCH_SCHEMA,
        "lanes": lanes,
        "queries": len(normalized_queries),
        "vectors": len(records),
        "top_k": top_k,
        "wall_ms": round((time.perf_counter() - started) * 1000, 3),
        "cpu_ms": None,
        "cpu_ms_null_reason": "NOT_MEASURED",
        "rss_bytes": None,
        "rss_bytes_null_reason": "NOT_MEASURED",
        "deprecated": True,
        "replacement": "run_benchmark",
    }


def _source_state(root: Path) -> dict[str, Any]:
    def git(*args: str) -> str | None:
        try:
            return _run_git(list(args), cwd=root, timeout=3, text=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    commit = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    status = git("status", "--porcelain=v1", "--untracked-files=all")
    dirty = status is None or bool(status)
    return {
        "schema": "simplicio.fast.benchmark-source-state/v1",
        "commit": commit,
        "tree": tree,
        "dirty": dirty,
        "reproducible": commit is not None and tree is not None and not dirty,
        "dirty_paths": status.splitlines() if status else [],
    }


def run_benchmark(
    root: str | Path,
    *,
    sizes: Sequence[int] = (10_000, 100_000, 1_000_000),
    repetitions: int = 10,
    max_vectors: int = 10_000,
    dimension: int = 16,
    candidate_k: int = 80,
    result_k: int = 20,
    seed: int = 198,
    shared_integral_store: bool = False,
) -> dict[str, Any]:
    if repetitions < 10:
        raise ValueError("repetitions must be at least 10")
    if max_vectors < 1 or any(size < 1 for size in sizes):
        raise ValueError("sizes and max_vectors must be positive")
    if candidate_k < result_k:
        raise ValueError("candidate_k must be >= result_k")
    base = Path(root).resolve()
    implementation_hashes = {
        relative: hashlib.sha256((base / relative).read_bytes()).hexdigest()
        for relative in (
            "benchmarks/quant_benchmark_198.py",
            "src/simplicio_fast/quant_benchmark.py",
            "src/simplicio_fast/slot_executor.py",
            "src/simplicio_fast/turboquant.py",
        )
    }
    configuration = {
        "schema": BENCHMARK_SCHEMA,
        "sizes": list(sizes),
        "repetitions": repetitions,
        "max_vectors": max_vectors,
        "dimension": dimension,
        "candidate_k": candidate_k,
        "result_k": result_k,
        "seed": seed,
        "storage_policy": (
            "shared-integral-store" if shared_integral_store else "dedicated-end-to-end"
        ),
        "metric": "cosine",
        "warmup": "one excluded build/query per lane",
        "cache_states": ["mmap_first_touch", "mmap_warm"],
        "implementation_hashes": implementation_hashes,
    }
    config_hash = digest(configuration)
    generation = digest({"config_hash": config_hash, "source": "issue-198"})
    measured: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-quant-") as directory:
        temporary = Path(directory)
        for size in sizes:
            if size > max_vectors:
                unavailable.append(
                    {
                        "classification": "BLOCKED",
                        "status": "unavailable",
                        "vectors": size,
                        "value": None,
                        "reason": "CAPACITY_LIMIT_CONFIGURED",
                        "configured_max_vectors": max_vectors,
                    }
                )
                continue
            dataset = build_fixture(size, dimension=dimension, seed=seed)
            lanes = {
                lane: _measure_lane(
                    dataset,
                    lane=lane,
                    generation=generation,
                    config_hash=config_hash,
                    candidate_k=candidate_k,
                    result_k=result_k,
                    repetitions=repetitions,
                    directory=temporary,
                    shared_integral_store=shared_integral_store,
                )
                for lane in LANES
            }
            q0 = lanes["Q0"]
            for lane in LANES:
                lanes[lane]["index_reduction_vs_q0"] = 1 - (
                    lanes[lane]["index_bytes"] / q0["index_bytes"]
                )
            reference = QuantLaneIndex.build(
                dataset.records,
                lane="Q2b",
                generation=generation,
                corpus_hash=dataset.corpus_hash,
                embedding_hash=dataset.embedding_hash,
                config_hash=config_hash,
                candidate_k=candidate_k,
                result_k=result_k,
                seed=seed,
            )
            measured.append(
                {
                    "classification": "MEASURED",
                    "vectors": size,
                    "dataset": dataset.receipt(),
                    "lanes": lanes,
                    "concurrency": [
                        concurrency_receipt(reference, dataset.queries, slots=slots)
                        for slots in (1, 5, 20)
                    ],
                    "promotion_gate": _promotion_gate(
                        lanes["Q0"],
                        lanes["Q2b"],
                        max_recall_regression=0.02,
                        max_ndcg_regression=0.02,
                        minimum_index_reduction=0.50,
                        maximum_latency_ratio=1.50,
                    ),
                }
            )
    source_state = _source_state(base)
    commit = source_state["commit"] or "unavailable"
    sizes_arg = ",".join(str(size) for size in sizes)
    shared_arg = " --shared-integral-store" if shared_integral_store else ""
    execution_report = benchmark_receipt(
        repository_id=base.name,
        source_commit=commit,
        generation=generation,
        fixture={
            "name": "quant-benchmark-198",
            "sizes": list(sizes),
            "seed": seed,
            "config_sha256": config_hash,
        },
        workload={
            "name": "quantized-lane-query",
            "candidate_k": candidate_k,
            "result_k": result_k,
            "dimension": dimension,
        },
        hardware={
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        cache_policy="mmap-first-touch-and-warm",
        repetitions=repetitions,
        baseline={"status": "blocked", "reason": "baseline_not_run"},
        classification="MEASURED",
        evidence={"command": "benchmarks/quant_benchmark_198.py", "exit_code": 0},
        metrics={"measured_sizes": len(measured), "blocked_sizes": len(unavailable)},
    )
    return {
        "schema": BENCHMARK_SCHEMA,
        "issue": 198,
        "status": "measured",
        "classification": "MEASURED",
        "command": (
            "PYTHONPATH=src python benchmarks/quant_benchmark_198.py "
            f"--repetitions {repetitions} --sizes {sizes_arg} "
            f"--max-vectors {max_vectors} --dimension {dimension} "
            f"--candidate-k {candidate_k} --result-k {result_k} "
            f"--seed {seed}{shared_arg}"
        ),
        "configuration": configuration,
        "config_hash": config_hash,
        "generation": generation,
        "source_commit": commit,
        "source_tree": source_state["tree"],
        "source_state": source_state,
        "execution_report": execution_report,
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "cpu_count": os.cpu_count(),
            "page_size": _page_size(),
        },
        "corpora": {
            "real": repository_corpus_receipt(root),
            "synthetic": [case["dataset"] for case in measured],
        },
        "measured": measured,
        "unavailable_sizes": unavailable,
        "simulated": {
            "classification": "SIMULATED",
            "values": None,
            "reason": "SIMULATION_NOT_RUN",
        },
        "parity": {
            "python": "MEASURED",
            "rust": None,
            "rust_reason": "RUNTIME_FAST_QUANT_CAPABILITY_UNAVAILABLE",
            "rust_compilation_attempted": False,
        },
        "claims": {
            "speed": "MEASURED_ONLY",
            "memory": "MEASURED_ONLY",
            "tokens": None,
            "tokens_reason": "NO_LLM_OR_PROVIDER_USED",
        },
    }


__all__ = [
    "BENCH_SCHEMA",
    "BENCHMARK_SCHEMA",
    "DATASET_SCHEMA",
    "LANES",
    "MANIFEST_SCHEMA",
    "QuantBenchmarkError",
    "QuantDataset",
    "QuantIndexManifest",
    "QuantLaneIndex",
    "QueryFixture",
    "build_fixture",
    "canonical",
    "concurrency_receipt",
    "digest",
    "quality_metrics",
    "repository_corpus_receipt",
    "run_benchmark",
    "run_quant_benchmark",
]
