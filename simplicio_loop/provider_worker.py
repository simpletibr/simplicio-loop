"""Explicit OpenRouter provider worker for Loop orchestration.

The provider proposes a bounded mechanical-edit plan; Loop remains the
orchestrator and Dev CLI remains the deterministic mutation/verification owner.
This module never writes a repository file and never treats a provider response
as execution evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

OPENROUTER_PROVIDER = "openrouter"
OPENROUTER_MODEL = "deepseek/deepseek-v4.1-flash"
OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_WORKER_SCHEMA = "simplicio.openrouter-worker/v1"
MECHANICAL_EDIT_SCHEMA = "simplicio.mechanical-edit/v1"
DEFAULT_TIMEOUT_SECONDS = 90.0
# The pinned model is a reasoning model that spends hidden reasoning inside the
# completion budget.  A small ceiling returns an empty `content` with
# `finish_reason == "length"`, so the worker reserves a realistic artifact
# window and disables hidden reasoning instead of truncating the deliverable.
OPENROUTER_MAX_TOKENS = 16384
MINIMUM_OPENROUTER_MAX_TOKENS = 1024
OPENROUTER_MAX_TOKENS_ENV = "SIMPLICIO_OPENROUTER_MAX_TOKENS"


class ProviderWorkerError(RuntimeError):
    """A provider worker failure that must stop the selected dispatch lane."""

    def __init__(self, message: str, *, reason_code: str = "provider_worker_failed") -> None:
        super().__init__(message)
        self.reason_code = reason_code


def forwarded_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the only provider values allowed across the worker boundary.

    The API key is returned for request construction only. Callers must not
    serialize this mapping or include it in receipts/logs. Model selection is
    deliberately absent: the worker pins :data:`OPENROUTER_MODEL` in code.
    """
    source = os.environ if env is None else env
    key = str(source.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise ProviderWorkerError(
            "OPENROUTER_API_KEY is required for the explicitly selected provider worker",
            reason_code="provider_credential_missing",
        )
    base_url = str(source.get("OPENROUTER_BASE_URL") or OPENROUTER_DEFAULT_BASE_URL).strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderWorkerError(
            "OPENROUTER_BASE_URL must be an absolute http(s) URL",
            reason_code="provider_base_url_invalid",
        )
    return {"OPENROUTER_API_KEY": key, "OPENROUTER_BASE_URL": base_url.rstrip("/")}


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def completion_max_tokens(env: Mapping[str, str] | None = None) -> int:
    """Return the completion budget reserved for one provider request.

    An explicit positive override below the minimum is ignored: the worker must
    never reserve a window too small to hold a complete artifact.
    """
    source = os.environ if env is None else env
    raw = str(source.get(OPENROUTER_MAX_TOKENS_ENV) or "").strip()
    if not raw:
        return OPENROUTER_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError:
        return OPENROUTER_MAX_TOKENS
    return value if value >= MINIMUM_OPENROUTER_MAX_TOKENS else OPENROUTER_MAX_TOKENS


def _request_prompt(task: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    return (
        "You are an explicitly authorized external coding worker. You are not an execution authority. "
        "Return only a JSON object with a non-empty top-level `files` object mapping authorized relative "
        "paths to complete UTF-8 file contents. Do not claim that changes were applied or verified. "
        "Do not return markdown fences or any path outside the authorized targets.\n\n"
        "Task:\n"
        + json.dumps(dict(task), ensure_ascii=False, sort_keys=True)
        + "\n\nMapper context:\n"
        + json.dumps(dict(context), ensure_ascii=False, sort_keys=True)
    )


def _decode_proposal(response: Mapping[str, Any], *, max_tokens: int) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderWorkerError("provider response has no choices", reason_code="provider_response_invalid")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ProviderWorkerError("provider response choice is invalid", reason_code="provider_response_invalid")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise ProviderWorkerError("provider response has no message", reason_code="provider_response_invalid")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        if str(first.get("finish_reason") or "") == "length":
            usage = response.get("usage")
            observed = usage.get("completion_tokens") if isinstance(usage, Mapping) else None
            spent = observed if isinstance(observed, int) and not isinstance(observed, bool) else max_tokens
            raise ProviderWorkerError(
                "provider response was truncated at the "
                f"{spent}-token completion budget (max_tokens={max_tokens}); no JSON content was returned",
                reason_code="provider_response_truncated",
            )
        raise ProviderWorkerError("provider response has no JSON content", reason_code="provider_response_invalid")
    try:
        proposal = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ProviderWorkerError("provider response content is not JSON", reason_code="provider_response_invalid") from exc
    if not isinstance(proposal, Mapping):
        raise ProviderWorkerError("provider proposal must be an object", reason_code="provider_proposal_invalid")
    return dict(proposal)


def _usage_fields(response: Mapping[str, Any]) -> dict[str, Any]:
    raw = response.get("usage")
    usage = dict(raw) if isinstance(raw, Mapping) else None
    if usage is None:
        return {
            "usage": None,
            "usage_status": "unknown",
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "reasoning_tokens": None,
            "cost": None,
            "cost_status": "unknown",
        }
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    cached_tokens = usage.get("cached_tokens")
    if cached_tokens is None:
        details = usage.get("prompt_tokens_details")
        if isinstance(details, Mapping):
            cached_tokens = details.get("cached_tokens")
    reasoning_tokens = usage.get("reasoning_tokens")
    if reasoning_tokens is None:
        details = usage.get("completion_tokens_details")
        if isinstance(details, Mapping):
            reasoning_tokens = details.get("reasoning_tokens")
    cost = usage.get("cost", response.get("cost"))
    return {
        "usage": usage,
        "usage_status": "measured",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cost": cost,
        "cost_status": "measured" if cost is not None else "unknown",
    }


def _path_is_allowed(path: str, allowed_paths: Sequence[str]) -> bool:
    return any(path == allowed or allowed.endswith("/") and path.startswith(allowed) for allowed in allowed_paths)


def _normalise_proposal_path(raw_path: Any) -> str:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise ProviderWorkerError("provider proposal contains an invalid relative path", reason_code="provider_proposal_invalid")
    path = PurePosixPath(raw_path)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ProviderWorkerError("provider proposal contains an unsafe relative path", reason_code="provider_proposal_invalid")
    normalized = path.as_posix()
    if normalized != raw_path or not normalized:
        raise ProviderWorkerError("provider proposal path is not canonical", reason_code="provider_proposal_invalid")
    return normalized


def proposal_to_mechanical_plan(
    proposal: Mapping[str, Any],
    *,
    root: str | Path,
    allowed_paths: Sequence[str],
    forbidden_literals: Sequence[str] = (),
) -> dict[str, Any]:
    """Convert a provider proposal into a Dev CLI-owned mechanical plan.

    This is a deterministic in-flow conversion. It reads only the authorized
    target files and returns plan data; it never writes source artifacts.
    """
    nested = proposal.get("proposal") if isinstance(proposal.get("proposal"), Mapping) else proposal
    files = nested.get("files") if isinstance(nested, Mapping) else None
    if not isinstance(files, Mapping) or not files:
        raise ProviderWorkerError(
            "provider proposal requires a non-empty files object",
            reason_code="provider_proposal_invalid",
        )
    root_path = Path(root).resolve()
    operations: list[dict[str, Any]] = []
    touched: list[str] = []
    allowed = tuple(str(item).replace("\\", "/") for item in allowed_paths if str(item).strip())
    if not allowed:
        raise ProviderWorkerError("provider proposal has no authorized paths", reason_code="provider_scope_missing")
    for raw_path, content in files.items():
        path = _normalise_proposal_path(raw_path)
        if not _path_is_allowed(path, allowed):
            raise ProviderWorkerError(
                f"provider proposal path {path!r} is outside authorized paths",
                reason_code="provider_scope_violation",
            )
        if not isinstance(content, str):
            raise ProviderWorkerError(
                f"provider proposal content for {path!r} must be text",
                reason_code="provider_proposal_invalid",
            )
        if any(literal and literal in content for literal in forbidden_literals):
            raise ProviderWorkerError(
                "provider proposal contains a credential literal",
                reason_code="provider_response_contains_credential",
            )
        target = root_path / path
        if target.exists() and not target.is_file():
            raise ProviderWorkerError(
                f"provider proposal target {path!r} is not a file",
                reason_code="provider_target_invalid",
            )
        if target.is_file():
            current = target.read_text(encoding="utf-8")
            operations.append({
                "op": "replace_range",
                "path": path,
                "start_line": 1,
                "end_line": max(1, len(current.splitlines())),
                "text": content,
            })
        else:
            operations.append({"op": "create_file", "path": path, "text": content})
        touched.append(path)
    return {
        "schema": MECHANICAL_EDIT_SCHEMA,
        "touched_files": sorted(touched),
        "operations": sorted(operations, key=lambda item: item["path"]),
        "validation": [],
    }


class OpenRouterWorker:
    """One explicitly selected provider worker using OpenRouter's HTTP API."""

    provider = OPENROUTER_PROVIDER
    model = OPENROUTER_MODEL

    def __init__(
        self,
        *,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener or urllib.request.urlopen
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")

    def dispatch(
        self,
        *,
        task: Mapping[str, Any],
        context: Mapping[str, Any],
        run_id: str,
        task_index: int,
        allowed_paths: Sequence[str],
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        forwarded = forwarded_environment(env)
        max_tokens = completion_max_tokens(env)
        request_payload = {
            "model": OPENROUTER_MODEL,
            "temperature": 0,
            "max_tokens": max_tokens,
            # This model exposes hidden reasoning inside the completion budget.
            # Disabling it keeps the requested artifact from being truncated
            # before any JSON content is emitted.
            "reasoning": {"enabled": False},
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": _request_prompt(task, context)}],
        }
        endpoint = forwarded["OPENROUTER_BASE_URL"] + "/chat/completions"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + forwarded["OPENROUTER_API_KEY"],
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                provider_response = json.load(response)
        except urllib.error.HTTPError as exc:
            raise ProviderWorkerError(
                f"provider returned HTTP {exc.code}", reason_code="provider_http_error"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderWorkerError(
                f"provider transport failed: {type(exc).__name__}", reason_code="provider_transport_failed"
            ) from exc
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderWorkerError(
                "provider response could not be decoded", reason_code="provider_response_invalid"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - provider boundary must fail closed
            raise ProviderWorkerError(
                f"provider worker failed: {type(exc).__name__}", reason_code="provider_worker_failed"
            ) from exc
        if not isinstance(provider_response, Mapping):
            raise ProviderWorkerError("provider response is not an object", reason_code="provider_response_invalid")
        proposal = _decode_proposal(provider_response, max_tokens=max_tokens)
        usage = _usage_fields(provider_response)
        return {
            "schema": OPENROUTER_WORKER_SCHEMA,
            "status": "succeeded",
            "provider": OPENROUTER_PROVIDER,
            "model": OPENROUTER_MODEL,
            "run_id": str(run_id),
            "task_index": int(task_index),
            "task_sha256": _canonical_hash(dict(task)),
            "context_sha256": _canonical_hash(dict(context)),
            "allowed_paths": sorted(str(path) for path in allowed_paths),
            "proposal": proposal,
            "response_sha256": _canonical_hash(provider_response),
            "provider_call_count": 1,
            **usage,
        }
