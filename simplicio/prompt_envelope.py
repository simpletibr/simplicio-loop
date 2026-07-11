"""Versioned prompt-layer accounting for stable, fail-closed retries."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

PROMPT_ENVELOPE_SCHEMA = "simplicio.prompt-envelope/v1"
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


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _estimate(text: str) -> int:
    return max(0, len(text) // 4)


def _budget(layer: str, default: int) -> int:
    raw = os.environ.get(f"SIMPLICIO_PROMPT_BUDGET_{layer.upper()}", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class PromptEnvelope:
    """Immutable prompt layers plus a typed retry delta.

    The rendered prompt remains byte-compatible with the legacy builder.  The
    envelope adds a machine-readable ledger so callers can detect overflow,
    cache identity changes, and retry duplication without guessing from text.
    """

    template_version: str
    layers: dict[str, str]
    budgets: dict[str, int]
    retry_delta: dict[str, Any] | None = None

    @classmethod
    def from_layers(cls, layers: dict[str, str], *, template_version: str = "unknown") -> PromptEnvelope:
        budgets = {name: _budget(name, DEFAULT_BUDGETS.get(name, 800)) for name in layers}
        return cls(template_version, dict(layers), budgets)

    @property
    def prefix_hash(self) -> str:
        return _hash({"template_version": self.template_version, "layers": self.layers})

    @property
    def context_pack_hash(self) -> str:
        return _hash({name: self.layers.get(name, "") for name in ("target", "precedent", "skill")})

    @property
    def delta_hash(self) -> str | None:
        return _hash(self.retry_delta) if self.retry_delta is not None else None

    @property
    def ledger(self) -> list[dict[str, Any]]:
        return [
            {
                "layer": name,
                "estimated_tokens": _estimate(text),
                "effective_budget": self.budgets[name],
                "overflow": _estimate(text) > self.budgets[name],
                "inclusion_reason": "required-layer",
            }
            for name, text in self.layers.items()
        ]

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
        return PromptEnvelope(self.template_version, self.layers, self.budgets, delta)

    def render(self) -> str:
        return "\n\n".join(self.layers.values()).strip()

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": PROMPT_ENVELOPE_SCHEMA,
            "template_version": self.template_version,
            "prefix_hash": self.prefix_hash,
            "context_pack_hash": self.context_pack_hash,
            "delta_hash": self.delta_hash,
            "layers": self.ledger,
            "retry_delta": self.retry_delta,
            "needs_broader_context": self.needs_broader_context,
            "cache_eligible": not self.needs_broader_context,
        }
