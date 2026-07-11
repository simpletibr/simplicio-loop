"""Versioned prompt-layer accounting for stable, fail-closed retries."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

PROMPT_ENVELOPE_SCHEMA = "simplicio.prompt-envelope/v1"
PROMPT_RETRY_DELTA_SCHEMA = "simplicio.prompt-retry-delta/v1"
LAYER_ORDER = (
    "policy",
    "goal",
    "target",
    "precedent",
    "skill",
    "adaptation",
    "acceptance",
    "constraints",
)
CONTEXT_PACK_LAYERS = ("target", "precedent", "skill")
DEFAULT_CONTEXT_WINDOW = 8192
DEFAULT_TASK_CLASS = "mechanical_edit"
DEFAULT_BUDGETS = {
    "policy": 900,
    "goal": 700,
    "target": 1800,
    "precedent": 1200,
    "skill": 1200,
    "adaptation": 700,
    "acceptance": 700,
    "constraints": 700,
}
TASK_CLASS_PROFILES = {
    "mechanical_edit": DEFAULT_BUDGETS,
    "diagnosis": {
        **DEFAULT_BUDGETS,
        "target": 2200,
        "precedent": 1400,
        "skill": 1000,
        "adaptation": 900,
    },
    "review": {
        **DEFAULT_BUDGETS,
        "policy": 1100,
        "goal": 600,
        "target": 1400,
        "precedent": 900,
        "skill": 900,
        "acceptance": 900,
        "constraints": 900,
    },
    "planning": {
        **DEFAULT_BUDGETS,
        "goal": 900,
        "target": 1200,
        "precedent": 900,
        "skill": 1400,
        "adaptation": 1000,
    },
    "verification": {
        **DEFAULT_BUDGETS,
        "policy": 1100,
        "goal": 600,
        "target": 1600,
        "precedent": 1000,
        "skill": 1000,
        "acceptance": 1000,
        "constraints": 900,
    },
    "repair": {
        **DEFAULT_BUDGETS,
        "goal": 650,
        "target": 1800,
        "precedent": 900,
        "skill": 900,
        "adaptation": 900,
        "acceptance": 800,
        "constraints": 800,
    },
}


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _estimate(text: str) -> int:
    return max(0, len(text) // 4)


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _ordered_names(layers: dict[str, str]) -> list[str]:
    known = [name for name in LAYER_ORDER if name in layers]
    extra = sorted(name for name in layers if name not in LAYER_ORDER)
    return [*known, *extra]


def _ordered_layers(layers: dict[str, str]) -> dict[str, str]:
    return {name: layers[name] for name in _ordered_names(layers)}


def _task_class(value: str | None) -> str:
    raw = (value or os.environ.get("SIMPLICIO_PROMPT_TASK_CLASS") or DEFAULT_TASK_CLASS).strip().lower()
    return raw if raw in TASK_CLASS_PROFILES else DEFAULT_TASK_CLASS


def _context_window(value: int | None) -> int:
    raw = value
    if raw is None:
        for env_name in ("SIMPLICIO_MODEL_CONTEXT_WINDOW", "SIMPLICIO_LOCAL_CTX"):
            env_raw = os.environ.get(env_name, "").strip()
            if env_raw:
                try:
                    raw = int(env_raw)
                except ValueError:
                    raw = None
                break
    if raw is None:
        return DEFAULT_CONTEXT_WINDOW
    return max(1024, raw)


def _provider_identity() -> tuple[str, str]:
    effective_model = (
        os.environ.get("SIMPLICIO_EFFECTIVE_MODEL") or os.environ.get("SIMPLICIO_MODEL") or ""
    ).strip()
    base = (os.environ.get("SIMPLICIO_BASE_URL") or "").strip()
    provider = (os.environ.get("SIMPLICIO_PROVIDER") or "").strip()
    if provider:
        return provider, effective_model
    if effective_model.startswith("claude-cli/"):
        return "claude-cli", effective_model
    if effective_model.startswith("codex-cli/"):
        return "codex-cli", effective_model
    if effective_model.startswith("local-llama/") or effective_model == "openbmb/minicpm5:latest":
        return "local-llama", effective_model
    if base and effective_model:
        parsed = urlparse(base)
        return parsed.netloc or "openai-compatible", effective_model
    if base:
        parsed = urlparse(base)
        return parsed.netloc or "openai-compatible", effective_model
    if not effective_model:
        return "local-llama", "openbmb/minicpm5:latest"
    return "unknown", effective_model


def _budget(layer: str, default: int) -> tuple[int, str]:
    raw = os.environ.get(f"SIMPLICIO_PROMPT_BUDGET_{layer.upper()}", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default, "profile"
    return (value, "env") if value > 0 else (default, "profile")


def _scaled_profile(
    task_class: str, context_window: int, layers: dict[str, str]
) -> tuple[dict[str, int], dict[str, str]]:
    profile = TASK_CLASS_PROFILES.get(task_class, DEFAULT_BUDGETS)
    scale = max(0.5, min(4.0, context_window / DEFAULT_CONTEXT_WINDOW))
    budgets: dict[str, int] = {}
    sources: dict[str, str] = {}
    for name in layers:
        default = int(round(profile.get(name, DEFAULT_BUDGETS.get(name, 800)) * scale))
        budgets[name], sources[name] = _budget(name, max(1, default))
    return budgets, sources


@dataclass(frozen=True)
class PromptEnvelope:
    """Immutable prompt layers plus a typed retry delta.

    The rendered base prompt remains byte-stable across retries unless the
    immutable layer set changes. Receipts expose per-layer budgeting and cache
    identity without persisting raw prompt bodies.
    """

    template_version: str
    layers: dict[str, str]
    budgets: dict[str, int]
    budget_sources: dict[str, str]
    task_class: str
    context_window: int
    provider: str
    model: str
    retry_delta: dict[str, Any] | None = None

    @classmethod
    def from_layers(
        cls,
        layers: dict[str, str],
        *,
        template_version: str = "unknown",
        task_class: str | None = None,
        context_window: int | None = None,
    ) -> PromptEnvelope:
        ordered_layers = _ordered_layers(dict(layers))
        resolved_task_class = _task_class(task_class)
        resolved_context_window = _context_window(context_window)
        budgets, budget_sources = _scaled_profile(
            resolved_task_class, resolved_context_window, ordered_layers
        )
        provider, model = _provider_identity()
        return cls(
            template_version,
            ordered_layers,
            budgets,
            budget_sources,
            resolved_task_class,
            resolved_context_window,
            provider,
            model,
        )

    @property
    def ordered_layer_names(self) -> list[str]:
        return list(self.layers)

    @property
    def prefix_hash(self) -> str:
        return _hash(
            {
                "template_version": self.template_version,
                "layers": [(name, self.layers[name]) for name in self.ordered_layer_names],
            }
        )

    @property
    def context_pack_hash(self) -> str:
        return _hash([(name, self.layers[name]) for name in CONTEXT_PACK_LAYERS if name in self.layers])

    @property
    def delta_hash(self) -> str | None:
        if self.retry_delta is None:
            return None
        payload = {key: value for key, value in self.retry_delta.items() if key != "diagnostics"}
        payload["diagnostics_hash"] = _hash(self.retry_delta.get("diagnostics", ""))
        return _hash(payload)

    @property
    def ledger(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name in self.ordered_layer_names:
            text = self.layers[name]
            estimated = _estimate(text)
            hard_budget = self.budgets[name]
            overflow = estimated > hard_budget
            rows.append(
                {
                    "layer": name,
                    "estimated_tokens": estimated,
                    "soft_budget": max(1, int(round(hard_budget * 0.85))),
                    "hard_budget": hard_budget,
                    "effective_budget": hard_budget,
                    "overflow": overflow,
                    "inclusion_reason": "required-layer" if not overflow else "overflow-escalated",
                    "truncation": "none" if not overflow else "needs_broader_context",
                    "fidelity_risk": "low" if not overflow else "high",
                    "budget_source": self.budget_sources[name],
                }
            )
        return rows

    @property
    def needs_broader_context(self) -> bool:
        return any(row["overflow"] for row in self.ledger)

    def with_retry_delta(
        self,
        *,
        reason: str,
        failure_class: str,
        diagnostics: str,
        affected_files: list[str] | tuple[str, ...] = (),
    ) -> PromptEnvelope:
        delta = {
            "reason": reason,
            "failure_class": failure_class,
            "diagnostics": diagnostics,
            "affected_files": list(affected_files),
        }
        return PromptEnvelope(
            self.template_version,
            self.layers,
            self.budgets,
            self.budget_sources,
            self.task_class,
            self.context_window,
            self.provider,
            self.model,
            delta,
        )

    def render(self) -> str:
        return "\n\n".join(self.layers[name] for name in self.ordered_layer_names).strip()

    def render_retry_delta(self) -> str:
        if self.retry_delta is None:
            return ""
        diagnostics = str(self.retry_delta.get("diagnostics", "")).strip()
        lines = [
            "Retry delta:",
            f"- reason: {self.retry_delta.get('reason', 'unknown')}",
            f"- failure_class: {self.retry_delta.get('failure_class', 'unknown')}",
        ]
        affected_files = self.retry_delta.get("affected_files") or []
        if affected_files:
            lines.append(f"- affected_files: {', '.join(str(item) for item in affected_files)}")
        if diagnostics:
            lines.append(f"- diagnostics_hash: {_hash(diagnostics)}")
            lines.append("- diagnostics_excerpt:")
            lines.append(_trim(diagnostics, 600))
        lines.append("- requested_correction: Return the full corrected DIFF + TEST block only.")
        return "\n".join(lines)

    def _retry_receipt(self) -> dict[str, Any] | None:
        if self.retry_delta is None:
            return None
        diagnostics = str(self.retry_delta.get("diagnostics", ""))
        return {
            "schema": PROMPT_RETRY_DELTA_SCHEMA,
            "reason": self.retry_delta.get("reason"),
            "failure_class": self.retry_delta.get("failure_class"),
            "affected_files": list(self.retry_delta.get("affected_files") or []),
            "diagnostics_hash": _hash(diagnostics),
            "diagnostics_tokens": _estimate(diagnostics),
            "diagnostics_excerpt": _trim(diagnostics, 240),
            "requested_correction": "Return the full corrected DIFF + TEST block only.",
        }

    def receipt(self) -> dict[str, Any]:
        context_layers = [name for name in CONTEXT_PACK_LAYERS if name in self.layers]
        return {
            "schema": PROMPT_ENVELOPE_SCHEMA,
            "template_version": self.template_version,
            "task_class": self.task_class,
            "context_window": self.context_window,
            "provider": self.provider,
            "model": self.model,
            "budget_profile": self.task_class,
            "immutable_prefix": {
                "hash": self.prefix_hash,
                "layers": self.ordered_layer_names,
            },
            "context_pack": {
                "hash": self.context_pack_hash,
                "layers": context_layers,
                "provenance": [{"layer": name, "source": "prompt-layer"} for name in context_layers],
            },
            "prefix_hash": self.prefix_hash,
            "context_pack_hash": self.context_pack_hash,
            "delta_hash": self.delta_hash,
            "layers": self.ledger,
            "retry_delta": self._retry_receipt(),
            "needs_broader_context": self.needs_broader_context,
            "cache_eligible": not self.needs_broader_context,
        }
