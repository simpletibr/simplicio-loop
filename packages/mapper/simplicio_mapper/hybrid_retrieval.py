"""Local-first hybrid retrieval over graph-linked documents.

The module never creates an embedding backend. Callers may provide cached
vector scores; lexical and graph signals remain a complete deterministic
fallback when vectors are unavailable.
"""

from __future__ import annotations

import math
import re
from collections import Counter, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .structural_graph import StructuralGraph

RANKING_POLICY_VERSION = "simplicio.hybrid-retrieval/v1"
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(value: str) -> tuple[str, ...]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value).replace("_", " ").replace("-", " ")
    return tuple(token.casefold() for token in _TOKEN_RE.findall(expanded))


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    return len(a & b) / len(a | b) if a or b else 1.0


@dataclass(frozen=True, slots=True)
class RankingPolicy:
    lexical_weight: float = 0.45
    vector_weight: float = 0.30
    graph_weight: float = 0.15
    path_weight: float = 0.10
    near_duplicate_threshold: float = 0.88
    version: str = RANKING_POLICY_VERSION

    def __post_init__(self) -> None:
        values = (self.lexical_weight, self.vector_weight, self.graph_weight, self.path_weight)
        if any(value < 0 for value in values) or not math.isclose(sum(values), 1.0, abs_tol=1e-9):
            raise ValueError("ranking weights must be non-negative and sum to 1")


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    node_id: str
    score: float
    lexical_score: float
    vector_score: float
    graph_score: float
    path_score: float
    reason_codes: tuple[str, ...]
    evidence: tuple[str, ...]
    text: str

    def compact(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "score": round(self.score, 6),
            "reason_codes": list(self.reason_codes),
            "evidence": list(self.evidence),
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class RetrievalResponse:
    query: str
    generation_id: str
    policy_version: str
    candidates: tuple[RetrievalCandidate, ...]
    vector_available: bool
    token_budget: int
    estimated_tokens: int
    truncated: bool
    omitted_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RANKING_POLICY_VERSION,
            "query": self.query,
            "generation_id": self.generation_id,
            "policy_version": self.policy_version,
            "vector_available": self.vector_available,
            "token_budget": self.token_budget,
            "estimated_tokens": self.estimated_tokens,
            "truncated": self.truncated,
            "omitted_count": self.omitted_count,
            "results": [candidate.compact() for candidate in self.candidates],
        }


class HybridRetriever:
    def __init__(self, graph: StructuralGraph, policy: RankingPolicy | None = None) -> None:
        self.graph = graph
        self.policy = policy or RankingPolicy()

    def _lexical_scores(self, query: str, documents: Mapping[str, str]) -> dict[str, float]:
        query_terms = set(_tokens(query))
        if not query_terms:
            return {key: 0.0 for key in documents}
        document_terms = {key: _tokens(value) for key, value in documents.items()}
        document_frequency = Counter(term for terms in document_terms.values() for term in set(terms))
        total = max(1, len(document_terms))
        raw: dict[str, float] = {}
        for node_id, terms in document_terms.items():
            counts = Counter(terms)
            score = 0.0
            for term in query_terms:
                if not counts[term]:
                    continue
                idf = math.log(1.0 + (total - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                score += idf * (counts[term] / max(1, len(terms)))
            raw[node_id] = score
        maximum = max(raw.values(), default=0.0)
        return {key: (value / maximum if maximum else 0.0) for key, value in raw.items()}

    def _graph_scores(self, seeds: Iterable[str], documents: Mapping[str, str]) -> dict[str, float]:
        scores = {key: 0.0 for key in documents}
        queue: deque[tuple[str, int]] = deque((seed, 0) for seed in sorted(set(seeds)) if self.graph.get(seed))
        seen = set(seed for seed, _ in queue)
        while queue:
            current, distance = queue.popleft()
            if current in scores:
                scores[current] = max(scores[current], 1.0 / (distance + 1))
            if distance >= 3:
                continue
            for neighbor in self.graph.neighbors(current):
                if neighbor.node_id not in seen:
                    seen.add(neighbor.node_id)
                    queue.append((neighbor.node_id, distance + 1))
            for neighbor in self.graph.neighbors(current, inbound=True):
                if neighbor.node_id not in seen:
                    seen.add(neighbor.node_id)
                    queue.append((neighbor.node_id, distance + 1))
        return scores

    @staticmethod
    def _path_scores(query: str, documents: Mapping[str, str]) -> dict[str, float]:
        terms = set(_tokens(query))
        return {key: (len(terms & set(_tokens(value))) / len(terms) if terms else 0.0) for key, value in documents.items()}

    def retrieve(
        self,
        query: str,
        documents: Mapping[str, str],
        *,
        vector_scores: Mapping[str, float] | None = None,
        seed_node_ids: Iterable[str] = (),
        token_budget: int = 512,
        limit: int = 20,
    ) -> RetrievalResponse:
        if token_budget < 1 or limit < 1:
            raise ValueError("token_budget and limit must be positive")
        vector_scores = dict(vector_scores or {})
        vector_available = bool(vector_scores)
        lexical = self._lexical_scores(query, documents)
        graph_scores = self._graph_scores(seed_node_ids, documents)
        path_scores = self._path_scores(query, documents)
        candidates: list[RetrievalCandidate] = []
        vector_weight = self.policy.vector_weight if vector_available else 0.0
        denominator = self.policy.lexical_weight + vector_weight + self.policy.graph_weight + self.policy.path_weight
        for node_id, text in documents.items():
            scores = (
                lexical.get(node_id, 0.0),
                max(0.0, min(1.0, float(vector_scores.get(node_id, 0.0)))),
                graph_scores.get(node_id, 0.0),
                path_scores.get(node_id, 0.0),
            )
            weights = (self.policy.lexical_weight, vector_weight, self.policy.graph_weight, self.policy.path_weight)
            score = sum(value * weight for value, weight in zip(scores, weights, strict=True)) / denominator
            reasons = tuple(name for name, value in zip(("lexical", "vector", "graph", "path"), scores, strict=True) if value > 0)
            node = self.graph.get(node_id)
            evidence = (f"{node.path}:{node.start_line}-{node.end_line}",) if node and node.path else ()
            candidates.append(RetrievalCandidate(node_id, score, *scores, reasons, evidence, text))
        candidates.sort(key=lambda item: (-item.score, item.node_id))
        selected: list[RetrievalCandidate] = []
        estimated = 0
        omitted = 0
        for candidate in candidates:
            if len(selected) >= limit:
                omitted += 1
                continue
            candidate_terms = _tokens(candidate.text)
            if any(_jaccard(candidate_terms, _tokens(existing.text)) >= self.policy.near_duplicate_threshold for existing in selected):
                omitted += 1
                continue
            cost = max(1, len(candidate.text) // 4)
            if estimated + cost > token_budget:
                omitted += 1
                continue
            selected.append(candidate)
            estimated += cost
        return RetrievalResponse(query, self.graph.generation_id, self.policy.version, tuple(selected), vector_available, token_budget, estimated, omitted > 0, omitted)


__all__ = ["HybridRetriever", "RankingPolicy", "RetrievalCandidate", "RetrievalResponse", "RANKING_POLICY_VERSION"]
