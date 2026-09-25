"""Content-addressed, authority-bound context views for Prism stage agents."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .hbp_codec import seal_receipt, verify_chain


REQUEST_SCHEMA = "simplicio.fast.context-view-request/v1"
VIEW_SCHEMA = "simplicio.fast.context-view/v1"
CACHE_SCHEMA = "simplicio.fast.context-view-cache/v1"
HBP_SCHEMA = "simplicio.fast.context-view-hbp/v1"
ITEM_KINDS = {
    "fact",
    "impact",
    "span",
    "test",
    "receipt",
    "evidence",
    "diff",
    "implementer_prompt",
}
VISIBILITIES = {"shared", "implementer", "reviewer"}
_PRIORITY = {
    "evidence": 0,
    "diff": 1,
    "test": 2,
    "receipt": 3,
    "impact": 4,
    "fact": 5,
    "span": 6,
    "implementer_prompt": 7,
}
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password)\b"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")


class ContextViewError(ValueError):
    """A view crossed a safety boundary with a stable reason code."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _required_text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ContextIdentity:
    prism_id: str
    slot_id: str
    task_id: str
    attempt: int
    agent_id: str
    stage: str

    def __post_init__(self) -> None:
        for field in ("prism_id", "slot_id", "task_id", "agent_id", "stage"):
            _required_text(getattr(self, field), field)
        if not isinstance(self.attempt, int) or self.attempt < 1:
            raise ValueError("attempt must be a positive integer")

    def record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_tokens: int
    max_bytes: int
    max_nodes: int

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or value < 1
            for value in (self.max_tokens, self.max_bytes, self.max_nodes)
        ):
            raise ValueError("context budgets must be positive integers")

    def record(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextAuthority:
    principal: str
    fence: str
    capabilities: tuple[str, ...]
    allowed_roots: tuple[str, ...] = (".",)

    def __post_init__(self) -> None:
        _required_text(self.principal, "principal")
        _required_text(self.fence, "fence")
        if (
            not isinstance(self.capabilities, tuple)
            or not self.capabilities
            or any(
                not isinstance(value, str) or not value for value in self.capabilities
            )
        ):
            raise ValueError("capabilities must be a non-empty tuple")
        if (
            not isinstance(self.allowed_roots, tuple)
            or not self.allowed_roots
            or any(
                not isinstance(value, str) or not value for value in self.allowed_roots
            )
        ):
            raise ValueError("allowed_roots must be a non-empty tuple")
        for root in self.allowed_roots:
            _validate_relative_path(root, allow_dot=True)

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "simplicio.fast.context-authority/v1",
                "principal": self.principal,
                "fence": self.fence,
                "capabilities": sorted(set(self.capabilities)),
                "allowed_roots": sorted(set(self.allowed_roots)),
            }
        )

    def permits_path(self, value: str) -> bool:
        candidate = _validate_relative_path(value)
        return any(
            root == "."
            or candidate == _validate_relative_path(root, allow_dot=True)
            or candidate.startswith(
                _validate_relative_path(root, allow_dot=True).rstrip("/") + "/"
            )
            for root in self.allowed_roots
        )


@dataclass(frozen=True, slots=True)
class ContextItem:
    kind: str
    handle: str
    content: str
    source_sha256: str
    base_generation: str
    token_count: int
    path: str | None = None
    overlay_digest: str | None = None
    visibility: str = "shared"
    relevance: float = 1.0
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in ITEM_KINDS:
            raise ValueError(f"unsupported context item kind: {self.kind}")
        for field in ("handle", "base_generation", "source_sha256"):
            _required_text(getattr(self, field), field)
        if not isinstance(self.content, str):
            raise ValueError("content must be text")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError("source_sha256 must be a lowercase SHA-256")
        if not isinstance(self.token_count, int) or self.token_count < 0:
            raise ValueError("token_count must be an observed non-negative integer")
        if self.visibility not in VISIBILITIES:
            raise ValueError("visibility is invalid")
        if not isinstance(self.relevance, (int, float)) or not 0 <= self.relevance <= 1:
            raise ValueError("relevance must be between zero and one")
        if self.path is not None:
            _validate_relative_path(self.path)
        if self.overlay_digest is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.overlay_digest
        ):
            raise ValueError("overlay_digest must be a lowercase SHA-256")
        if any(not isinstance(value, str) or not value for value in self.provenance):
            raise ValueError("provenance entries must be non-empty strings")

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        handle: str,
        content: str,
        base_generation: str,
        token_count: int,
        **kwargs: Any,
    ) -> "ContextItem":
        return cls(
            kind=kind,
            handle=handle,
            content=content,
            source_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            base_generation=base_generation,
            token_count=token_count,
            **kwargs,
        )

    def record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ContextViewRequest:
    repository: str
    identity: ContextIdentity
    base_generation: str
    requested_capability: str
    goal_fragment: str
    budget: ContextBudget
    authority_digest: str
    fence: str
    overlay_digest: str | None = None
    ttl_seconds: int = 300
    schema: str = REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != REQUEST_SCHEMA:
            raise ValueError("unsupported context view request schema")
        for field in (
            "repository",
            "base_generation",
            "requested_capability",
            "goal_fragment",
            "authority_digest",
            "fence",
        ):
            _required_text(getattr(self, field), field)
        if not re.fullmatch(r"[0-9a-f]{64}", self.authority_digest):
            raise ValueError("authority_digest must be a lowercase SHA-256")
        if self.overlay_digest is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.overlay_digest
        ):
            raise ValueError("overlay_digest must be a lowercase SHA-256")
        if not isinstance(self.ttl_seconds, int) or not 1 <= self.ttl_seconds <= 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")

    def record(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "repository": self.repository,
            "identity": self.identity.record(),
            "base_generation": self.base_generation,
            "overlay_digest": self.overlay_digest,
            "requested_capability": self.requested_capability,
            "goal_fragment": self.goal_fragment,
            "budget": self.budget.record(),
            "authority_digest": self.authority_digest,
            "fence": self.fence,
            "ttl_seconds": self.ttl_seconds,
        }

    def to_hbp(self) -> str:
        return encode_hbp("request", self.record())

    @classmethod
    def from_hbp(cls, row: str) -> "ContextViewRequest":
        value = decode_hbp(row, expected_kind="request")
        try:
            return cls(
                repository=value["repository"],
                identity=ContextIdentity(**value["identity"]),
                base_generation=value["base_generation"],
                overlay_digest=value.get("overlay_digest"),
                requested_capability=value["requested_capability"],
                goal_fragment=value["goal_fragment"],
                budget=ContextBudget(**value["budget"]),
                authority_digest=value["authority_digest"],
                fence=value["fence"],
                ttl_seconds=value["ttl_seconds"],
                schema=value["schema"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ContextViewError("hbp_payload_invalid", str(error)) from error


@dataclass(frozen=True, slots=True)
class ContextView:
    handle: str
    identity: ContextIdentity
    request_hash: str
    cache_key: str
    base_generation: str
    overlay_digest: str | None
    authority_digest: str
    fence: str
    requested_capability: str
    selected: tuple[dict[str, object], ...]
    usage: dict[str, int]
    quality: dict[str, object]
    abstention: dict[str, object] | None
    cache: dict[str, object]
    provenance: dict[str, object]
    view_hash: str
    schema: str = VIEW_SCHEMA

    def unsigned_record(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "handle": self.handle,
            "identity": self.identity.record(),
            "request_hash": self.request_hash,
            "cache_key": self.cache_key,
            "base_generation": self.base_generation,
            "overlay_digest": self.overlay_digest,
            "authority_digest": self.authority_digest,
            "fence": self.fence,
            "requested_capability": self.requested_capability,
            "selected": [dict(item) for item in self.selected],
            "usage": dict(self.usage),
            "quality": dict(self.quality),
            "abstention": None if self.abstention is None else dict(self.abstention),
            "cache": dict(self.cache),
            "provenance": dict(self.provenance),
        }

    def record(self) -> dict[str, object]:
        return {**self.unsigned_record(), "view_hash": self.view_hash}

    def to_hbp(self) -> str:
        return encode_hbp("result", self.record())


def _validate_relative_path(value: str, *, allow_dot: bool = False) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or ".." in path.parts
        or (not allow_dot and normalized in {"", "."})
    ):
        raise ContextViewError("path_escape", value)
    if ":" in path.parts[0]:
        raise ContextViewError("path_escape", value)
    return path.as_posix()


def _redact(content: str) -> tuple[str, bool]:
    value, assignments = _SECRET_ASSIGNMENT.subn(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>", content
    )
    value, bearers = _BEARER.subn("Bearer <redacted>", value)
    return value, bool(assignments or bearers)


def encode_hbp(kind: str, payload: Mapping[str, object]) -> str:
    if kind not in {"request", "result"}:
        raise ValueError("HBP kind must be request or result")
    encoded = base64.urlsafe_b64encode(_canonical(dict(payload))).decode("ascii")
    return seal_receipt(f"schema={HBP_SCHEMA}|kind={kind}|payload={encoded}")


def decode_hbp(row: str, *, expected_kind: str) -> dict[str, Any]:
    if not isinstance(row, str):
        raise ContextViewError("hbp_row_invalid")
    try:
        verify_chain([row])
        body = row.rsplit("|event_hash=", 1)[0].rsplit("|prev_event_hash=", 1)[0]
        fields = dict(part.split("=", 1) for part in body.split("|"))
        if fields.get("schema") != HBP_SCHEMA or fields.get("kind") != expected_kind:
            raise ContextViewError("hbp_schema_invalid")
        payload = base64.b64decode(
            fields["payload"].encode("ascii"), altchars=b"-_", validate=True
        )
        value = json.loads(payload.decode("utf-8"))
    except ContextViewError:
        raise
    except Exception as error:
        raise ContextViewError("hbp_tampered", str(error)) from error
    if not isinstance(value, dict):
        raise ContextViewError("hbp_payload_invalid")
    return value


class ContextViewCache:
    """Bounded TTL cache with optional tamper-evident JSON persistence."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        max_entries: int = 128,
        clock: Any = time.time,
    ) -> None:
        if not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.path = None if path is None else Path(path)
        self.max_entries = max_entries
        self.clock = clock
        self._entries: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._sequence = 0
        self.metrics = {
            "lookups": 0,
            "hits": 0,
            "misses": 0,
            "expired": 0,
            "evicted": 0,
        }
        if self.path is not None and self.path.exists():
            self._load()

    def _load(self) -> None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value.get("schema") != CACHE_SCHEMA or not isinstance(
                value.get("entries"), dict
            ):
                raise ValueError("schema")
            entries: dict[str, dict[str, Any]] = {}
            for key, entry in value["entries"].items():
                payload = entry["payload"]
                checksum = entry["checksum"]
                if not hmac.compare_digest(checksum, _digest(payload)):
                    raise ValueError("checksum")
                entries[key] = dict(entry)
            self._entries = entries
            self._sequence = max(
                (int(entry.get("access_order", 0)) for entry in entries.values()),
                default=0,
            )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as error:
            raise ContextViewError("cache_tampered", str(error)) from error

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(
            _canonical({"schema": CACHE_SCHEMA, "entries": self._entries})
        )
        os.replace(temporary, self.path)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            self.metrics["lookups"] += 1
            entry = self._entries.get(key)
            if entry is None:
                self.metrics["misses"] += 1
                return None
            if float(entry["expires_at"]) <= float(self.clock()):
                self._entries.pop(key)
                self.metrics["expired"] += 1
                self.metrics["misses"] += 1
                self._persist()
                return None
            if not hmac.compare_digest(entry["checksum"], _digest(entry["payload"])):
                raise ContextViewError("cache_tampered", key)
            self._sequence += 1
            entry["last_access"] = float(self.clock())
            entry["access_order"] = self._sequence
            self.metrics["hits"] += 1
            self._persist()
            return json.loads(json.dumps(entry["payload"]))

    def put(self, key: str, payload: Mapping[str, object], ttl_seconds: int) -> None:
        with self._lock:
            now = float(self.clock())
            self._sequence += 1
            body = json.loads(json.dumps(dict(payload)))
            self._entries[key] = {
                "payload": body,
                "checksum": _digest(body),
                "expires_at": now + ttl_seconds,
                "last_access": now,
                "access_order": self._sequence,
            }
            while len(self._entries) > self.max_entries:
                victim = min(
                    self._entries,
                    key=lambda item: (
                        self._entries[item].get("access_order", 0),
                        item,
                    ),
                )
                self._entries.pop(victim)
                self.metrics["evicted"] += 1
            self._persist()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._persist()


class ContextViewService:
    """Materialize bounded views from verified Mapper-owned context items."""

    def __init__(self, cache: ContextViewCache | None = None) -> None:
        self.cache = cache or ContextViewCache()

    @staticmethod
    def _authorize(request: ContextViewRequest, authority: ContextAuthority) -> None:
        if not hmac.compare_digest(request.authority_digest, authority.digest):
            raise ContextViewError("authority_mismatch")
        if request.fence != authority.fence:
            raise ContextViewError("fence_stale")
        if request.requested_capability not in authority.capabilities:
            raise ContextViewError("capability_denied", request.requested_capability)

    @staticmethod
    def _validate_item(
        request: ContextViewRequest, authority: ContextAuthority, item: ContextItem
    ) -> None:
        if not hmac.compare_digest(
            hashlib.sha256(item.content.encode("utf-8")).hexdigest(),
            item.source_sha256,
        ):
            raise ContextViewError("item_tampered", item.handle)
        if item.base_generation != request.base_generation:
            raise ContextViewError("stale_generation", item.handle)
        if (
            item.overlay_digest is not None
            and item.overlay_digest != request.overlay_digest
        ):
            raise ContextViewError("overlay_scope_mismatch", item.handle)
        if request.overlay_digest is None and item.overlay_digest is not None:
            raise ContextViewError("overlay_scope_mismatch", item.handle)
        if item.path is not None and not authority.permits_path(item.path):
            raise ContextViewError("path_denied", item.path)

    @staticmethod
    def _visible(identity: ContextIdentity, item: ContextItem) -> bool:
        reviewer = identity.stage.casefold() == "reviewer"
        if reviewer:
            return (
                item.kind != "implementer_prompt" and item.visibility != "implementer"
            )
        return item.visibility != "reviewer"

    @staticmethod
    def _cache_key(
        request: ContextViewRequest,
        items: Sequence[ContextItem],
        input_digest: str,
    ) -> str:
        overlay_specific = any(item.overlay_digest is not None for item in items)
        scope: dict[str, object] = {
            "schema": CACHE_SCHEMA,
            "repository": request.repository,
            "base_generation": request.base_generation,
            "overlay_digest": request.overlay_digest,
            "requested_capability": request.requested_capability,
            "goal_fragment": request.goal_fragment,
            "stage": request.identity.stage,
            "budget": request.budget.record(),
            "authority_digest": request.authority_digest,
            "fence": request.fence,
            "input_digest": input_digest,
            "ttl_seconds": request.ttl_seconds,
        }
        if overlay_specific:
            scope["task_id"] = request.identity.task_id
            scope["attempt"] = request.identity.attempt
        return _digest(scope)

    def _select(
        self, request: ContextViewRequest, items: Sequence[ContextItem]
    ) -> dict[str, object]:
        eligible = [item for item in items if self._visible(request.identity, item)]
        ordered = sorted(
            eligible,
            key=lambda item: (
                _PRIORITY[item.kind],
                -float(item.relevance),
                item.handle,
            ),
        )
        selected: list[dict[str, object]] = []
        used_bytes = used_tokens = used_nodes = redactions = budget_rejections = 0
        for item in ordered:
            content, redacted = _redact(item.content)
            size = len(content.encode("utf-8"))
            if (
                used_nodes + 1 > request.budget.max_nodes
                or used_bytes + size > request.budget.max_bytes
                or used_tokens + item.token_count > request.budget.max_tokens
            ):
                budget_rejections += 1
                continue
            record = {
                "kind": item.kind,
                "handle": item.handle,
                "content": content,
                "source_sha256": item.source_sha256,
                "base_generation": item.base_generation,
                "overlay_digest": item.overlay_digest,
                "path": item.path,
                "token_count": item.token_count,
                "visibility": item.visibility,
                "relevance": item.relevance,
                "provenance": list(item.provenance),
                "redacted": redacted,
            }
            selected.append(record)
            used_bytes += size
            used_tokens += item.token_count
            used_nodes += 1
            redactions += int(redacted)
        eligible_count = len(eligible)
        coverage = 1.0 if eligible_count == 0 else used_nodes / eligible_count
        reviewer = request.identity.stage.casefold() == "reviewer"
        evidence_kinds = {"evidence", "diff", "test", "receipt"}
        evidence_count = sum(item["kind"] in evidence_kinds for item in selected)
        abstention: dict[str, object] | None = None
        if not selected:
            abstention = {
                "reason_code": "insufficient_evidence",
                "detail": "no item fit the bounded context view",
            }
        elif reviewer and evidence_count == 0:
            abstention = {
                "reason_code": "reviewer_evidence_missing",
                "detail": "reviewer view contains no evidence, diff, test or receipt",
            }
        quality = {
            "coverage": coverage,
            "eligible_nodes": eligible_count,
            "selected_nodes": used_nodes,
            "evidence_nodes": evidence_count,
            "fidelity": (
                "abstained"
                if abstention is not None
                else "complete"
                if budget_rejections == 0
                else "bounded"
            ),
            "budget_rejections": budget_rejections,
        }
        return {
            "selected": selected,
            "usage": {
                "bytes": used_bytes,
                "tokens": used_tokens,
                "nodes": used_nodes,
                "redactions": redactions,
            },
            "quality": quality,
            "abstention": abstention,
        }

    def materialize(
        self,
        request: ContextViewRequest,
        authority: ContextAuthority,
        items: Iterable[ContextItem],
    ) -> ContextView:
        if not isinstance(request, ContextViewRequest):
            raise TypeError("request must be a ContextViewRequest")
        if not isinstance(authority, ContextAuthority):
            raise TypeError("authority must be a ContextAuthority")
        self._authorize(request, authority)
        candidates = tuple(items)
        if any(not isinstance(item, ContextItem) for item in candidates):
            raise TypeError("items must contain ContextItem values")
        by_handle: dict[str, ContextItem] = {}
        for item in candidates:
            self._validate_item(request, authority, item)
            previous = by_handle.get(item.handle)
            if previous is not None and previous.record() != item.record():
                raise ContextViewError("item_handle_collision", item.handle)
            by_handle[item.handle] = item
        candidates = tuple(by_handle.values())
        normalized = sorted(
            candidates,
            key=lambda item: (
                item.kind,
                item.handle,
                item.source_sha256,
                item.overlay_digest or "",
            ),
        )
        input_digest = _digest([item.record() for item in normalized])
        cache_key = self._cache_key(request, normalized, input_digest)
        selection = self.cache.get(cache_key)
        outcome = "hit" if selection is not None else "miss"
        if selection is None:
            selection = self._select(request, normalized)
            self.cache.put(cache_key, selection, request.ttl_seconds)
        request_hash = _digest(request.record())
        selection_digest = _digest(selection)
        handle_material = {
            "schema": VIEW_SCHEMA,
            "identity": request.identity.record(),
            "request_hash": request_hash,
            "selection_digest": selection_digest,
            "authority_digest": request.authority_digest,
            "fence": request.fence,
        }
        handle = "CTX-" + _digest(handle_material)[:32]
        provenance = {
            "repository": request.repository,
            "base_generation": request.base_generation,
            "overlay_digest": request.overlay_digest,
            "input_digest": input_digest,
            "authority_principal": authority.principal,
            "authority_digest": authority.digest,
            "fence": authority.fence,
            "prism_id": request.identity.prism_id,
            "slot_id": request.identity.slot_id,
            "task_id": request.identity.task_id,
            "attempt": request.identity.attempt,
            "agent_id": request.identity.agent_id,
            "stage": request.identity.stage,
        }
        usage = dict(selection["usage"])
        cache_receipt = {
            "outcome": outcome,
            "key": cache_key,
            "bytes_reused_observed": usage["bytes"] if outcome == "hit" else 0,
            "tokens_reused_observed": usage["tokens"] if outcome == "hit" else 0,
            "token_savings": None,
            "token_savings_reason": "MODEL_TOKEN_ACCOUNTING_NOT_OBSERVED",
        }
        unsigned = {
            "schema": VIEW_SCHEMA,
            "handle": handle,
            "identity": request.identity.record(),
            "request_hash": request_hash,
            "cache_key": cache_key,
            "base_generation": request.base_generation,
            "overlay_digest": request.overlay_digest,
            "authority_digest": request.authority_digest,
            "fence": request.fence,
            "requested_capability": request.requested_capability,
            "selected": selection["selected"],
            "usage": usage,
            "quality": selection["quality"],
            "abstention": selection["abstention"],
            "cache": cache_receipt,
            "provenance": provenance,
        }
        return ContextView(
            handle=handle,
            identity=request.identity,
            request_hash=request_hash,
            cache_key=cache_key,
            base_generation=request.base_generation,
            overlay_digest=request.overlay_digest,
            authority_digest=request.authority_digest,
            fence=request.fence,
            requested_capability=request.requested_capability,
            selected=tuple(dict(item) for item in selection["selected"]),
            usage=usage,
            quality=dict(selection["quality"]),
            abstention=(
                None
                if selection["abstention"] is None
                else dict(selection["abstention"])
            ),
            cache=cache_receipt,
            provenance=provenance,
            view_hash=_digest(unsigned),
        )


def verify_context_view(
    view: ContextView | Mapping[str, object],
    *,
    request: ContextViewRequest,
    authority: ContextAuthority,
) -> dict[str, object]:
    value = view.record() if isinstance(view, ContextView) else dict(view)
    if value.get("schema") != VIEW_SCHEMA:
        raise ContextViewError("view_schema_invalid")
    supplied = value.pop("view_hash", None)
    if not isinstance(supplied, str) or not hmac.compare_digest(
        supplied, _digest(value)
    ):
        raise ContextViewError("view_tampered")
    expected = {
        "request_hash": _digest(request.record()),
        "base_generation": request.base_generation,
        "overlay_digest": request.overlay_digest,
        "authority_digest": authority.digest,
        "fence": authority.fence,
        "requested_capability": request.requested_capability,
        "identity": request.identity.record(),
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise ContextViewError(f"view_{field}_mismatch")
    handle = value.get("handle")
    if not isinstance(handle, str) or not handle.startswith("CTX-"):
        raise ContextViewError("view_handle_invalid")
    return {**value, "view_hash": supplied}


def verify_context_view_hbp(
    row: str,
    *,
    request: ContextViewRequest,
    authority: ContextAuthority,
) -> dict[str, object]:
    return verify_context_view(
        decode_hbp(row, expected_kind="result"), request=request, authority=authority
    )


__all__ = [
    "CACHE_SCHEMA",
    "HBP_SCHEMA",
    "REQUEST_SCHEMA",
    "VIEW_SCHEMA",
    "ContextAuthority",
    "ContextBudget",
    "ContextIdentity",
    "ContextItem",
    "ContextView",
    "ContextViewCache",
    "ContextViewError",
    "ContextViewRequest",
    "ContextViewService",
    "decode_hbp",
    "encode_hbp",
    "verify_context_view",
    "verify_context_view_hbp",
]
