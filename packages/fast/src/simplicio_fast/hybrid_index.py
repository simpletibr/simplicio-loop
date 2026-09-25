"""Deterministic lexical + optional 4-bit candidates with full-precision reranking."""

from __future__ import annotations


class IndexError(RuntimeError):
    pass


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


class HybridIndex:
    def __init__(self, docs, vectors=None, version="v1"):
        self.docs = docs
        self.vectors = vectors or {}
        self.version = version

    def search(self, query, qvec=None, k=10, index_version="v1"):
        if index_version != self.version:
            raise IndexError("index_stale")
        terms = set(query.lower().split())
        lex = {
            i: len(terms & set(text.lower().split())) for i, text in self.docs.items()
        }
        method = "lexical"
        scores = {i: float(v) for i, v in lex.items()}
        if qvec is not None and self.vectors:
            method = "hybrid_4bit_rerank"
            scale = max(max(abs(x) for x in qvec), 1e-9) / 7
            q4 = [round(x / scale) for x in qvec]

            def coarse(i):
                vector = self.vectors[i]
                vscale = max(max(abs(y) for y in vector), 1e-9) / 7
                return lex[i] + dot(q4, [round(x / vscale) for x in vector])

            cand = sorted(self.vectors, key=lambda i: (-coarse(i), -lex[i], i))[
                : max(k * 2, k)
            ]
            scores = {i: lex[i] + dot(qvec, self.vectors[i]) for i in cand}
        ranked = sorted(scores, key=lambda i: (-scores[i], i))[:k]
        return [
            {
                "id": i,
                "score": scores[i],
                "method": method,
                "index_version": self.version,
            }
            for i in ranked
        ]


def parity(py, rust=None):
    return {
        "parity": None if rust is None else py == rust,
        "null_reason": "RUST_UNAVAILABLE" if rust is None else None,
    }
