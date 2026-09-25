"""Deterministic delivery-engine preparation and cache receipts.

This layer coordinates bounded semantic preparation. It does not make cognitive
decisions or write source files: Dev CLI owns mutation and Runtime owns Full
effects. The receipt is the handoff contract for Loop standalone and Full.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .adapters import language_for_path
from .integrations import run_runtime_effect_transaction
from .mapper_ingest import MapperIngestError, validate_handoff
from .mapper_snapshot import compile_mapper_payload
from .parser_adapter import build_payload_from_mapper
from .processor import ProjectProcessor
from .semantic_scoring import (
    SemanticBudgets,
    SemanticScorer,
    SemanticScoringError,
    SourceDocument,
)
from .snapshot import Snapshot, build_snapshot
from .tokenizers import resolve_tokenizer


SCHEMA = "simplicio.fast.delivery-engine/v1"
CONTEXT_REQUEST_SCHEMA = "simplicio.fast.context-request/v2"
DEFAULT_SCORING_CONFIG = "semantic-ranking-v1"
PROFILE_NAMES = {"full": "Full", "loop-standalone": "Loop standalone"}
SELECTION_MODES = {"semantic", "legacy-regex"}


def _source_commit(root: Path) -> tuple[str | None, str | None]:
    try:
        with tempfile.TemporaryDirectory(prefix="simplicio-fast-git-") as directory:
            stdout_path = Path(directory) / "stdout.txt"
            stderr_path = Path(directory) / "stderr.txt"
            with (
                stdout_path.open("w", encoding="utf-8") as stdout,
                stderr_path.open("w", encoding="utf-8") as stderr,
            ):
                result = subprocess.run(
                    ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    check=False,
                    close_fds=True,
                )
            commit = stdout_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None, "git_unavailable"
    return (
        (commit, None)
        if result.returncode == 0 and commit
        else (None, "not_a_git_checkout")
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _receipt_digest(receipt: dict[str, Any]) -> str:
    unsigned = dict(receipt)
    unsigned.pop("receipt_digest", None)
    encoded = json.dumps(unsigned, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_cached_prepare(path: Path, cache_key: str) -> dict[str, Any] | None:
    """Return only a structurally valid receipt for this exact cache key."""
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(cached, dict):
        return None
    if cached.get("schema") != SCHEMA or cached.get("status") != "ready":
        return None
    cache = cached.get("cache")
    timings = cached.get("timings")
    request = cached.get("context_request")
    context = cached.get("context")
    if (
        not isinstance(cache, dict)
        or cache.get("key") != cache_key
        or not isinstance(timings, dict)
        or not isinstance(request, dict)
        or request.get("schema") != CONTEXT_REQUEST_SCHEMA
        or not isinstance(context, dict)
        or not isinstance(context.get("tokenizer"), dict)
        or cached.get("receipt_digest") != _receipt_digest(cached)
    ):
        return None
    return cached


def _terms(task: str) -> list[str]:
    values = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", task)
    return list(dict.fromkeys(values))[:8]


def _token_count(text: str, tokenizer: Callable[[str], int] | None) -> int:
    try:
        value = tokenizer(text) if tokenizer is not None else max(1, len(text.split()))
    except (TypeError, ValueError) as error:
        raise ValueError("tokenizer must return a non-negative integer") from error
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("tokenizer must return a non-negative integer")
    return value


def _deduplicate_spans(spans: list[Any]) -> tuple[list[Any], list[str]]:
    """Remove repeated source ranges before ranking or token accounting."""

    selected: list[Any] = []
    seen_handles: set[str] = set()
    seen_ranges: set[tuple[str, int, int, str]] = set()
    rejected: list[str] = []
    for span in spans:
        handle = span.symbol_id or f"{span.file}:{span.start_line}:{span.symbol}"
        range_key = (span.file, span.start_line, span.end_line, span.source_sha256)
        if handle in seen_handles or range_key in seen_ranges:
            rejected.append(handle)
            continue
        contained = False
        for index, previous in enumerate(selected):
            same_source = (
                span.file == previous.file
                and span.source_sha256 == previous.source_sha256
            )
            overlaps = span.start_line <= previous.end_line and previous.start_line <= span.end_line
            content_confirms = (
                span.content == previous.content
                or span.content in previous.content
                or previous.content in span.content
            )
            if same_source and overlaps and content_confirms:
                previous_handle = previous.symbol_id or (
                    f"{previous.file}:{previous.start_line}:{previous.symbol}"
                )
                previous_size = previous.end_line - previous.start_line
                current_size = span.end_line - span.start_line
                if current_size > previous_size:
                    selected[index] = span
                    seen_handles.discard(previous_handle)
                    seen_ranges.discard(
                        (
                            previous.file,
                            previous.start_line,
                            previous.end_line,
                            previous.source_sha256,
                        )
                    )
                    rejected.append(previous_handle)
                else:
                    rejected.append(handle)
                contained = True
                break
        if contained:
            continue
        seen_handles.add(handle)
        seen_ranges.add(range_key)
        selected.append(span)
    return selected, rejected


def _mapper_symbol_handles(
    root: Path, mapper_provenance: dict[str, Any]
) -> dict[tuple[str, int], str]:
    """Index Mapper symbol IDs by the public source file/line handle."""

    artifacts = mapper_provenance.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise MapperIngestError("mapper_graph_missing")
    artifact = next(
        (
            item
            for item in artifacts
            if isinstance(item, dict) and item.get("name") == "context_snapshot"
        ),
        None,
    )
    if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
        raise MapperIngestError("mapper_graph_missing")
    path = (root / artifact["path"]).resolve()
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MapperIngestError("mapper_graph_missing") from error
    if not isinstance(graph, dict) or graph.get("schema") != "simplicio.context-snapshot/v1":
        raise MapperIngestError("mapper_schema_unsupported")
    graph_payload = graph.get("graph")
    nodes = graph_payload.get("nodes") if isinstance(graph_payload, dict) else None
    if not isinstance(nodes, list):
        raise MapperIngestError("mapper_graph_missing")
    result: dict[tuple[str, int], str] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            continue
        source = node.get("source")
        if not isinstance(source, dict):
            continue
        relative = source.get("file")
        line = source.get("line")
        if (
            not isinstance(relative, str)
            or not isinstance(line, int)
            or isinstance(line, bool)
            or line < 1
            or not node["id"].startswith("symbol:")
        ):
            continue
        result.setdefault((relative.replace("\\", "/"), line), node["id"])
    if not result:
        raise MapperIngestError("mapper_graph_missing")
    return result


class DeliveryEngine:
    def __init__(self, root: Path, snapshot: Path, cache: Path | None = None) -> None:
        self.root = root.resolve()
        self.snapshot = snapshot.resolve()
        self.cache = (
            cache or self.root / ".simplicio-fast" / "delivery-cache"
        ).resolve()
        self._source_commit_cache: tuple[str | None, str | None] | None = None

    def _source_commit_receipt(self) -> tuple[str | None, str | None]:
        """Avoid repeating failed Git discovery for immutable non-Git fixtures."""
        if self._source_commit_cache is not None:
            return self._source_commit_cache
        result = _source_commit(self.root)
        if result[1] == "not_a_git_checkout":
            self._source_commit_cache = result
        return result

    def cache_stats(self) -> dict[str, Any]:
        """Return deterministic size telemetry for the disposable delivery cache."""
        paths = (
            sorted(path for path in self.cache.rglob("*.json") if path.is_file())
            if self.cache.is_dir()
            else []
        )
        return {
            "schema": "simplicio.fast.delivery-cache/v1",
            "entries": len(paths),
            "bytes": sum(path.stat().st_size for path in paths),
        }

    def _refresh_after_write(self) -> tuple[str | None, str]:
        """Refresh only bootstrap snapshots; Mapper projections need a new handoff."""

        with Snapshot(self.snapshot) as snapshot:
            if snapshot.provenance.get("mode") == "integrated":
                return None, "mapper_refresh_required"
        build_snapshot(self.root, self.snapshot)
        with Snapshot(self.snapshot) as snapshot:
            return snapshot.generation, "refreshed"

    def prepare(
        self,
        task: str,
        *,
        profile: str,
        engine_receipt: dict[str, Any],
        mode: str = "integrated",
        mapper_handoff: dict[str, Any] | None = None,
        tokenizer_id: str | None = None,
        tokenizer: Callable[[str], int] | None = None,
        scoring_config: str = DEFAULT_SCORING_CONFIG,
        selection_mode: str = "semantic",
    ) -> dict[str, Any]:
        started = time.perf_counter_ns()
        if profile not in PROFILE_NAMES:
            raise ValueError(f"unsupported delivery profile: {profile}")
        if mode not in {"bootstrap", "integrated"}:
            raise ValueError(f"unsupported mapper mode: {mode}")
        if tokenizer is not None and not tokenizer_id:
            raise ValueError("tokenizer_id is required when an exact tokenizer is supplied")
        if not scoring_config.strip():
            raise ValueError("scoring_config must not be empty")
        if selection_mode not in SELECTION_MODES:
            raise ValueError(f"unsupported selection mode: {selection_mode}")
        effective_tokenizer_id = tokenizer_id or "estimated:word-split-v1"
        active_tokenizer = tokenizer or resolve_tokenizer(tokenizer_id)
        tokenizer_mode = "exact" if active_tokenizer is not None else "estimated"
        mapper_provenance: dict[str, Any]
        if mode == "integrated":
            if mapper_handoff is None:
                raise MapperIngestError("mapper_missing")
            mapper_provenance = validate_handoff(self.root, mapper_handoff)
            mapper_handles = _mapper_symbol_handles(self.root, mapper_provenance)
            try:
                mapper_payload = build_payload_from_mapper(self.root, mapper_handoff)
                sidecar = self.snapshot.with_name(self.snapshot.name + ".mapper.json")
                sidecar_data: dict[str, Any] | None = None
                if sidecar.is_file():
                    try:
                        candidate = json.loads(sidecar.read_text(encoding="utf-8"))
                        if isinstance(candidate, dict):
                            sidecar_data = candidate
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                        sidecar_data = None
                snapshot_matches_mapper = False
                if self.snapshot.is_file():
                    try:
                        with Snapshot(self.snapshot) as existing:
                            snapshot_matches_mapper = existing.matches_mapper(
                                mapper_provenance
                            )
                    except (OSError, ValueError):
                        snapshot_matches_mapper = False
                if (
                    not self.snapshot.is_file()
                    or sidecar_data is None
                    or sidecar_data.get("mapper_generation")
                    != mapper_provenance["generation"]
                    or sidecar_data.get("handoff_sha256")
                    != mapper_provenance["handoff_sha256"]
                    or not snapshot_matches_mapper
                ):
                    compile_mapper_payload(
                        self.root,
                        mapper_payload,
                        self.snapshot,
                        mapper_generation=str(mapper_provenance["generation"]),
                        handoff_sha256=str(mapper_provenance["handoff_sha256"]),
                        mapper_provenance=mapper_provenance,
                    )
            except (OSError, TypeError, ValueError) as error:
                reason = getattr(error, "reason_code", None) or str(error)
                raise MapperIngestError("mapper_compile_failed", reason) from error
        else:
            mapper_provenance = {
                "schema": "simplicio.fast.mapper-ingest/v1",
                "mode": "bootstrap",
                "producer": "simplicio-fast-python-bootstrap",
                "generation": None,
                "handle": None,
            }
            mapper_handles = {}
        if not self.snapshot.is_file():
            if mode == "integrated":
                raise MapperIngestError("bootstrap_not_allowed")
            build_snapshot(self.root, self.snapshot)
        commit, commit_reason = self._source_commit_receipt()
        with Snapshot(self.snapshot) as snapshot:
            key_material = {
                "task": task,
                "profile": PROFILE_NAMES[profile],
                "engine": engine_receipt,
                "source_commit": commit,
                "snapshot_generation": snapshot.generation,
                "mapper_mode": mode,
                "mapper_generation": mapper_provenance.get("generation"),
                "mapper_handoff": mapper_provenance.get("handoff_sha256"),
                "tokenizer_id": effective_tokenizer_id,
                "tokenizer_mode": tokenizer_mode,
                "context_request_schema": CONTEXT_REQUEST_SCHEMA,
                "scoring_config": scoring_config,
                "selection_mode": selection_mode,
            }
            cache_key = hashlib.sha256(
                json.dumps(key_material, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
            cache_path = self.cache / f"{cache_key}.json"
            if cache_path.is_file():
                cached = _load_cached_prepare(cache_path, cache_key)
                if cached is not None:
                    cached["cache"] = {
                        "L0_attempt": "hit",
                        "hits": 1,
                        "misses": 0,
                        "key": cache_key,
                    }
                    cached["timings"]["prepare_wall_ms"] = (
                        time.perf_counter_ns() - started
                    ) / 1_000_000
                    cached["receipt_digest"] = _receipt_digest(cached)
                    return cached

            terms = _terms(task)
            spans, deduplicated_handles = _deduplicate_spans(
                snapshot.context_many(
                    self.root, terms, max_results=8, max_bytes=32_000
                )
            )
            context_bytes = sum(len(span.content.encode("utf-8")) for span in spans)
            context_tokens = (
                sum(max(1, len(span.content.split())) for span in spans) if spans else 0
            )
            documents: list[SourceDocument] = []
            spans_by_handle: dict[str, Any] = {}
            for span in spans:
                handle = (
                    span.symbol_id or f"{span.file}:{span.start_line}:{span.symbol}"
                )
                if handle in spans_by_handle:
                    continue
                spans_by_handle[handle] = span
                documents.append(
                    SourceDocument.create(
                        handle,
                        span.content,
                        structural_score=1.0 / max(1, span.start_line),
                    )
                )
            wrapper_material = {
                "schema": CONTEXT_REQUEST_SCHEMA,
                "task_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
                "generation": snapshot.generation,
                "languages": sorted(
                    {
                        language_for_path(Path(span.file))
                        or Path(span.file).suffix.casefold().lstrip(".")
                        or "unknown"
                        for span in spans
                    }
                ),
                "requested_relations": ["calls", "imports", "references", "tests"],
                "tokenizer_id": effective_tokenizer_id,
            }
            wrapper_tokens = _token_count(
                json.dumps(wrapper_material, sort_keys=True, separators=(",", ":")),
                active_tokenizer,
            )
            if wrapper_tokens >= 8_000:
                raise ValueError("context wrapper exceeds token budget")
            source_token_budget = 8_000 - wrapper_tokens
            if selection_mode == "legacy-regex":
                ranking = {
                    "schema": "simplicio.fast.semantic-ranking-receipt/v1",
                    "generation": snapshot.generation,
                    "selected": [
                        {
                            "canonical_id": document.canonical_id,
                            "score": 0.0,
                            "confidence": 0.0,
                            "reason": "legacy_regex_explicit",
                            "method": "legacy_regex",
                        }
                        for document in documents[:8]
                    ],
                    "fallback": {
                        "used": True,
                        "reason_code": "legacy_regex_explicit",
                    },
                    "usage": {
                        "candidate_count": len(documents),
                        "selected_count": min(8, len(documents)),
                    },
                }
            else:
                try:
                    ranking = SemanticScorer(
                        budgets=SemanticBudgets(
                            max_candidates=max(1, min(64, len(documents) or 1)),
                            max_selected=max(1, min(8, len(documents) or 1)),
                            max_request_bytes=32_000,
                            max_selected_tokens=source_token_budget,
                        )
                    ).score(
                        generation=snapshot.generation,
                        query=task,
                        candidates=tuple(documents),
                    )
                except SemanticScoringError as error:
                    ranking = {
                        "schema": "simplicio.fast.semantic-ranking-receipt/v1",
                        "selected": [],
                        "fallback": {"used": True, "reason_code": error.args[0]},
                        "usage": {
                            "candidate_count": len(documents),
                            "selected_count": 0,
                        },
                    }
            selected_spans = []
            selected_tokens = 0
            rejected_budget: list[str] = []
            rejected_quality: list[str] = []
            semantic_floor: float | None = None
            if selection_mode == "semantic":
                scores = [
                    item.get("confidence")
                    for item in ranking.get("selected", [])
                    if isinstance(item, dict)
                    and isinstance(item.get("confidence"), (int, float))
                    and not isinstance(item.get("confidence"), bool)
                ]
                if scores:
                    semantic_floor = max(0.12, max(scores) * 0.75)
            for item in ranking.get("selected", []):
                if not isinstance(item, dict):
                    continue
                handle = item.get("canonical_id")
                span = spans_by_handle.get(handle)
                if span is None:
                    continue
                confidence = item.get("confidence")
                if (
                    semantic_floor is not None
                    and isinstance(confidence, (int, float))
                    and not isinstance(confidence, bool)
                    and confidence < semantic_floor
                ):
                    rejected_quality.append(str(handle))
                    continue
                token_count = _token_count(span.content, active_tokenizer)
                if selected_tokens + token_count > source_token_budget:
                    rejected_budget.append(str(handle))
                    continue
                selected_spans.append(span)
                selected_tokens += token_count
            selected_mapper_handles: dict[str, str] = {}
            if mode == "integrated":
                for span in selected_spans:
                    mapper_handle = mapper_handles.get(
                        (span.file.replace("\\", "/"), span.start_line)
                    )
                    if mapper_handle is None:
                        raise MapperIngestError("mapper_id_missing", span.file)
                    selected_mapper_handles[
                        span.symbol_id or f"{span.file}:{span.start_line}:{span.symbol}"
                    ] = mapper_handle
            if selected_spans:
                context_bytes = sum(
                    len(span.content.encode("utf-8")) for span in selected_spans
                )
                context_tokens = selected_tokens
            context_request = {
                "schema": CONTEXT_REQUEST_SCHEMA,
                "task_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
                "generation": snapshot.generation,
                "structural_anchors": [
                    {
                        "handle": span.symbol_id
                        or f"{span.file}:{span.start_line}:{span.symbol}",
                        "file": span.file,
                        "line": span.start_line,
                        "kind": span.kind,
                    }
                    for span in spans[:8]
                ],
                "languages": sorted(
                    {
                        language_for_path(Path(span.file))
                        or Path(span.file).suffix.casefold().lstrip(".")
                        or "unknown"
                        for span in spans
                    }
                ),
                "requested_relations": ["calls", "imports", "references", "tests"],
                "tokenizer_id": effective_tokenizer_id,
                "budgets": {
                    "max_candidates": 64,
                    "max_selected": 8,
                    "max_request_bytes": 32_000,
                    "max_selected_tokens": source_token_budget,
                    "max_context_tokens": 8_000,
                    "max_source_bytes": 32_000,
                },
            }
            receipt: dict[str, Any] = {
                "schema": SCHEMA,
                "status": "ready",
                "task": {
                    "text": task,
                    "sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
                },
                "profile": PROFILE_NAMES[profile],
                "engine": engine_receipt,
                "engine_version": __version__,
                "repository": str(self.root),
                "source_commit": commit,
                "source_commit_reason": commit_reason,
                "base_generation": snapshot.generation,
                "overlay_generation": None,
                "context_request": context_request,
                "mapper": {
                    "schema": "simplicio.mapper-context/v1",
                    "mode": mode,
                    "producer": mapper_provenance["producer"],
                    "generation": mapper_provenance.get("generation"),
                    "source_schema": mapper_provenance.get("mapper_schema"),
                    "version": mapper_provenance.get("mapper_version"),
                    "artifact_digest": mapper_provenance.get("artifact_digest"),
                    "capability_coverage": mapper_provenance.get(
                        "capability_coverage", {}
                    ),
                    "handle": mapper_provenance.get("handle"),
                    "traceability": (
                        "mapper-symbol-id" if mode == "integrated" else "bootstrap"
                    ),
                    "selected_handles": selected_mapper_handles,
                },
                "budgets": {
                    "context_bytes": 32_000,
                    "context_tokens": 8_000,
                    "source_tokens": source_token_budget,
                    "wrapper_tokens": wrapper_tokens,
                },
                "context": {
                    "terms": terms,
                    "spans": len(selected_spans),
                    "bytes": context_bytes,
                    "tokens": context_tokens,
                    "estimated_tokens": context_tokens if active_tokenizer is None else None,
                    "source_tokens": context_tokens,
                    "wrapper_tokens": wrapper_tokens,
                    "total_tokens": context_tokens + wrapper_tokens,
                    "digest": hashlib.sha256(
                        "\n".join(span.content for span in selected_spans).encode(
                            "utf-8"
                        )
                    ).hexdigest(),
                    "selection": ranking,
                    "selected": [
                        {
                            "handle": (
                                selected_mapper_handles.get(
                                    span.symbol_id
                                    or f"{span.file}:{span.start_line}:{span.symbol}"
                                )
                                if mode == "integrated"
                                else span.symbol_id
                                or f"{span.file}:{span.start_line}:{span.symbol}"
                            ),
                            "fast_handle": span.symbol_id
                            or f"{span.file}:{span.start_line}:{span.symbol}",
                            "file": span.file,
                            "start_line": span.start_line,
                            "end_line": span.end_line,
                            "source_sha256": span.source_sha256,
                            "generation": snapshot.generation,
                            "reason": "semantic_rank_selected",
                        }
                        for span in selected_spans
                    ],
                    "rejected_budget_handles": rejected_budget,
                    "rejected_quality_handles": rejected_quality,
                    "quality_floor": semantic_floor,
                    "deduplicated_handles": deduplicated_handles,
                    "tokenizer": {
                        "mode": tokenizer_mode,
                        "id": effective_tokenizer_id,
                        "reason": None
                        if active_tokenizer is not None
                        else (
                            "provider_tokenizer_unavailable"
                            if tokenizer_id
                            else "tokenizer_unconfigured"
                        ),
                    },
                    "scoring_config": scoring_config,
                    "selection_mode": selection_mode,
                },
                "cache": {
                    "L0_attempt": "miss",
                    "hits": 0,
                    "misses": 1,
                    "key": cache_key,
                },
                "ownership": {
                    "source_writer": "simplicio-dev-cli",
                    "full_effect_authority": "simplicio-runtime"
                    if profile == "full"
                    else "local-guard",
                    "mutation_applied": False,
                },
                "reason_codes": ["prepared_context_only"],
                "timings": {
                    "prepare_wall_ms": (time.perf_counter_ns() - started) / 1_000_000
                },
            }
            receipt["receipt_digest"] = _receipt_digest(receipt)
        _atomic_json(cache_path, receipt)
        return receipt

    def deliver(
        self,
        changeset: dict[str, Any],
        *,
        profile: str,
        engine_receipt: dict[str, Any],
        write: bool = False,
        idempotency_key: str | None = None,
        runtime_authorized: bool = False,
        runtime_transaction: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one guarded changeset and persist a replay-safe delivery receipt.

        Loop standalone may use the local guarded executor. Full write effects
        require a coordinator-issued EffectTransaction; the legacy boolean
        argument is intentionally not an authority bypass. Dry-runs remain
        available in both profiles for inspection and planning.
        """
        started = time.perf_counter_ns()
        if profile not in PROFILE_NAMES:
            raise ValueError(f"unsupported delivery profile: {profile}")
        if changeset.get("schema") != "simplicio.fast.changeset/v2":
            raise ValueError("unsupported changeset schema")
        if not isinstance(changeset.get("changes"), list) or not changeset["changes"]:
            raise ValueError("changeset must contain at least one change")
        if not self.snapshot.is_file():
            raise MapperIngestError(
                "snapshot_missing",
                "prepare a canonical Mapper projection before delivery",
            )
        canonical = json.dumps(changeset, sort_keys=True, separators=(",", ":"))
        change_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        request_key = (
            idempotency_key
            or hashlib.sha256(
                json.dumps(
                    {
                        "changeset": change_digest,
                        "profile": profile,
                        "write": write,
                        "runtime_transaction": runtime_transaction,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
        result_path = self.cache / "delivery" / f"{request_key}.json"
        if result_path.is_file():
            cached = json.loads(result_path.read_text(encoding="utf-8"))
            cached["idempotency"] = {
                **cached.get("idempotency", {}),
                "key": request_key,
                "hit": True,
                "replayed": True,
            }
            cached["cache"] = {"L0_delivery": "hit", "key": request_key}
            return cached

        with Snapshot(self.snapshot) as snapshot:
            before_generation = snapshot.generation
        if profile == "full" and write:
            runtime_outcome: dict[str, Any] | None = None
            reason_codes = ["runtime_authorization_required"]
            if runtime_transaction is not None:
                try:
                    transaction_write_set = runtime_transaction.get("write_set")
                    changeset_paths = [
                        change["path"] for change in changeset["changes"]
                    ]
                    if sorted(transaction_write_set or []) != sorted(changeset_paths):
                        raise ValueError("runtime_write_set_mismatch")
                    effect_payload = runtime_transaction.get("effect")
                    patch_ref = (
                        effect_payload.get("patch_ref")
                        if isinstance(effect_payload, dict)
                        else None
                    )
                    if patch_ref is not None and patch_ref != change_digest:
                        raise ValueError("runtime_patch_ref_mismatch")
                    runtime_outcome = run_runtime_effect_transaction(
                        self.root, runtime_transaction
                    )
                except (ImportError, RuntimeError, TypeError, ValueError) as error:
                    reason_codes = [
                        "runtime_effect_transaction_rejected",
                        type(error).__name__,
                    ]
                else:
                    if runtime_outcome.get("state") == "completed":
                        after_generation, refresh_status = self._refresh_after_write()
                        receipt = {
                            "schema": SCHEMA,
                            "status": "applied",
                            "profile": PROFILE_NAMES[profile],
                            "engine": engine_receipt,
                            "engine_version": __version__,
                            "changeset": {
                                "schema": changeset["schema"],
                                "sha256": change_digest,
                            },
                            "base_generation": before_generation,
                            "result_generation": after_generation,
                            "idempotency": {
                                "key": request_key,
                                "hit": False,
                                "replayed": False,
                            },
                            "cache": {"L0_delivery": "miss", "key": request_key},
                            "ownership": {
                                "source_writer": "simplicio-dev-cli",
                                "full_effect_authority": "simplicio-runtime",
                                "mutation_applied": True,
                            },
                            "runtime": runtime_outcome,
                            "refresh": {
                                "attempted": refresh_status == "refreshed",
                                "status": refresh_status,
                            },
                            "reason_codes": [
                                "runtime_effect_completed",
                                *(
                                    ["mapper_refresh_required"]
                                    if refresh_status == "mapper_refresh_required"
                                    else []
                                ),
                            ],
                            "timings": {
                                "delivery_wall_ms": (time.perf_counter_ns() - started)
                                / 1_000_000
                            },
                        }
                        _atomic_json(result_path, receipt)
                        return receipt
            receipt = {
                "schema": SCHEMA,
                "status": "blocked",
                "profile": PROFILE_NAMES[profile],
                "engine": engine_receipt,
                "engine_version": __version__,
                "changeset": {"schema": changeset["schema"], "sha256": change_digest},
                "base_generation": before_generation,
                "idempotency": {"key": request_key, "hit": False, "replayed": False},
                "cache": {"L0_delivery": "miss", "key": request_key},
                "ownership": {
                    "source_writer": "simplicio-dev-cli",
                    "full_effect_authority": "simplicio-runtime",
                    "mutation_applied": False,
                },
                "runtime": runtime_outcome,
                "reason_codes": reason_codes,
                "timings": {
                    "delivery_wall_ms": (time.perf_counter_ns() - started) / 1_000_000
                },
            }
            _atomic_json(result_path, receipt)
            return receipt

        applied_receipt = ProjectProcessor(self.root, self.snapshot).apply_changeset(
            changeset, write=write
        )
        applied = bool(applied_receipt.get("applied"))
        after_generation = before_generation
        refresh = {"attempted": False, "status": "not-needed"}
        if write and applied:
            after_generation, refresh_status = self._refresh_after_write()
            refresh["attempted"] = refresh_status == "refreshed"
            refresh["status"] = refresh_status
        outcome = "applied" if applied else "dry_run" if not write else "refused"
        reason_codes = []
        if applied_receipt.get("reason_code"):
            reason_codes.append(str(applied_receipt["reason_code"]))
        if not applied:
            reason_codes.append("changeset_not_applied")
        receipt = {
            "schema": SCHEMA,
            "status": outcome,
            "profile": PROFILE_NAMES[profile],
            "engine": engine_receipt,
            "engine_version": __version__,
            "changeset": {
                "schema": changeset["schema"],
                "sha256": change_digest,
                "files": [change["path"] for change in changeset["changes"]],
            },
            "apply": applied_receipt,
            "base_generation": before_generation,
            "result_generation": after_generation,
            "idempotency": {"key": request_key, "hit": False, "replayed": False},
            "cache": {"L0_delivery": "miss", "key": request_key},
            "ownership": {
                "source_writer": "simplicio-dev-cli",
                "full_effect_authority": "simplicio-runtime"
                if profile == "full"
                else "local-guard",
                "mutation_applied": applied,
            },
            "refresh": refresh,
            "reason_codes": reason_codes,
            "timings": {
                "delivery_wall_ms": (time.perf_counter_ns() - started) / 1_000_000
            },
        }
        _atomic_json(result_path, receipt)
        return receipt
