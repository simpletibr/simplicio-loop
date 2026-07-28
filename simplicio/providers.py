"""Deterministic provider boundary for ``simplicio-py``.

The Python adapter is intentionally provider-free.  It must never send a
prompt, load a local model, invoke a provider CLI, open an HTTP client, or
download model weights.  LLM execution belongs outside this package.

The small compatibility surface below exists so the task/pipeline contracts
can report a typed, machine-readable block instead of importing or invoking a
provider implementation.
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any


class ProviderExecutionError(SystemExit):
    """Terminal, deterministic refusal to perform LLM generation."""

    def __init__(self, receipt: dict[str, Any]):
        self.receipt = dict(receipt)
        super().__init__(self.receipt["message"])


LLM_DISABLED_REASON = "llm_execution_disabled"

# Kept as data-only compatibility constants for local-model status contracts.
# No code in this module loads, downloads, or executes a model.
LOCAL_DEFAULT_MODEL = "openbmb/minicpm5:latest"
LOCAL_DEFAULT_REPO = "openbmb/MiniCPM5-1B-GGUF"
LOCAL_DEFAULT_FILE = "MiniCPM5-1B-Q4_K_M.gguf"
LOCAL_MODEL_PREFIX = "local-llama/"
LOCAL_EXECUTOR_DIR = str(Path.home() / ".simplicio" / "models" / "executor")

_LAST_CACHE_RECEIPT: dict[str, Any] | None = None


def _disabled_receipt(*, surface: str, model: str | None = None) -> dict[str, Any]:
    return {
        "schema": "simplicio.provider-terminal/v1",
        "status": "blocked",
        "reason_code": LLM_DISABLED_REASON,
        "provider": "disabled",
        "model": model or os.environ.get("SIMPLICIO_MODEL", ""),
        "surface": surface,
        "message": (
            "simplicio-py is deterministic-only; LLM execution is disabled and "
            "no local or remote provider will be contacted"
        ),
        "next_action": "provide deterministic input or use an external orchestrator",
    }


def _disabled(*, surface: str, model: str | None = None) -> ProviderExecutionError:
    return ProviderExecutionError(_disabled_receipt(surface=surface, model=model))


def _provider_id(model: str | None, base: str | None) -> str:
    """Return the only supported execution route: deterministic-disabled."""
    return "deterministic-disabled"


def info() -> str:
    return "provider=disabled mode=deterministic-only llm_calls=disabled"


def planner_info() -> str:
    return "planner=disabled mode=deterministic-only llm_calls=disabled"


def _apply_directives(prompt: str) -> str:
    """Compatibility identity function; prompts are never transmitted."""
    return prompt


def _cfg() -> dict[str, str | None]:
    """Expose configuration shape without reading or resolving credentials."""
    return {
        "model": os.environ.get("SIMPLICIO_MODEL"),
        "base": os.environ.get("SIMPLICIO_BASE_URL"),
        "key": None,
    }


def generate(
    prompt: str, feedback: str | None = None, max_tokens: int = 4000, template_version: str | None = None
) -> str:
    """Refuse generation without contacting any model or provider."""
    del prompt, feedback, max_tokens, template_version
    raise _disabled(surface="generate")


def planner_cfg(require_key: bool = True) -> dict[str, Any]:
    """Return a deterministic-disabled planner descriptor."""
    del require_key
    return {
        "model": None,
        "base": None,
        "key": None,
        "native_anthropic": False,
        "shell_out": False,
        "disabled": True,
    }


def _planner_provider_id(cfg: dict[str, Any]) -> str:
    del cfg
    return "planner:deterministic-disabled"


def _planner_cache_key(
    cfg: dict[str, Any], prompt: str, max_tokens: int, temperature: float, template_version: str | None = None
) -> str:
    """Stable local identifier for callers that still build cache receipts."""
    from ._cache import make_key

    return make_key(
        _planner_provider_id(cfg),
        "disabled",
        prompt,
        max_tokens=max_tokens,
        template_version=f"{temperature}:{template_version or ''}",
    )


def planner_complete(
    prompt: str, max_tokens: int = 8192, temperature: float = 0.1, template_version: str | None = None
) -> str:
    """Refuse planning generation without contacting any model or provider."""
    del prompt, max_tokens, temperature, template_version
    raise _disabled(surface="planner_complete")


def last_cache_receipt() -> dict[str, Any] | None:
    """Read-only compatibility accessor for deterministic cache receipts."""
    return deepcopy(_LAST_CACHE_RECEIPT)
