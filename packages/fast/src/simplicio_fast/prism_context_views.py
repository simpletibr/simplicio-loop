"""Compatibility facade for the authority-bound context-view service (#214).

This module intentionally owns no selection or authorization logic.  Legacy
callers keep ``build_context_view``/``validate_context_view`` while the
canonical :mod:`simplicio_fast.context_view` implementation performs path,
authority, budget, lineage and tamper checks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping, Sequence

from .context_view import (
    ContextAuthority,
    ContextBudget,
    ContextIdentity,
    ContextItem,
    ContextViewError,
    ContextViewRequest,
    ContextViewService,
    verify_context_view,
)

VIEW_SCHEMA = "simplicio.fast.prism-context-view/v2"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()


def _require_authority(authority: ContextAuthority | None) -> ContextAuthority:
    if not isinstance(authority, ContextAuthority):
        raise ContextViewError(
            "authority_required", "an explicit ContextAuthority is required"
        )
    return authority


def _compatibility_span(item: Mapping[str, Any]) -> dict[str, Any]:
    provenance = item.get("provenance")
    if not isinstance(provenance, list):
        raise ContextViewError("compatibility_binding_invalid")
    fields: dict[str, Any] = {}
    for entry in provenance:
        if not isinstance(entry, str) or not entry.startswith("compat:"):
            continue
        key, separator, encoded = entry[7:].partition(":")
        if separator and key in {"start", "end"}:
            try:
                fields[key] = json.loads(encoded)
            except json.JSONDecodeError as error:
                raise ContextViewError("compatibility_binding_invalid", key) from error
    if set(fields) != {"start", "end"}:
        raise ContextViewError("compatibility_binding_invalid")
    return {
        "path": item["path"],
        "start": fields["start"],
        "end": fields["end"],
        "text_hash": item["source_sha256"],
        "tokens": item["token_count"],
    }


def _request_from_record(value: object) -> ContextViewRequest:
    if not isinstance(value, Mapping):
        raise ContextViewError("request_invalid")
    try:
        identity = value["identity"]
        budget = value["budget"]
        if not isinstance(identity, Mapping) or not isinstance(budget, Mapping):
            raise TypeError("identity and budget must be mappings")
        return ContextViewRequest(
            repository=value["repository"],
            identity=ContextIdentity(**identity),
            base_generation=value["base_generation"],
            overlay_digest=value.get("overlay_digest"),
            requested_capability=value["requested_capability"],
            goal_fragment=value["goal_fragment"],
            budget=ContextBudget(**budget),
            authority_digest=value["authority_digest"],
            fence=value["fence"],
            ttl_seconds=value["ttl_seconds"],
            schema=value["schema"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ContextViewError("request_invalid", str(error)) from error


def build_context_view(
    *,
    agent_id: str,
    stage_id: str,
    task_id: str,
    generation_id: str,
    spans: Sequence[Mapping[str, Any]],
    budget_tokens: int = 4000,
    source_hashes: Mapping[str, str] | None = None,
    authority: ContextAuthority | None = None,
    repository: str = "compatibility/legacy",
    prism_id: str = "compatibility-prism",
    slot_id: str = "compatibility-slot",
    attempt: int = 1,
    requested_capability: str = "context:read",
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    """Build the legacy envelope through the canonical deep implementation."""
    authority = _require_authority(authority)
    if not isinstance(spans, Sequence) or isinstance(spans, (str, bytes)):
        raise ContextViewError("spans_invalid")
    if not isinstance(budget_tokens, int) or budget_tokens < 1:
        raise ContextViewError("budget_invalid")
    try:
        ordered = sorted(
            (dict(item) for item in spans),
            key=lambda row: (str(row.get("path", "")), row.get("start", 0)),
        )
    except (TypeError, ValueError) as error:
        raise ContextViewError("spans_invalid", str(error)) from error

    items: list[ContextItem] = []
    metadata: dict[str, dict[str, Any]] = {}
    expected_hashes = dict(source_hashes or {})
    for index, span in enumerate(ordered):
        path = span.get("path")
        text = span.get("text", "")
        if not isinstance(path, str) or not isinstance(text, str):
            raise ContextViewError("span_invalid", f"index={index}")
        tokens = span.get("tokens")
        if tokens is None:
            tokens = max(1, len(text) // 4)
        if not isinstance(tokens, int) or tokens < 0:
            raise ContextViewError("span_invalid", f"tokens index={index}")
        source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        expected = expected_hashes.get(path)
        if expected is not None and (
            not isinstance(expected, str)
            or not hmac.compare_digest(expected, source_sha256)
        ):
            raise ContextViewError("item_tampered", path)
        handle = (
            "legacy-span-"
            + _digest(
                {
                    "path": path,
                    "start": span.get("start"),
                    "end": span.get("end"),
                    "source_sha256": source_sha256,
                }
            )[:32]
        )
        item = ContextItem.create(
            kind="span",
            handle=handle,
            content=text,
            base_generation=generation_id,
            token_count=tokens,
            path=path,
            provenance=(
                "prism_context_views:compatibility",
                "compat:start:"
                + json.dumps(
                    span.get("start"), separators=(",", ":"), ensure_ascii=True
                ),
                "compat:end:"
                + json.dumps(span.get("end"), separators=(",", ":"), ensure_ascii=True),
            ),
        )
        items.append(item)
        metadata[handle] = {
            "path": path,
            "start": span.get("start"),
            "end": span.get("end"),
            "text_hash": item.source_sha256,
            "tokens": item.token_count,
        }

    identity = ContextIdentity(
        prism_id=prism_id,
        slot_id=slot_id,
        task_id=task_id,
        attempt=attempt,
        agent_id=agent_id,
        stage=stage_id,
    )
    budget = ContextBudget(
        max_tokens=budget_tokens,
        max_bytes=max(1024, budget_tokens * 16),
        max_nodes=max(1, len(items)),
    )
    request = ContextViewRequest(
        repository=repository,
        identity=identity,
        base_generation=generation_id,
        requested_capability=requested_capability,
        goal_fragment=f"compatibility context view for {task_id}",
        budget=budget,
        authority_digest=authority.digest,
        fence=authority.fence,
        ttl_seconds=ttl_seconds,
    )
    deep_view = ContextViewService().materialize(request, authority, items)
    selected = [metadata[item["handle"]] for item in deep_view.selected]
    selected_hashes = {
        item["path"]: item["text_hash"] for item in selected if item["path"]
    }
    unsigned = {
        "schema": VIEW_SCHEMA,
        "view_id": deep_view.handle,
        "agent_id": agent_id,
        "stage_id": stage_id,
        "task_id": task_id,
        "generation_id": generation_id,
        "spans": selected,
        "source_hashes": dict(sorted(selected_hashes.items())),
        "budget_tokens": budget_tokens,
        "truncated": len(selected) < len(items),
        "used_tokens": deep_view.usage["tokens"],
        "authority_digest": authority.digest,
        "fence": authority.fence,
        "request": request.record(),
        "deep_view": deep_view.record(),
    }
    return {**unsigned, "view_hash": _digest(unsigned)}


def validate_context_view(
    view: Mapping[str, Any],
    *,
    authority: ContextAuthority | None = None,
) -> dict[str, Any]:
    """Validate both the compatibility envelope and canonical deep receipt."""
    authority = _require_authority(authority)
    if not isinstance(view, Mapping) or view.get("schema") != VIEW_SCHEMA:
        raise ContextViewError("schema_invalid")
    value = dict(view)
    supplied_hash = value.pop("view_hash", None)
    if not isinstance(supplied_hash, str) or not hmac.compare_digest(
        supplied_hash, _digest(value)
    ):
        raise ContextViewError("tampered")
    request = _request_from_record(value.get("request"))
    deep = verify_context_view(
        value.get("deep_view", {}),
        request=request,
        authority=authority,
    )
    expected = {
        "view_id": deep["handle"],
        "agent_id": deep["identity"]["agent_id"],
        "stage_id": deep["identity"]["stage"],
        "task_id": deep["identity"]["task_id"],
        "generation_id": deep["base_generation"],
        "used_tokens": deep["usage"]["tokens"],
        "authority_digest": deep["authority_digest"],
        "fence": deep["fence"],
    }
    if any(
        value.get(field) != expected_value for field, expected_value in expected.items()
    ):
        raise ContextViewError("compatibility_binding_invalid")
    selected_by_handle = {item["handle"]: item for item in deep["selected"]}
    expected_spans = [_compatibility_span(item) for item in selected_by_handle.values()]
    if value.get("spans") != expected_spans:
        raise ContextViewError("compatibility_binding_invalid")
    expected_hashes = {
        span["path"]: span["text_hash"] for span in expected_spans if span["path"]
    }
    if value.get("source_hashes") != dict(sorted(expected_hashes.items())):
        raise ContextViewError("compatibility_binding_invalid")
    if value.get("budget_tokens") != request.budget.max_tokens:
        raise ContextViewError("compatibility_binding_invalid")
    if value.get("truncated") is not (deep["quality"]["budget_rejections"] > 0):
        raise ContextViewError("compatibility_binding_invalid")
    return {**value, "view_hash": supplied_hash}


__all__ = [
    "VIEW_SCHEMA",
    "ContextAuthority",
    "ContextViewError",
    "build_context_view",
    "validate_context_view",
]
