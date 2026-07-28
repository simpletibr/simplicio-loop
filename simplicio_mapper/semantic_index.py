"""Optional semantic index enrichment (simplicio.mapper.semantic-index/v1).

Structural mapper facts remain canonical. Embeddings only suggest proximity;
they never create factual edges alone. Default mode is deterministic-only
(no Runtime InferenceBackend required).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

SEMANTIC_SCHEMA = "simplicio.mapper.semantic-index/v1"
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


class SemanticIndexError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _tokens(text: str) -> list[str]:
    return sorted({tok.casefold() for tok in _TOKEN_RE.findall(text or "")})


def _hash_embedding(tokens: Sequence[str], *, dims: int = 32) -> list[float]:
    """Deterministic bag-of-tokens pseudo-embedding (not a neural model)."""
    vec = [0.0] * dims
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for i in range(dims):
            vec[i] += ((digest[i % len(digest)] / 255.0) * 2.0) - 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 8) for v in vec]


def build_semantic_index(
    items: Sequence[Mapping[str, Any]],
    *,
    model: str = "deterministic-hash/v1",
    revision: str = "1",
    enable_ml: bool = False,
) -> dict[str, Any]:
    """Build an optional semantic index.

    When ``enable_ml`` is False (default), only deterministic hash embeddings
    are emitted. ML backends are intentionally not invoked here — Runtime
    InferenceBackend remains optional and out of process.
    """
    if enable_ml:
        # Fail closed until Runtime backend is bound; never invent neural output.
        raise SemanticIndexError(
            "ml_backend_unavailable",
            "InferenceBackend/v1 not bound; use enable_ml=False for deterministic-only",
        )
    entries: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or item.get("fact_id") or "")
        text = str(item.get("text") or item.get("key") or "")
        if not item_id:
            raise SemanticIndexError("item_id_missing", text[:40])
        tokens = _tokens(text)
        emb = _hash_embedding(tokens)
        source_hash = _sha({"id": item_id, "text": text, "tokens": tokens})
        entries.append(
            {
                "id": item_id,
                "tokens": tokens,
                "embedding": emb,
                "kind": "inferred",
                "confidence": 0.4 if tokens else 0.0,
                "source_hash": source_hash,
                "fact": False,
                "inferred": True,
            }
        )
    entries = sorted(entries, key=lambda row: row["id"])
    body = {
        "schema": SEMANTIC_SCHEMA,
        "model": model,
        "revision": revision,
        "model_hash": _sha({"model": model, "revision": revision}),
        "preprocessing": {"tokenizer": "regex_identifier_v1", "normalize": "casefold"},
        "generation": _sha([row["source_hash"] for row in entries]),
        "entries": entries,
        "related_suggestions": _related(entries),
        "policy": {
            "creates_factual_edges": False,
            "optional": True,
            "default_mode": "deterministic-only",
            "ignore_safe": True,
        },
    }
    body["index_digest"] = _sha(body)
    return body


def _related(entries: Sequence[Mapping[str, Any]], *, top_k: int = 3) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for i, left in enumerate(entries):
        scored: list[tuple[float, str]] = []
        for j, right in enumerate(entries):
            if i == j:
                continue
            score = _cosine(left["embedding"], right["embedding"])
            if score <= 0:
                continue
            scored.append((score, right["id"]))
        scored.sort(key=lambda item: (-item[0], item[1]))
        for score, other_id in scored[:top_k]:
            suggestions.append(
                {
                    "source_id": left["id"],
                    "target_id": other_id,
                    "score": round(score, 6),
                    "kind": "inferred",
                    "fact": False,
                    "confidence": min(0.5, round(score, 6)),
                }
            )
    return sorted(suggestions, key=lambda row: (row["source_id"], -row["score"], row["target_id"]))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def validate_semantic_index(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema") != SEMANTIC_SCHEMA:
        raise SemanticIndexError("schema_invalid", str(payload.get("schema")))
    if payload.get("policy", {}).get("creates_factual_edges") is not False:
        raise SemanticIndexError("policy_invalid", "creates_factual_edges must be false")
    unsigned = {k: v for k, v in payload.items() if k != "index_digest"}
    if payload.get("index_digest") != _sha(unsigned):
        raise SemanticIndexError("digest_mismatch", str(payload.get("index_digest")))
    return dict(payload)


__all__ = [
    "SEMANTIC_SCHEMA",
    "SemanticIndexError",
    "build_semantic_index",
    "validate_semantic_index",
]
