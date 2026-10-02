"""Local-first hybrid retrieval over graph-linked documents.

The module never creates an embedding backend. Callers may provide cached
vector scores; lexical and graph signals remain a complete deterministic
fallback when vectors are unavailable.
Now supports TurboQuant 4-bit compressed vector scoring, SemanticScorer
Runtime integration with deterministic fallback, and Pareto representation policies.
"""

from __future__ import annotations

import math
import re
from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from .store.neural.pareto_policy import (
    ParetoPolicy,
    Profile,
    RepresentationCandidate,
    RepresentationKind,
)
from .store.neural.semantic_scoring import (
    EmbeddingProvider,
    SemanticScorer,
    SourceDocument,
)
from .store.neural.turboquant import (
    QuantizedVector,
    approximate_candidates,
)
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
    semantic_receipt: dict[str, Any] | None = None
    pareto_receipt: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
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
        if self.semantic_receipt is not None:
            payload["semantic_receipt"] = self.semantic_receipt
        if self.pareto_receipt is not None:
            payload["pareto_receipt"] = self.pareto_receipt
        return payload


class HybridRetriever:
    def __init__(
        self,
        graph: StructuralGraph,
        policy: RankingPolicy | None = None,
        *,
        semantic_scorer: SemanticScorer | None = None,
        pareto_policy: ParetoPolicy | None = None,
    ) -> None:
        self.graph = graph
        self.policy = policy or RankingPolicy()
        self.semantic_scorer = semantic_scorer
        self.pareto_policy = pareto_policy

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
        provider: EmbeddingProvider | None = None,
        scorer: SemanticScorer | None = None,
        query_vector: Sequence[float] | None = None,
        quantized_vectors: Mapping[str, QuantizedVector] | None = None,
        quantized_metric: Literal["cosine", "dot", "l2"] = "dot",
        use_pareto: bool = False,
        pareto_profile: Profile | str | None = None,
    ) -> RetrievalResponse:
        if token_budget < 1 or limit < 1:
            raise ValueError("token_budget and limit must be positive")

        lexical = self._lexical_scores(query, documents)
        graph_scores = self._graph_scores(seed_node_ids, documents)
        path_scores = self._path_scores(query, documents)

        semantic_receipt: dict[str, Any] | None = None
        pareto_receipt: dict[str, Any] | None = None

        # 1. Try TurboQuant approximate scoring if quantized vectors and query_vector provided
        if vector_scores is None and quantized_vectors is not None and query_vector is not None:
            try:
                candidate_pairs = [
                    (node_id, quantized_vectors[node_id])
                    for node_id in documents
                    if node_id in quantized_vectors
                ]
                if candidate_pairs:
                    seed = getattr(candidate_pairs[0][1], "seed", 0)
                    approx = approximate_candidates(
                        query_vector,
                        candidate_pairs,
                        seed=seed,
                        metric=quantized_metric,
                        candidate_k=len(candidate_pairs),
                    )
                    raw_scores = {item.canonical_id: item.score for item in approx}
                    min_s = min(raw_scores.values())
                    max_s = max(raw_scores.values())
                    diff = max_s - min_s
                    if diff > 1e-9:
                        vector_scores = {k: (v - min_s) / diff for k, v in raw_scores.items()}
                    else:
                        vector_scores = {k: 1.0 if v > 0 else 0.0 for k, v in raw_scores.items()}
            except Exception:  # noqa: BLE001
                vector_scores = None

        # 2. Try SemanticScorer / EmbeddingProvider if vector_scores not yet computed
        if vector_scores is None and (scorer is not None or self.semantic_scorer is not None or provider is not None):
            active_scorer = scorer or self.semantic_scorer
            if active_scorer is None and provider is not None:
                active_scorer = SemanticScorer(provider=provider)
            if active_scorer is not None:
                try:
                    source_candidates = [
                        SourceDocument.create(
                            node_id,
                            text,
                            structural_score=graph_scores.get(node_id, 0.0),
                        )
                        for node_id, text in documents.items()
                    ]
                    score_res = active_scorer.score(
                        generation=self.graph.generation_id,
                        query=query,
                        candidates=source_candidates,
                    )
                    semantic_receipt = score_res
                    if not score_res.get("fallback", {}).get("used", True):
                        extracted_scores = {}
                        for r in score_res.get("results", []):
                            cid = r["canonical_id"]
                            c_semantic = r.get("components", {}).get("semantic")
                            if c_semantic is not None:
                                extracted_scores[cid] = float(c_semantic)
                            else:
                                extracted_scores[cid] = float(r.get("score", 0.0))
                        if extracted_scores:
                            vector_scores = extracted_scores
                except Exception:  # noqa: BLE001
                    # Deterministic fallback without failing
                    vector_scores = None

        resolved_vector_scores = dict(vector_scores or {})
        vector_available = bool(resolved_vector_scores)

        candidates: list[RetrievalCandidate] = []
        vector_weight = self.policy.vector_weight if vector_available else 0.0
        denominator = self.policy.lexical_weight + vector_weight + self.policy.graph_weight + self.policy.path_weight
        for node_id, text in documents.items():
            scores = (
                lexical.get(node_id, 0.0),
                max(0.0, min(1.0, float(resolved_vector_scores.get(node_id, 0.0)))),
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

        # 3. Optional Pareto policy selection
        if use_pareto or pareto_profile is not None or self.pareto_policy is not None:
            active_pareto = self.pareto_policy or ParetoPolicy(
                Profile.parse(pareto_profile) if pareto_profile else Profile.BALANCED
            )
            try:
                rep_candidates = [
                    RepresentationCandidate(
                        name=cand.node_id,
                        representation=RepresentationKind.DENSE_QUANT,
                        quality=max(0.0, min(1.0, cand.score)),
                        resident_bytes=max(1, len(cand.text.encode("utf-8"))),
                        peak_bytes=max(2, len(cand.text.encode("utf-8")) * 2),
                        tokens_per_second=100.0,
                        ttft_ms=10.0,
                    )
                    for cand in candidates
                ]
                decision = active_pareto.decide(
                    rep_candidates,
                    generation=self.graph.generation_id,
                )
                pareto_receipt = decision.receipt.to_dict()
                if decision.selected_id:
                    frontier = set(decision.receipt.pareto_frontier)
                    candidates.sort(
                        key=lambda c: (
                            0 if c.node_id == decision.selected_id else (1 if c.node_id in frontier else 2),
                            -c.score,
                            c.node_id,
                        )
                    )
            except Exception:  # noqa: BLE001
                pareto_receipt = None

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

        return RetrievalResponse(
            query,
            self.graph.generation_id,
            self.policy.version,
            tuple(selected),
            vector_available,
            token_budget,
            estimated,
            omitted > 0,
            omitted,
            semantic_receipt=semantic_receipt,
            pareto_receipt=pareto_receipt,
        )


__all__ = [
    "HybridRetriever",
    "RankingPolicy",
    "RetrievalCandidate",
    "RetrievalResponse",
    "RANKING_POLICY_VERSION",
]
