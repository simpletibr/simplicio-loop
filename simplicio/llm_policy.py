"""Deterministic-only execution policy for the Simplicio Dev CLI.

The CLI is an executor and evidence boundary, not an inference runtime. It
must work without a local model, a remote model, provider SDKs, API keys,
provider CLIs, model weights, or network access. Model generation belongs to
an external coordinator; this package only consumes explicit plans/changesets
and performs deterministic local work.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

LLM_EXECUTION_DISABLED = "llm_execution_disabled"


def _safe_endpoint(value: str | None) -> str:
    """Return only non-secret endpoint identity for a policy receipt."""
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.hostname:
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return f"{parsed.scheme}://{host}" if parsed.scheme else host
    return "<configured>"


def _requested_route(model: str, base_url: str) -> str:
    lowered = model.lower()
    if (
        lowered.startswith(("local-", "ollama", "llama", "qwen"))
        or "localhost" in base_url.lower()
        or "127.0.0.1" in base_url
        or "::1" in base_url
    ):
        return "local"
    if model or base_url:
        return "remote"
    return "unspecified"


def execution_disabled_receipt(
    *,
    surface: str,
    model: str | None = None,
    base_url: str | None = None,
) -> dict[str, object]:
    """Build the stable, secret-free receipt for every blocked LLM route."""
    requested_model = model or os.environ.get("SIMPLICIO_MODEL", "")
    requested_base_url = base_url or os.environ.get("SIMPLICIO_BASE_URL", "")
    return {
        "schema": "simplicio.llm-policy-receipt/v1",
        "status": "blocked",
        "reason_code": LLM_EXECUTION_DISABLED,
        "message": (
            "LLM execution is disabled; provide an explicit mechanical-edit/changeset "
            "plan or use an external orchestrator."
        ),
        "policy": "deterministic_only",
        "surface": surface,
        "requested_route": _requested_route(requested_model, requested_base_url),
        "requested_model": requested_model,
        "requested_base_url": _safe_endpoint(requested_base_url),
        "effective_route": "deterministic",
        "model_invoked": False,
        "side_effects": {
            "cache_read": False,
            "cache_write": False,
            "model_load": False,
            "network": False,
            "subprocess": False,
        },
        "retryable": False,
        "correlation_id": os.environ.get("SIMPLICIO_TRACE_ID") or None,
        "next_action": (
            "provide an explicit mechanical-edit/changeset plan, or use an "
            "external orchestrator for model generation"
        ),
    }
