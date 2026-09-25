"""Provider-neutral bounded compiler for Code, Knowledge and Operations facts."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Mapping, Sequence

from .projection import ProjectionEnvelope
from .tokenizers import resolve_tokenizer


CONTEXT_SCHEMA = "simplicio.fast.universal-context/v1"
_TRUST_RANK = {
    "untrusted": 0,
    "derived_fact": 1,
    "advisory": 2,
    "verified": 3,
    "authoritative": 4,
}


class UniversalContextError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _tokens(value: Any, tokenizer: Callable[[str], int] | None = None) -> int:
    if tokenizer is None:
        return len(str(value).split())
    text = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    try:
        count = tokenizer(text)
    except Exception as error:
        raise UniversalContextError("context_tokenizer_failed") from error
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise UniversalContextError("context_tokenizer_invalid")
    return count


def compile_context(
    projections: Sequence[ProjectionEnvelope],
    *,
    repository_scope: str | None = None,
    tenant_scope: str | None = None,
    max_bytes: int = 256 * 1024,
    max_tokens: int = 4096,
    max_items: int = 128,
    domain_caps: Mapping[str, int] | None = None,
    wrapper_bytes: int = 0,
    wrapper_tokens: int = 0,
    trust_floor: str | None = None,
    tokenizer_id: str | None = None,
    tokenizer: Callable[[str], int] | None = None,
) -> dict[str, Any]:
    """Compile a deterministic context packet; inputs remain immutable."""
    if not isinstance(projections, (tuple, list)) or any(
        not isinstance(item, ProjectionEnvelope) for item in projections
    ):
        raise UniversalContextError("context_projections_invalid")
    for value in (repository_scope, tenant_scope):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise UniversalContextError("context_scope_invalid")
    if domain_caps is not None and not isinstance(domain_caps, Mapping):
        raise UniversalContextError("context_domain_budget_invalid")
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes <= 0
        or isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or max_tokens <= 0
        or isinstance(max_items, bool)
        or not isinstance(max_items, int)
        or max_items <= 0
        or isinstance(wrapper_bytes, bool)
        or not isinstance(wrapper_bytes, int)
        or wrapper_bytes < 0
        or isinstance(wrapper_tokens, bool)
        or not isinstance(wrapper_tokens, int)
        or wrapper_tokens < 0
        or wrapper_bytes > max_bytes
        or wrapper_tokens > max_tokens
    ):
        raise UniversalContextError("context_budget_invalid")
    if domain_caps is not None and any(
        not isinstance(key, str)
        or not key
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for key, value in domain_caps.items()
    ):
        raise UniversalContextError("context_domain_budget_invalid")
    if trust_floor is not None and trust_floor not in _TRUST_RANK:
        raise UniversalContextError("context_trust_invalid")
    if tokenizer_id is not None and (
        not isinstance(tokenizer_id, str) or not tokenizer_id.strip()
    ):
        raise UniversalContextError("context_tokenizer_invalid")
    if tokenizer is not None and (not callable(tokenizer) or not tokenizer_id):
        raise UniversalContextError("context_tokenizer_invalid")
    resolved_tokenizer = tokenizer or resolve_tokenizer(tokenizer_id)
    effective_tokenizer_id = tokenizer_id or "estimated:word-split-v1"
    selected: list[dict[str, Any]] = []
    reasons: list[str] = []
    rejected: list[dict[str, str]] = []
    domain_counts: dict[str, int] = {}
    source_tokens = 0
    source_bytes = 0
    token_total = wrapper_tokens
    byte_total = wrapper_bytes
    ordered = sorted(projections, key=lambda item: (item.projection_type, item.stable_handle))
    seen: dict[str, str] = {}
    for envelope in ordered:
        if repository_scope is not None:
            payload_repository = envelope.payload.get("repository")
            metadata_matches = envelope.repository_scope in {"*", repository_scope}
            payload_matches = payload_repository in {None, repository_scope}
            metadata_bound = envelope.repository_scope != "*"
            payload_bound = payload_repository is not None
            if (
                not metadata_matches
                or not payload_matches
                or not (metadata_bound or payload_bound)
            ):
                raise UniversalContextError("context_scope_mismatch")
        if tenant_scope is not None:
            payload_tenant = envelope.payload.get("tenant")
            metadata_matches = envelope.tenant_scope in {"*", tenant_scope}
            payload_matches = payload_tenant in {None, tenant_scope}
            metadata_bound = envelope.tenant_scope != "*"
            payload_bound = payload_tenant is not None
            if (
                not metadata_matches
                or not payload_matches
                or not (metadata_bound or payload_bound)
            ):
                raise UniversalContextError("context_scope_mismatch")
        previous_digest = seen.get(envelope.stable_handle)
        if previous_digest is not None:
            if previous_digest != envelope.payload_sha256:
                raise UniversalContextError("context_conflict")
            rejected.append({"stable_handle": envelope.stable_handle, "reason": "duplicate"})
            continue
        seen[envelope.stable_handle] = envelope.payload_sha256
        domain = envelope.domain_scope if envelope.domain_scope != "*" else envelope.projection_type
        if domain_caps is not None and domain in domain_caps and domain_counts.get(domain, 0) >= domain_caps[domain]:
            reasons.append("domain_budget")
            rejected.append({"stable_handle": envelope.stable_handle, "reason": "domain_budget"})
            continue
        item = {
            "projection_type": envelope.projection_type,
            "stable_handle": envelope.stable_handle,
            "generation": envelope.generation,
            "source_generation": envelope.source_generation,
            "projection_generation": envelope.projection_generation,
            "producer": envelope.producer,
            "digest": envelope.payload_sha256,
            "trust": envelope.payload.get("trust", "derived_fact"),
            "freshness": envelope.payload.get("freshness", "generation_pinned"),
            "selection_reason": "projection_order",
            "content_class": envelope.payload.get("content_class", "fact"),
            "trusted_for_instruction": False,
            "payload": dict(envelope.payload),
            "authority": "producer",
        }
        if trust_floor is not None and _TRUST_RANK.get(item["trust"], -1) < _TRUST_RANK[trust_floor]:
            reasons.append("trust_floor")
            rejected.append({"stable_handle": envelope.stable_handle, "reason": "trust_floor"})
            continue
        encoded_size = len(json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        estimated_tokens = _tokens(item, resolved_tokenizer)
        if len(selected) >= max_items:
            reasons.append("item_budget")
            rejected.append({"stable_handle": envelope.stable_handle, "reason": "item_budget"})
            break
        if byte_total + encoded_size > max_bytes:
            reasons.append("byte_budget")
            rejected.append({"stable_handle": envelope.stable_handle, "reason": "byte_budget"})
            break
        if token_total + estimated_tokens > max_tokens:
            reasons.append("token_budget")
            rejected.append({"stable_handle": envelope.stable_handle, "reason": "token_budget"})
            break
        selected.append(item)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        source_bytes += encoded_size
        source_tokens += estimated_tokens
        byte_total += encoded_size
        token_total += estimated_tokens
    return {
        "schema": CONTEXT_SCHEMA,
        "repository_scope": repository_scope,
        "projections": selected,
        "projection_count": len(selected),
        "bytes": byte_total,
        "estimated_tokens": token_total if resolved_tokenizer is None else None,
        "tokens": token_total if resolved_tokenizer is not None else None,
        "source_bytes": source_bytes,
        "source_tokens": source_tokens,
        "wrapper_bytes": wrapper_bytes,
        "wrapper_tokens": wrapper_tokens,
        "trust_floor": trust_floor,
        "tokenizer": {
            "mode": "exact" if resolved_tokenizer is not None else "estimated",
            "id": effective_tokenizer_id,
            "reason": (
                None
                if resolved_tokenizer is not None
                else "provider_tokenizer_unavailable"
                if tokenizer_id
                else "tokenizer_unconfigured"
            ),
        },
        "source_generations": sorted({item["source_generation"] for item in selected}),
        "projection_generations": sorted(
            {item["projection_generation"] for item in selected}
        ),
        "selection": {
            "candidate_count": len(ordered),
            "selected_count": len(selected),
            "rejected": rejected,
            "domain_counts": dict(sorted(domain_counts.items())),
        },
        "truncated": bool(reasons),
        "truncation_reasons": sorted(set(reasons)),
        "authority": "facts_only",
        "instructions": False,
    }


__all__ = ["CONTEXT_SCHEMA", "UniversalContextError", "compile_context"]
