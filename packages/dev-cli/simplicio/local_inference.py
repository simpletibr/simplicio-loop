"""Deterministic-only boundary for local model operations.

The Dev CLI never provisions or executes local inference. Model generation is
owned by an external coordinator.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

LOCAL_INFERENCE_PAUSED = "LOCAL_INFERENCE_PAUSED"
LOCAL_INFERENCE_ENV = "SIMPLICIO_LOCAL_INFERENCE"


def local_inference_enabled() -> bool:
    """Local inference is never available inside the deterministic CLI."""
    return False


def is_local_endpoint(base_url: str | None) -> bool:
    """Recognize loopback OpenAI-compatible endpoints, including Ollama."""
    if not base_url:
        return False
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def pause_receipt(
    *,
    surface: str,
    model: str | None = None,
    base_url: str | None = None,
) -> dict:
    """Return a stable, secret-free receipt for a blocked local route."""
    endpoint = ""
    if base_url:
        parsed = urlparse(base_url)
        endpoint = f"{parsed.scheme}://{parsed.hostname}" if parsed.hostname else "<configured>"
    return {
        "schema": "simplicio.local-inference-policy-receipt/v1",
        "reason_code": LOCAL_INFERENCE_PAUSED,
        "policy": "deterministic_only",
        "surface": surface,
        "configuration_origin": LOCAL_INFERENCE_ENV,
        "correlation_id": os.environ.get("SIMPLICIO_TRACE_ID") or None,
        "requested_model": model or "",
        "requested_base_url": endpoint,
        "refused_backend": (
            "loopback-openai-compatible" if is_local_endpoint(base_url) else "local-inference"
        ),
        "effective_route": "blocked",
        "retryable": False,
        "reenable": "external orchestrator required",
        "next_action": ("provide an explicit mechanical-edit/changeset plan or use an external orchestrator"),
    }


class LocalInferencePaused(SystemExit):
    """Fail-closed terminal result with a machine-readable policy receipt."""

    def __init__(self, receipt: dict):
        self.receipt = dict(receipt)
        super().__init__(LOCAL_INFERENCE_PAUSED)


def require_enabled(
    *,
    surface: str,
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    """Always block local model side effects inside the deterministic CLI."""
    raise LocalInferencePaused(pause_receipt(surface=surface, model=model, base_url=base_url))
