"""Hard-bounded, reason-coded adaptive context assembly (issue #810)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol, Sequence

SCHEMA = "simplicio.loop-adaptive-context/v1"
RECEIPT_SCHEMA = "simplicio.loop-adaptive-context-receipt/v1"


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class ContextBudgetError(RuntimeError):
    reason_code = "CONTEXT_BUDGET_ERROR"


class HardBudgetExceeded(ContextBudgetError):
    reason_code = "HARD_BUDGET_EXCEEDED"


class TokenCountUnavailable(ContextBudgetError):
    reason_code = "TOKEN_COUNT_UNAVAILABLE"


class InvalidExpansion(ContextBudgetError):
    reason_code = "EXPANSION_REASON_REQUIRED"


class StaleSpan(ContextBudgetError):
    reason_code = "STALE_SPAN"


class ExpansionReason(str, Enum):
    MISSING_SYMBOL = "MISSING_SYMBOL"
    UNRESOLVED_RELATION = "UNRESOLVED_RELATION"
    FAILING_TEST = "FAILING_TEST"
    STALE_CONTEXT = "STALE_CONTEXT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class TokenCounter(Protocol):
    name: str

    def count(self, text: str) -> int: ...


class RegexTokenCounter:
    """Portable observed counter for offline control; not provider billing."""

    name = "regex-v1"
    _TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)

    def count(self, text: str) -> int:
        return len(self._TOKEN.findall(text))


class TiktokenCounter:
    """Provider-compatible BPE counter when the declared dependency is installed."""

    def __init__(self, encoding: str = "cl100k_base") -> None:
        import tiktoken  # type: ignore[import-not-found]
        self._encoding = tiktoken.get_encoding(encoding)
        self.name = "tiktoken:" + encoding

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))


@dataclass(frozen=True)
class BudgetLimits:
    soft_tokens: int
    hard_tokens: int

    def __post_init__(self) -> None:
        if self.soft_tokens < 0 or self.hard_tokens < 1:
            raise ValueError("token limits must be positive")
        if self.soft_tokens > self.hard_tokens:
            raise ValueError("soft token limit cannot exceed hard token limit")


@dataclass(frozen=True)
class BudgetScope:
    run: BudgetLimits
    stages: Mapping[str, BudgetLimits] = field(default_factory=dict)
    tasks: Mapping[str, BudgetLimits] = field(default_factory=dict)
    providers: Mapping[str, BudgetLimits] = field(default_factory=dict)

    def resolve(self, *, stage: str, task: str, provider: str) -> BudgetLimits:
        candidates = [self.run]
        for key, values in ((stage, self.stages), (task, self.tasks),
                            (provider, self.providers)):
            if key in values:
                candidates.append(values[key])
        return BudgetLimits(
            soft_tokens=min(item.soft_tokens for item in candidates),
            hard_tokens=min(item.hard_tokens for item in candidates),
        )


@dataclass(frozen=True)
class ContextSpan:
    content: str
    provenance: str
    revision: str
    kind: str = "fact"
    priority: int = 100
    handle: str = ""

    def __post_init__(self) -> None:
        if not self.content or not self.provenance or not self.revision:
            raise ValueError("content, provenance and revision are required")

    @property
    def span_hash(self) -> str:
        return _hash({"content": self.content, "provenance": self.provenance,
                      "revision": self.revision})

    def metadata(self, tokens: int) -> dict[str, Any]:
        return {"hash": self.span_hash, "provenance": self.provenance,
                "revision": self.revision, "kind": self.kind,
                "priority": self.priority, "handle": self.handle or None,
                "tokens": tokens}




class AdaptiveContextController:
    """Select the smallest justified context without crossing a hard ceiling."""

    def __init__(self, scope: BudgetScope, *, stage: str, task: str,
                 provider: str, expected_revision: str,
                 counter: TokenCounter | None) -> None:
        self.limits = scope.resolve(stage=stage, task=task, provider=provider)
        self.stage, self.task, self.provider = stage, task, provider
        self.expected_revision = expected_revision
        self.counter = counter
        self._selected: list[ContextSpan] = []
        self._selected_hashes: set[str] = set()
        self._token_cache: dict[str, int] = {}
        self._expansions: list[dict[str, Any]] = []
        self._cache_hits = 0
        self._deduped = 0
        self._usage: dict[str, Any] = {
            "input_tokens": None, "output_tokens": None,
            "reasoning_tokens": None, "cached_tokens": None,
            "reason": "provider usage receipt not supplied",
        }

    def _tokens(self, span: ContextSpan) -> int:
        if self.counter is None:
            raise TokenCountUnavailable("cannot enforce hard budget without a token counter")
        if span.span_hash in self._token_cache:
            self._cache_hits += 1
            return self._token_cache[span.span_hash]
        count = self.counter.count(span.content)
        if count < 0:
            raise TokenCountUnavailable("token counter returned an invalid value")
        self._token_cache[span.span_hash] = count
        return count

    @property
    def selected_tokens(self) -> int:
        return sum(self._tokens(span) for span in self._selected)

    def _validate(self, span: ContextSpan) -> None:
        if span.revision != self.expected_revision:
            raise StaleSpan(
                f"span {span.span_hash} revision {span.revision} != {self.expected_revision}"
            )

    def seed(self, spans: Iterable[ContextSpan]) -> dict[str, Any]:
        """Add prioritized signatures/relations/rules/tests up to the soft limit."""
        accepted = 0
        for span in sorted(spans, key=lambda item: (item.priority, item.span_hash)):
            self._validate(span)
            if span.span_hash in self._selected_hashes:
                self._deduped += 1
                continue
            tokens = self._tokens(span)
            if self.selected_tokens + tokens > self.limits.soft_tokens:
                continue
            self._selected.append(span)
            self._selected_hashes.add(span.span_hash)
            accepted += 1
        return self.receipt("SEEDED", accepted=accepted)

    def expand(self, spans: Iterable[ContextSpan], *, reason: ExpansionReason,
               evidence: str) -> dict[str, Any]:
        if not isinstance(reason, ExpansionReason) or not evidence.strip():
            raise InvalidExpansion("expansion requires an observable gap and evidence")
        candidates: list[tuple[ContextSpan, int]] = []
        before = self.selected_tokens
        for span in sorted(spans, key=lambda item: (item.priority, item.span_hash)):
            self._validate(span)
            if span.span_hash in self._selected_hashes:
                self._deduped += 1
                continue
            tokens = self._tokens(span)
            candidates.append((span, tokens))
        if before + sum(tokens for _, tokens in candidates) > self.limits.hard_tokens:
            raise HardBudgetExceeded(
                f"{reason.value}: expansion would cross hard token budget"
            )
        added: list[str] = []
        for span, _ in candidates:
            self._selected.append(span)
            self._selected_hashes.add(span.span_hash)
            added.append(span.span_hash)
        event = {"reason_code": reason.value, "evidence": evidence,
                 "before_tokens": before, "after_tokens": self.selected_tokens,
                 "added_hashes": added}
        event["event_hash"] = _hash(event)
        self._expansions.append(event)
        return self.receipt("EXPANDED", expansion=event)

    def record_provider_usage(self, usage: Mapping[str, Any] | None) -> None:
        if not usage:
            return
        fields = ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")
        normalized: dict[str, Any] = {}
        missing: list[str] = []
        for field_name in fields:
            value = usage.get(field_name)
            if isinstance(value, int) and value >= 0:
                normalized[field_name] = value
            else:
                normalized[field_name] = None
                missing.append(field_name)
        normalized["reason"] = (
            None if not missing else "provider omitted: " + ",".join(missing)
        )
        self._usage = normalized

    def prompt(self) -> dict[str, Any]:
        """Return content plus lazy handles; full receipts remain out-of-band."""
        return {
            "schema": SCHEMA,
            "context": [
                {"content": span.content, "handle": span.handle or None,
                 "hash": span.span_hash, "provenance": span.provenance}
                for span in self._selected
            ],
            "token_count": self.selected_tokens,
            "hard_limit": self.limits.hard_tokens,
        }

    def receipt(self, status: str, **extra: Any) -> dict[str, Any]:
        token_count = self.selected_tokens if self.counter is not None else None
        spans = [span.metadata(self._tokens(span)) for span in self._selected]
        payload = {
            "schema": RECEIPT_SCHEMA, "status": status,
            "scope": {"stage": self.stage, "task": self.task,
                      "provider": self.provider},
            "limits": {"soft_tokens": self.limits.soft_tokens,
                       "hard_tokens": self.limits.hard_tokens},
            "observed": {
                "context_tokens": token_count,
                "counter": self.counter.name if self.counter else None,
                "reason": None if self.counter else "token counter unavailable",
                **self._usage,
            },
            "spans": spans, "expansions": list(self._expansions),
            "cache_hits": self._cache_hits, "deduplicated_spans": self._deduped,
            "hard_budget_respected": (
                token_count is not None and token_count <= self.limits.hard_tokens
            ),
            "local_llm": False,
            **extra,
        }
        payload["receipt_hash"] = _hash(payload)
        return payload


__all__ = [
    "AdaptiveContextController", "BudgetLimits", "BudgetScope", "ContextBudgetError",
    "ContextSpan", "ExpansionReason", "HardBudgetExceeded", "InvalidExpansion",
    "RegexTokenCounter", "StaleSpan", "TiktokenCounter", "TokenCountUnavailable",
]
