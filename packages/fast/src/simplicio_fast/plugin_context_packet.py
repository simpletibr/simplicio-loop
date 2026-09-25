"""Read-only Plugin v1 ABI for pinned ContextPackets and generations.

Fast exposes existing snapshot/generation/hash-guard state through a stable
envelope. It does not own source-of-truth, decide policy, or mutate files.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from .hbp_codec import seal_receipt, verify_chain


PACKET_SCHEMA = "simplicio.plugin.context-packet/v1"
HANDLE_SCHEMA = "simplicio.plugin.context-handle/v1"
REQUEST_SCHEMA = "simplicio.plugin.context-request/v1"
MANIFEST_SCHEMA = "simplicio.plugin.context-packet-manifest/v1"
HBP_SCHEMA = "simplicio.plugin.context-packet-hbp/v1"
ABI_MAJOR = 1
ABI_MINOR = 0
FIDELITIES = frozenset({"metadata", "summary", "exact"})
PRIVATE_FIELDS = frozenset({"offset", "mmap_offset", "address", "pointer"})
MAX_ENCODED_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 100_000
MAX_TEXT = 4096
SUMMARY_CHARS = 160


class PluginContextError(ValueError):
    """Fail-closed Plugin context ABI error with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _canonical(value: Any) -> bytes:
    _reject_private_fields(value)
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise PluginContextError("payload_not_json") from error


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hex_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_private_fields(value: Any, *, depth: int = 0, items: list[int] | None = None) -> None:
    if depth > 32:
        raise PluginContextError("payload_depth_limit")
    if items is None:
        items = [0]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise PluginContextError("payload_not_json")
        if PRIVATE_FIELDS.intersection(value):
            raise PluginContextError("private_layout_field")
        items[0] += len(value)
        if items[0] > MAX_ITEMS:
            raise PluginContextError("payload_item_limit")
        for child in value.values():
            _reject_private_fields(child, depth=depth + 1, items=items)
    elif isinstance(value, (list, tuple)):
        items[0] += len(value)
        if items[0] > MAX_ITEMS:
            raise PluginContextError("payload_item_limit")
        for child in value:
            _reject_private_fields(child, depth=depth + 1, items=items)
    elif isinstance(value, str) and len(value) > MAX_TEXT:
        raise PluginContextError("payload_text_limit")


def _required_text(value: object, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PluginContextError(reason)
    return value


def _positive_int(value: object, reason: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PluginContextError(reason)
    return value


def validate_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PluginContextError("path_escape", str(value))
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or normalized in {"", "."}:
        raise PluginContextError("path_escape", value)
    if path.parts and ":" in path.parts[0]:
        raise PluginContextError("path_escape", value)
    return path.as_posix()


def negotiate_abi(requested: Mapping[str, Any] | None = None) -> dict[str, int]:
    """Accept Plugin v1 and reject unknown majors without silent coercion."""
    if requested is None:
        return {"major": ABI_MAJOR, "minor": ABI_MINOR}
    if not isinstance(requested, Mapping):
        raise PluginContextError("plugin_abi_unsupported")
    major = requested.get("major", ABI_MAJOR)
    minor = requested.get("minor", 0)
    if isinstance(major, bool) or not isinstance(major, int) or major != ABI_MAJOR:
        raise PluginContextError("plugin_abi_unsupported", str(major))
    if isinstance(minor, bool) or not isinstance(minor, int) or minor < 0:
        raise PluginContextError("plugin_abi_unsupported", str(minor))
    return {"major": ABI_MAJOR, "minor": min(minor, ABI_MINOR) if minor else ABI_MINOR}


def contract_manifest() -> dict[str, Any]:
    return {
        "schema": MANIFEST_SCHEMA,
        "packet_schema": PACKET_SCHEMA,
        "handle_schema": HANDLE_SCHEMA,
        "request_schema": REQUEST_SCHEMA,
        "hbp_schema": HBP_SCHEMA,
        "abi": {"major": ABI_MAJOR, "minor": ABI_MINOR},
        "fidelities": sorted(FIDELITIES),
        "authority": "derived_read_only",
        "writes": False,
        "instructions": False,
        "private_layout_fields": "reject",
        "unknown_major": "reject",
        "reason_codes": [
            "budget_invalid",
            "cancellation_requested",
            "generation_missing",
            "generation_stale",
            "generation_tampered",
            "handle_missing",
            "handle_stale",
            "handle_tampered",
            "overlay_escape",
            "packet_corrupt",
            "packet_schema_invalid",
            "path_escape",
            "payload_not_json",
            "plugin_abi_unsupported",
            "plugin_schema_unsupported",
            "private_layout_field",
            "source_hash_mismatch",
            "slice_missing",
        ],
    }


@dataclass(frozen=True, slots=True)
class PluginContextHandle:
    handle: str
    generation: str
    source_ref: str
    overlay_id: str | None = None
    digest: str = ""

    def __post_init__(self) -> None:
        _required_text(self.handle, "handle_missing")
        _required_text(self.generation, "generation_missing")
        _required_text(self.source_ref, "handle_tampered")
        if self.overlay_id is not None:
            _required_text(self.overlay_id, "overlay_escape")
        expected = _digest(self.identity())
        if self.digest:
            if self.digest != expected:
                raise PluginContextError("handle_tampered", self.handle)
        else:
            object.__setattr__(self, "digest", expected)

    def identity(self) -> dict[str, Any]:
        return {
            "schema": HANDLE_SCHEMA,
            "handle": self.handle,
            "generation": self.generation,
            "source_ref": self.source_ref,
            "overlay_id": self.overlay_id,
        }

    def to_dict(self) -> dict[str, Any]:
        body = self.identity()
        body["digest"] = self.digest
        return body

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PluginContextHandle":
        if not isinstance(value, Mapping):
            raise PluginContextError("handle_missing")
        schema = value.get("schema", HANDLE_SCHEMA)
        if schema != HANDLE_SCHEMA:
            raise PluginContextError("plugin_schema_unsupported", str(schema))
        return cls(
            handle=_required_text(value.get("handle"), "handle_missing"),
            generation=_required_text(value.get("generation"), "generation_missing"),
            source_ref=_required_text(value.get("source_ref"), "handle_tampered"),
            overlay_id=value.get("overlay_id"),
            digest=str(value.get("digest") or ""),
        )


@dataclass(frozen=True, slots=True)
class PluginContextBudget:
    max_bytes: int
    max_items: int
    max_span_bytes: int
    fidelity: str = "exact"

    def __post_init__(self) -> None:
        _positive_int(self.max_bytes, "budget_invalid")
        _positive_int(self.max_items, "budget_invalid")
        _positive_int(self.max_span_bytes, "budget_invalid")
        if self.fidelity not in FIDELITIES:
            raise PluginContextError("budget_invalid", self.fidelity)
        if self.max_bytes > MAX_ENCODED_BYTES or self.max_items > MAX_ITEMS:
            raise PluginContextError("budget_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_bytes": self.max_bytes,
            "max_items": self.max_items,
            "max_span_bytes": self.max_span_bytes,
            "fidelity": self.fidelity,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PluginContextBudget":
        if value is None:
            return cls(max_bytes=65536, max_items=64, max_span_bytes=4096, fidelity="exact")
        if not isinstance(value, Mapping):
            raise PluginContextError("budget_invalid")
        return cls(
            max_bytes=int(value.get("max_bytes", 65536)),
            max_items=int(value.get("max_items", 64)),
            max_span_bytes=int(value.get("max_span_bytes", 4096)),
            fidelity=str(value.get("fidelity", "exact")),
        )


@dataclass(frozen=True, slots=True)
class PluginContextSpan:
    handle: str
    path: str
    kind: str
    start_line: int
    end_line: int
    source_sha256: str
    byte_length: int
    text: str | None
    overlay_id: str | None = None
    requested_start_line: int | None = None
    requested_end_line: int | None = None
    start_byte: int = 0
    end_byte: int = 0
    content_sha256: str = ""
    fidelity: str = "complete"
    omitted_ranges: tuple[tuple[int, int], ...] = ()
    needs_broader_context: bool = False

    def to_dict(self) -> dict[str, Any]:
        body = {
            "handle": self.handle,
            "path": self.path,
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "source_sha256": self.source_sha256,
            "byte_length": self.byte_length,
            "text": self.text,
            "overlay_id": self.overlay_id,
        }
        # Keep complete-span packets wire compatible.  The extra range and
        # content identity fields are required when a budget cuts a span.
        if self.fidelity != "complete" or self.omitted_ranges or self.needs_broader_context:
            body.update(
                {
                    "requested_start_line": self.requested_start_line,
                    "requested_end_line": self.requested_end_line,
                    "start_byte": self.start_byte,
                    "end_byte": self.end_byte,
                    "content_sha256": self.content_sha256,
                    "fidelity": self.fidelity,
                    "omitted_ranges": [list(item) for item in self.omitted_ranges],
                    "needs_broader_context": self.needs_broader_context,
                }
            )
        return body


@dataclass(frozen=True, slots=True)
class PluginContextRequest:
    task_id: str
    session_id: str
    handle: PluginContextHandle
    budget: PluginContextBudget
    requested_handles: tuple[str, ...] = ()
    expected_source_hashes: Mapping[str, str] | None = None
    cancelled: Callable[[], bool] | None = None
    abi: Mapping[str, int] | None = None

    def __post_init__(self) -> None:
        _required_text(self.task_id, "handle_missing")
        _required_text(self.session_id, "handle_missing")
        if not isinstance(self.handle, PluginContextHandle):
            raise PluginContextError("handle_missing")
        if not isinstance(self.budget, PluginContextBudget):
            raise PluginContextError("budget_invalid")
        handles = tuple(self.requested_handles or ())
        if any(not isinstance(item, str) or not item for item in handles):
            raise PluginContextError("handle_missing")
        object.__setattr__(self, "requested_handles", handles)
        negotiate_abi(self.abi)


@dataclass(frozen=True, slots=True)
class _SpanRecord:
    handle: str
    path: str
    kind: str
    start_line: int
    end_line: int
    start_offset: int
    end_offset: int


@dataclass
class _GenerationRecord:
    generation: str
    repo: str
    commit: str
    files: dict[str, memoryview]
    hashes: dict[str, str]
    spans: dict[str, _SpanRecord]
    digest: str


def _span_text(blob: memoryview, record: _SpanRecord) -> bytes:
    return bytes(blob[record.start_offset : record.end_offset])


def _line_span(data: bytes) -> tuple[int, int, int, int]:
    if not data:
        return 1, 1, 0, 0
    return 1, data.count(b"\n") + (0 if data.endswith(b"\n") else 1), 0, len(data)


class PluginContextStore:
    """Pinned generations with isolated overlays and a content-addressed cache."""

    def __init__(self) -> None:
        self._generations: dict[str, _GenerationRecord] = {}
        self._overlays: dict[tuple[str, str], dict[str, bytes | None]] = {}
        self._pins: dict[tuple[str, str], str] = {}
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_deps: dict[str, set[str]] = {}
        self._lock = threading.RLock()
        self.metrics: Counter[str] = Counter()

    def load_generation(
        self,
        *,
        generation: str,
        repo: str,
        commit: str,
        files: Mapping[str, bytes],
        spans: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> str:
        _required_text(generation, "generation_missing")
        _required_text(repo, "generation_tampered")
        _required_text(commit, "generation_tampered")
        if not isinstance(files, Mapping) or not files:
            raise PluginContextError("generation_missing", "files")
        stored: dict[str, memoryview] = {}
        hashes: dict[str, str] = {}
        for raw_path, payload in files.items():
            path = validate_relative_path(str(raw_path))
            if not isinstance(payload, (bytes, bytearray, memoryview)):
                raise PluginContextError("generation_tampered", path)
            blob = bytes(payload)
            stored[path] = memoryview(blob)
            hashes[path] = _hex_digest(blob)
        index = self._index_spans(stored, spans)
        digest = _digest(
            {
                "generation": generation,
                "repo": repo,
                "commit": commit,
                "hashes": hashes,
                "handles": sorted(index),
            }
        )
        record = _GenerationRecord(
            generation=generation,
            repo=repo,
            commit=commit,
            files=stored,
            hashes=hashes,
            spans=index,
            digest=digest,
        )
        with self._lock:
            existing = self._generations.get(generation)
            if existing is not None and existing.digest != digest:
                raise PluginContextError("generation_tampered", generation)
            self._generations[generation] = record
        return digest

    def load_tree(
        self,
        *,
        generation: str,
        repo: str,
        commit: str,
        root: str | Path,
    ) -> str:
        base = Path(root).resolve()
        if not base.is_dir():
            raise PluginContextError("generation_missing", str(root))
        files: dict[str, bytes] = {}
        for path in sorted(base.rglob("*")):
            if path.is_dir():
                continue
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(base)
            except ValueError as error:
                raise PluginContextError("path_escape", str(path)) from error
            if path.is_symlink() and resolved.parent != path.parent:
                try:
                    resolved.relative_to(base)
                except ValueError as error:
                    raise PluginContextError("path_escape", str(path)) from error
            files[relative.as_posix()] = resolved.read_bytes()
        return self.load_generation(
            generation=generation, repo=repo, commit=commit, files=files
        )

    def pin(self, task_id: str, session_id: str, generation: str) -> str:
        _required_text(task_id, "handle_missing")
        _required_text(session_id, "handle_missing")
        _required_text(generation, "generation_missing")
        with self._lock:
            if generation not in self._generations:
                raise PluginContextError("generation_missing", generation)
            key = (task_id, session_id)
            current = self._pins.get(key)
            if current is not None and current != generation:
                raise PluginContextError("generation_stale", current)
            self._pins[key] = generation
        return generation

    def apply_overlay(
        self,
        generation: str,
        overlay_id: str,
        files: Mapping[str, bytes | None],
    ) -> str:
        _required_text(generation, "generation_missing")
        _required_text(overlay_id, "overlay_escape")
        with self._lock:
            if generation not in self._generations:
                raise PluginContextError("generation_missing", generation)
            overlay = self._overlays.setdefault((generation, overlay_id), {})
            for raw_path, payload in files.items():
                path = validate_relative_path(str(raw_path))
                if payload is not None and not isinstance(payload, (bytes, bytearray)):
                    raise PluginContextError("overlay_escape", path)
                overlay[path] = None if payload is None else bytes(payload)
            return _digest(
                {
                    path: None if blob is None else _hex_digest(blob)
                    for path, blob in sorted(overlay.items())
                }
            )

    def compile(self, request: PluginContextRequest) -> dict[str, Any]:
        started = time.perf_counter_ns()
        self._raise_if_cancelled(request)
        negotiate_abi(request.abi)
        with self._lock:
            pinned = self._pins.get((request.task_id, request.session_id))
            if pinned is None:
                raise PluginContextError("generation_missing", "unpinned")
            if pinned != request.handle.generation:
                raise PluginContextError("generation_stale", request.handle.generation)
            record = self._generations.get(pinned)
            if record is None:
                raise PluginContextError("generation_missing", pinned)
            overlay_id = request.handle.overlay_id
            view_files, view_hashes = self._materialize_view(record, overlay_id)
            if request.expected_source_hashes is not None:
                expected = {
                    validate_relative_path(path): digest
                    for path, digest in request.expected_source_hashes.items()
                }
                if expected != {path: view_hashes[path] for path in expected}:
                    raise PluginContextError("source_hash_mismatch")
            cache_key = _digest(
                {
                    "task_id": request.task_id,
                    "session_id": request.session_id,
                    "handle": request.handle.to_dict(),
                    "budget": request.budget.to_dict(),
                    "requested": list(request.requested_handles),
                    "generation": record.digest,
                    "hashes": view_hashes,
                }
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                self.metrics["warm"] += 1
                self.metrics["hit"] += 1
                packet = dict(cached)
                packet["cache_status"] = "warm"
                return packet
            self._raise_if_cancelled(request)
            selected = self._select_handles(record, request)
            spans, truncated, reasons = self._bound_spans(
                record, view_files, selected, request.budget, overlay_id
            )
            payload = self._payload(spans, request.budget.fidelity)
            body = {
                "schema": PACKET_SCHEMA,
                "abi": {"major": ABI_MAJOR, "minor": ABI_MINOR},
                "task_id": request.task_id,
                "session_id": request.session_id,
                "handle": request.handle.to_dict(),
                "generation": record.generation,
                "base_generation": record.generation,
                "overlay_id": overlay_id,
                "repo": record.repo,
                "source_ref": request.handle.source_ref,
                "source_hashes": {
                    span["path"]: span["source_sha256"] for span in spans
                },
                "generation_digest": record.digest,
                "spans": spans,
                "payload": payload,
                "provenance": {
                    "producer": "simplicio-fast",
                    "authority": "derived_read_only",
                    "mapper_handle": request.handle.handle,
                    "writes": False,
                    "instructions": False,
                },
                "cache_status": "cold",
                "truncated": truncated,
                "truncation_reasons": reasons,
                "completeness": "partial" if truncated else "complete",
                "fidelity": request.budget.fidelity,
                "budget": request.budget.to_dict(),
            }
            encoded = _canonical(body)
            while len(encoded) > request.budget.max_bytes and body["spans"]:
                body["spans"] = body["spans"][:-1]
                body["payload"] = self._payload(body["spans"], request.budget.fidelity)
                body["truncated"] = True
                body["truncation_reasons"] = sorted(set(reasons + ["byte_budget"]))
                body["completeness"] = "partial"
                encoded = _canonical(body)
            if len(encoded) > request.budget.max_bytes:
                raise PluginContextError("budget_invalid", "packet exceeds max_bytes")
            body["encoded_bytes"] = len(encoded)
            body["packet_hash"] = _digest(body)
            self._cache[cache_key] = dict(body)
            self._cache_deps[cache_key] = set(body["source_hashes"])
            self.metrics["cold"] += 1
            self.metrics["miss"] += 1
            self.metrics["compile_ns"] += time.perf_counter_ns() - started
            self.metrics["bytes"] += body["encoded_bytes"]
            return dict(body)

    def slice(self, packet: Mapping[str, Any], handle: str) -> dict[str, Any]:
        verified = verify_packet(packet)
        for span in verified["spans"]:
            if span["handle"] == handle:
                return dict(span)
        raise PluginContextError("slice_missing", handle)

    def invalidate(self, changed: Sequence[str]) -> list[str]:
        doomed: list[str] = []
        changed_paths = {validate_relative_path(item) for item in changed}
        with self._lock:
            for key, deps in list(self._cache_deps.items()):
                if deps.intersection(changed_paths):
                    self._cache.pop(key, None)
                    self._cache_deps.pop(key, None)
                    doomed.append(key)
            self.metrics["invalidation"] += len(doomed)
        return sorted(doomed)

    def cache_receipt(self) -> dict[str, Any]:
        return {
            "schema": "simplicio.plugin.context-cache/v1",
            "hit": int(self.metrics["hit"]),
            "miss": int(self.metrics["miss"]),
            "cold": int(self.metrics["cold"]),
            "warm": int(self.metrics["warm"]),
            "invalidation": int(self.metrics["invalidation"]),
            "bytes": int(self.metrics["bytes"]),
        }

    def _index_spans(
        self,
        files: Mapping[str, memoryview],
        spans: Mapping[str, Mapping[str, Any]] | None,
    ) -> dict[str, _SpanRecord]:
        index: dict[str, _SpanRecord] = {}
        if spans:
            for handle, spec in spans.items():
                _required_text(handle, "handle_missing")
                path = validate_relative_path(str(spec.get("path", "")))
                if path not in files:
                    raise PluginContextError("slice_missing", path)
                blob = files[path]
                start = int(spec.get("start_offset", 0))
                end = int(spec.get("end_offset", len(blob)))
                if start < 0 or end < start or end > len(blob):
                    raise PluginContextError("slice_missing", handle)
                index[handle] = _SpanRecord(
                    handle=handle,
                    path=path,
                    kind=str(spec.get("kind", "file")),
                    start_line=int(spec.get("start_line", 1)),
                    end_line=int(spec.get("end_line", 1)),
                    start_offset=start,
                    end_offset=end,
                )
            return index
        for path, blob in files.items():
            start_line, end_line, start, end = _line_span(bytes(blob))
            handle = f"plugin:{path}"
            index[handle] = _SpanRecord(
                handle=handle,
                path=path,
                kind="file",
                start_line=start_line,
                end_line=end_line,
                start_offset=start,
                end_offset=end,
            )
        return index

    def _materialize_view(
        self,
        record: _GenerationRecord,
        overlay_id: str | None,
    ) -> tuple[dict[str, memoryview], dict[str, str]]:
        files = dict(record.files)
        hashes = dict(record.hashes)
        if overlay_id is None:
            return files, hashes
        overlay = self._overlays.get((record.generation, overlay_id))
        if overlay is None:
            raise PluginContextError("overlay_escape", overlay_id)
        for path, payload in overlay.items():
            if payload is None:
                files.pop(path, None)
                hashes.pop(path, None)
                continue
            files[path] = memoryview(payload)
            hashes[path] = _hex_digest(payload)
        return files, hashes

    def _select_handles(
        self,
        record: _GenerationRecord,
        request: PluginContextRequest,
    ) -> list[str]:
        if request.requested_handles:
            missing = [item for item in request.requested_handles if item not in record.spans]
            if missing:
                raise PluginContextError("handle_missing", missing[0])
            return list(request.requested_handles)
        if request.handle.handle in record.spans:
            return [request.handle.handle]
        if request.budget.fidelity == "metadata":
            return sorted(record.spans)
        raise PluginContextError("handle_missing", request.handle.handle)

    def _bound_spans(
        self,
        record: _GenerationRecord,
        files: Mapping[str, memoryview],
        handles: Sequence[str],
        budget: PluginContextBudget,
        overlay_id: str | None,
    ) -> tuple[list[dict[str, Any]], bool, list[str]]:
        spans: list[dict[str, Any]] = []
        reasons: list[str] = []
        used = 0
        for handle in handles:
            if len(spans) >= budget.max_items:
                reasons.append("item_budget")
                break
            spec = record.spans.get(handle)
            if spec is None:
                raise PluginContextError("handle_missing", handle)
            blob = files.get(spec.path)
            if blob is None:
                raise PluginContextError("slice_missing", spec.path)
            text = _span_text(blob, spec)
            truncated = False
            if len(text) > budget.max_span_bytes:
                text = text[: budget.max_span_bytes]
                reasons.append("span_budget")
                truncated = True
            rendered = None
            if budget.fidelity == "exact":
                rendered = text.decode("utf-8", "replace")
            elif budget.fidelity == "summary":
                rendered = text[:SUMMARY_CHARS].decode("utf-8", "replace")
            payload_bytes = 0 if rendered is None else len(rendered.encode("utf-8"))
            if used + payload_bytes > budget.max_bytes:
                reasons.append("byte_budget")
                break
            used += payload_bytes
            spans.append(
                PluginContextSpan(
                    handle=handle,
                    path=spec.path,
                    kind=spec.kind,
                    start_line=spec.start_line,
                    end_line=(
                        spec.start_line + text.count(b"\n") - 1
                        if text.endswith(b"\n") and text
                        else spec.start_line + text.count(b"\n")
                    ),
                    source_sha256=_hex_digest(bytes(blob)),
                    byte_length=len(text),
                    text=rendered,
                    overlay_id=overlay_id,
                    requested_start_line=spec.start_line,
                    requested_end_line=spec.end_line,
                    start_byte=spec.start_offset,
                    end_byte=spec.start_offset + len(text),
                    content_sha256=_hex_digest(text),
                    fidelity="partial" if truncated else "complete",
                    omitted_ranges=(
                        (
                            (
                                spec.start_line + text.count(b"\n"),
                                spec.end_line,
                            ),
                        )
                        if truncated and text
                        else ()
                    ),
                    needs_broader_context=truncated,
                ).to_dict()
            )
        return spans, bool(reasons), sorted(set(reasons))

    def _payload(self, spans: Sequence[Mapping[str, Any]], fidelity: str) -> dict[str, Any]:
        if fidelity == "metadata":
            return {
                "handles": [span["handle"] for span in spans],
                "paths": [span["path"] for span in spans],
                "source_hashes": [span["source_sha256"] for span in spans],
            }
        if fidelity == "summary":
            return {
                "items": [
                    {
                        "handle": span["handle"],
                        "path": span["path"],
                        "byte_length": span["byte_length"],
                        "preview": span["text"],
                    }
                    for span in spans
                ]
            }
        return {"spans": [dict(span) for span in spans]}

    @staticmethod
    def _raise_if_cancelled(request: PluginContextRequest) -> None:
        if request.cancelled is not None and request.cancelled():
            raise PluginContextError("cancellation_requested")


def verify_packet(
    packet: Mapping[str, Any],
    *,
    expected_generation: str | None = None,
) -> dict[str, Any]:
    if not isinstance(packet, Mapping) or packet.get("schema") != PACKET_SCHEMA:
        raise PluginContextError("packet_schema_invalid")
    unsigned = dict(packet)
    supplied = unsigned.pop("packet_hash", "")
    if supplied != _digest(unsigned):
        raise PluginContextError("packet_corrupt", str(supplied))
    if expected_generation is not None and packet.get("generation") != expected_generation:
        raise PluginContextError("generation_stale", str(packet.get("generation")))
    provenance = packet.get("provenance")
    if not isinstance(provenance, Mapping) or provenance.get("writes") is not False:
        raise PluginContextError("packet_corrupt", "writes")
    if provenance.get("authority") != "derived_read_only":
        raise PluginContextError("packet_corrupt", "authority")
    _reject_private_fields(packet.get("payload"))
    return dict(packet)


def encode_hbp(packet: Mapping[str, Any]) -> str:
    verified = verify_packet(packet)
    encoded = base64.urlsafe_b64encode(_canonical(verified)).decode("ascii")
    return seal_receipt(
        f"schema={HBP_SCHEMA}|kind=packet|digest={verified['packet_hash']}|payload={encoded}"
    )


def decode_hbp(row: str) -> dict[str, Any]:
    if not isinstance(row, str) or not row:
        raise PluginContextError("packet_corrupt", "hbp")
    verify_chain([row])
    body = row.rsplit("|event_hash=", 1)[0].rsplit("|prev_event_hash=", 1)[0]
    fields = dict(part.split("=", 1) for part in body.split("|"))
    if fields.get("schema") != HBP_SCHEMA or fields.get("kind") != "packet":
        raise PluginContextError("plugin_schema_unsupported", str(fields.get("schema")))
    payload = base64.b64decode(fields["payload"].encode("ascii"), altchars=b"-_", validate=True)
    packet = json.loads(payload.decode("utf-8"))
    verified = verify_packet(packet)
    if verified["packet_hash"] != fields.get("digest"):
        raise PluginContextError("packet_corrupt", "hbp_digest")
    return verified


def measure_compile(
    store: PluginContextStore,
    request: PluginContextRequest,
    *,
    iterations: int = 21,
) -> dict[str, Any]:
    """Record raw compile latency. RSS is omitted when the OS cannot measure it."""
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise PluginContextError("budget_invalid", "iterations")
    timings: list[int] = []
    packet = None
    for _ in range(iterations):
        started = time.perf_counter_ns()
        packet = store.compile(request)
        timings.append(time.perf_counter_ns() - started)
    ordered = sorted(timings)
    rss = _rss_kib()
    return {
        "schema": "simplicio.plugin.context-packet-benchmark/v1",
        "iterations": iterations,
        "p50_ns": ordered[len(ordered) // 2],
        "p95_ns": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "p99_ns": ordered[max(0, int(len(ordered) * 0.99) - 1)],
        "raw_ns": timings,
        "encoded_bytes": None if packet is None else packet["encoded_bytes"],
        "rss_kib": rss,
        "rss_kib_null_reason": None if rss is not None else "RSS_UNAVAILABLE",
    }


def _rss_kib() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage)


__all__ = [
    "ABI_MAJOR",
    "ABI_MINOR",
    "HANDLE_SCHEMA",
    "HBP_SCHEMA",
    "PACKET_SCHEMA",
    "PluginContextBudget",
    "PluginContextError",
    "PluginContextHandle",
    "PluginContextRequest",
    "PluginContextStore",
    "contract_manifest",
    "decode_hbp",
    "encode_hbp",
    "measure_compile",
    "negotiate_abi",
    "validate_relative_path",
    "verify_packet",
]
