"""Fail-closed policy for optional local LLM inference (issue #259).

Local engines are intentionally paused by default.  This module contains no
provider imports and performs no I/O, so callers can apply the gate before
model discovery, downloads, subprocesses, sockets, or cache reads.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

LOCAL_INFERENCE_PAUSED = "LOCAL_INFERENCE_PAUSED"
LOCAL_INFERENCE_ENV = "SIMPLICIO_LOCAL_INFERENCE"
_ENABLED_VALUES = {"enabled", "1", "true", "yes"}


def local_inference_enabled() -> bool:
    """Return true only after an explicit, process-scoped re-enable."""
    return os.environ.get(LOCAL_INFERENCE_ENV, "").strip().lower() in _ENABLED_VALUES


def is_local_endpoint(base_url: str | None) -> bool:
    """Recognize loopback OpenAI-compatible endpoints, including Ollama."""
    if not base_url:
        return False
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def pause_receipt(*, surface: str, model: str | None = None, base_url: str | None = None) -> dict:
    """Stable, secret-free receipt emitted for every blocked local route."""
    return {
        "schema": "simplicio.local-inference-policy-receipt/v1",
        "reason_code": LOCAL_INFERENCE_PAUSED,
        "policy": "disabled_by_default",
        "surface": surface,
        "configuration_origin": LOCAL_INFERENCE_ENV,
        "correlation_id": os.environ.get("SIMPLICIO_TRACE_ID") or None,
        "requested_model": model or "",
        "requested_base_url": base_url or "",
        "refused_backend": "loopback-openai-compatible" if is_local_endpoint(base_url) else "local-inference",
        "effective_route": "blocked",
        "retryable": True,
        "reenable": f"set {LOCAL_INFERENCE_ENV}=enabled explicitly",
        "next_action": f"set {LOCAL_INFERENCE_ENV}=enabled explicitly, then retry",
    }


class LocalInferencePaused(SystemExit):
    """Fail-closed terminal result with a machine-readable policy receipt."""

    def __init__(self, receipt: dict):
        self.receipt = dict(receipt)
        super().__init__(LOCAL_INFERENCE_PAUSED)


def require_enabled(*, surface: str, model: str | None = None, base_url: str | None = None) -> None:
    """Block before any local backend side effect unless explicitly enabled."""
    if not local_inference_enabled():
        raise LocalInferencePaused(pause_receipt(surface=surface, model=model, base_url=base_url))
