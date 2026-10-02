from __future__ import annotations

import time
import unittest
from tempfile import TemporaryDirectory

from simplicio_mapper.hybrid_retrieval import HybridRetriever
from simplicio_mapper.store.neural.pareto_policy import (
    ParetoPolicy,
    Profile,
    RepresentationCandidate,
)
from simplicio_mapper.store.neural.semantic_scoring import (
    INFERENCE_BACKEND_SCHEMA,
    DerivedVectorStore,
    ModelIdentity,
    RuntimeEmbeddingProvider,
    SemanticBudgets,
    SemanticScorer,
    SemanticScoringError,
    SourceDocument,
)
from simplicio_mapper.store.neural.turboquant import quantize
from simplicio_mapper.structural_parser import build_structural_graph

MODEL_SHA = "1" * 64


def fixture_model(*, sha: str = MODEL_SHA, dimension: int = 4) -> ModelIdentity:
    return ModelIdentity(
        model="fixture-embed-small",
        version="1.0",
        sha256=sha,
        preprocessing="lowercase-word-v1",
        dimension=dimension,
        max_tokens=128,
        license="test-fixture-only",
    )


def vectorize(text: str) -> tuple[float, ...]:
    lowered = text.casefold()
    groups = (
        ("login", "auth", "identity", "credential"),
        ("cache", "memo", "store"),
        ("retry", "timeout", "deadline"),
        ("parser", "syntax", "ast"),
    )
    return tuple(float(sum(lowered.count(word) for word in words)) for words in groups)


class FakeBackend:
    def __init__(
        self,
        *,
        schema: str = INFERENCE_BACKEND_SCHEMA,
        operations: tuple[str, ...] = ("embeddings",),
        result_schema: str = "simplicio.inference-result/v1",
        result_model: str = MODEL_SHA,
        failure: Exception | None = None,
        malformed: object | None = None,
    ) -> None:
        self.schema = schema
        self.operations = operations
        self.result_schema = result_schema
        self.result_model = result_model
        self.failure = failure
        self.malformed = malformed
        self.requests: list[dict[str, object]] = []

    def capabilities(self):
        return {"schema": self.schema, "operations": list(self.operations)}

    def infer(self, request, *, deadline, cancel_event):
        self.requests.append(dict(request))
        if self.failure:
            raise self.failure
        vectors = (
            self.malformed
            if self.malformed is not None
            else [vectorize(text) for text in request["inputs"]]
        )
        return {
            "schema": self.result_schema,
            "model_sha256": self.result_model,
            "vectors": vectors,
        }


class SemanticScoringTests(unittest.TestCase):
    def test_model_identity_and_contracts(self) -> None:
        m = fixture_model()
        rec = m.record()
        self.assertEqual(MODEL_SHA, rec["sha256"])
        self.assertEqual(64, len(rec["preprocessing_hash"]))
        with self.assertRaises(ValueError):
            ModelIdentity("m", "1", "invalid_sha", "pre", 4, 128, "lic")

    def test_source_document_validation(self) -> None:
        doc = SourceDocument.create("doc1", "content text", structural_score=0.5)
        self.assertEqual("doc1", doc.canonical_id)
        self.assertEqual(0.5, doc.structural_score)
        with self.assertRaises(ValueError):
            SourceDocument("doc1", "mismatched", doc.source_sha256, 0.5)

    def test_semantic_budgets_validation(self) -> None:
        budgets = SemanticBudgets(max_candidates=64, max_selected=8)
        self.assertEqual(64, budgets.max_candidates)
        with self.assertRaises(ValueError):
            SemanticBudgets(max_candidates=10, max_selected=20)
        with self.assertRaises(ValueError):
            SemanticBudgets(max_index_bytes=200, max_memory_bytes=100)

    def test_runtime_embedding_provider_handshake_and_embed(self) -> None:
        backend = FakeBackend()
        provider = RuntimeEmbeddingProvider(backend, fixture_model())
        vectors = provider.embed(
            ["login user", "cache store"],
            deadline=time.monotonic() + 2.0,
            cancel_event=None,
        )
        self.assertEqual(2, len(vectors))
        self.assertEqual(4, len(vectors[0]))
        self.assertEqual(1.0, vectors[0][0])  # "login" matches group 0
        self.assertEqual(2.0, vectors[1][1])  # "cache", "store" match group 1

    def test_runtime_provider_rejects_bad_backend(self) -> None:
        with self.assertRaises(SemanticScoringError) as ctx:
            RuntimeEmbeddingProvider(FakeBackend(schema="wrong"), fixture_model())
        self.assertEqual("INFERENCE_BACKEND_ABI_MISMATCH", ctx.exception.reason_code)

        with self.assertRaises(SemanticScoringError) as ctx:
            RuntimeEmbeddingProvider(FakeBackend(operations=("other",)), fixture_model())
        self.assertEqual("INFERENCE_BACKEND_CAPABILITY_MISSING", ctx.exception.reason_code)

    def test_runtime_provider_failure_and_deadline(self) -> None:
        failing_backend = FakeBackend(failure=RuntimeError("connection refused"))
        provider = RuntimeEmbeddingProvider(failing_backend, fixture_model())
        with self.assertRaises(SemanticScoringError) as ctx:
            provider.embed(["test"], deadline=time.monotonic() + 1.0, cancel_event=None)
        self.assertEqual("INFERENCE_BACKEND_FAILURE", ctx.exception.reason_code)

        # Past deadline
        ok_provider = RuntimeEmbeddingProvider(FakeBackend(), fixture_model())
        with self.assertRaises(SemanticScoringError) as ctx:
            ok_provider.embed(["test"], deadline=time.monotonic() - 1.0, cancel_event=None)
        self.assertEqual("INFERENCE_DEADLINE_EXCEEDED", ctx.exception.reason_code)

    def test_semantic_scorer_with_runtime_provider_and_store(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = DerivedVectorStore(tmpdir)
            backend = FakeBackend()
            provider = RuntimeEmbeddingProvider(backend, fixture_model())
            scorer = SemanticScorer(provider=provider, store=store)

            docs = [
                SourceDocument.create("d1", "login auth credential", structural_score=0.8),
                SourceDocument.create("d2", "cache memo store", structural_score=0.3),
            ]
            receipt = scorer.score(generation="gen-1", query="login user", candidates=docs)
            self.assertFalse(receipt["fallback"]["used"])
            self.assertEqual("NONE", receipt["fallback"]["reason_code"])
            self.assertTrue(len(receipt["selected"]) > 0)
            self.assertEqual("d1", receipt["selected"][0]["canonical_id"])

    def test_semantic_scorer_deterministic_offline_fallback(self) -> None:
        # No provider passed: purely offline deterministic scoring
        scorer = SemanticScorer(provider=None)
        docs = [
            SourceDocument.create("d1", "user search function", structural_score=0.7),
            SourceDocument.create("d2", "database connector", structural_score=0.1),
        ]
        receipt = scorer.score(generation="gen-1", query="search user", candidates=docs)
        self.assertTrue(receipt["fallback"]["used"])
        self.assertEqual("INFERENCE_BACKEND_UNAVAILABLE", receipt["fallback"]["reason_code"])
        self.assertEqual("d1", receipt["selected"][0]["canonical_id"])
        # Fallback uses formula: 0.80 * lexical + 0.20 * structural
        d1_result = next(r for r in receipt["results"] if r["canonical_id"] == "d1")
        self.assertEqual("deterministic_lexical_structural", d1_result["method"])

    def test_semantic_scorer_falls_back_when_provider_fails(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = DerivedVectorStore(tmpdir)
            failing_backend = FakeBackend(failure=RuntimeError("GPU OOM"))
            provider = RuntimeEmbeddingProvider(failing_backend, fixture_model())
            scorer = SemanticScorer(provider=provider, store=store)

            docs = [SourceDocument.create("d1", "user search query", structural_score=0.5)]
            receipt = scorer.score(generation="gen-1", query="search", candidates=docs)
            self.assertTrue(receipt["fallback"]["used"])
            self.assertEqual("INFERENCE_BACKEND_FAILURE", receipt["fallback"]["reason_code"])
            self.assertEqual("deterministic_lexical_structural", receipt["results"][0]["method"])


class ParetoPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidates = [
            RepresentationCandidate(
                name="dense-4bit",
                representation="dense_quant",
                quality=0.97,
                resident_bytes=160,
                peak_bytes=200,
                tokens_per_second=80.0,
                ttft_ms=40.0,
            ),
            RepresentationCandidate(
                name="sqtn",
                representation="sqtn",
                quality=0.93,
                resident_bytes=80,
                peak_bytes=100,
                tokens_per_second=70.0,
                ttft_ms=45.0,
            ),
            RepresentationCandidate(
                name="mixed",
                representation="mixed",
                quality=0.96,
                resident_bytes=120,
                peak_bytes=140,
                tokens_per_second=90.0,
                ttft_ms=30.0,
            ),
        ]

    def test_profiles_select_best_fit(self) -> None:
        policy_quality = ParetoPolicy(Profile.QUALITY, quality_threshold=0.85)
        decision_q = policy_quality.decide(self.candidates, generation="gen-1")
        self.assertEqual("selected", decision_q.status)
        self.assertEqual("dense-4bit", decision_q.selected_id)

        policy_mem = ParetoPolicy(Profile.MEMORY, quality_threshold=0.85)
        decision_m = policy_mem.decide(self.candidates, generation="gen-1")
        self.assertEqual("selected", decision_m.status)
        self.assertEqual("sqtn", decision_m.selected_id)

        policy_bal = ParetoPolicy(Profile.BALANCED, quality_threshold=0.85)
        decision_b = policy_bal.decide(self.candidates, generation="gen-1")
        self.assertEqual("selected", decision_b.status)
        self.assertEqual("mixed", decision_b.selected_id)

    def test_hard_quality_threshold(self) -> None:
        policy = ParetoPolicy(Profile.BALANCED, quality_threshold=0.965)
        decision = policy.decide(self.candidates, generation="gen-1")
        self.assertEqual("dense-4bit", decision.selected_id)

    def test_cannot_fit_threshold(self) -> None:
        policy = ParetoPolicy(Profile.BALANCED, quality_threshold=0.99)
        decision = policy.decide(self.candidates, generation="gen-1")
        self.assertEqual("cannot_fit", decision.status)
        self.assertIsNone(decision.selected)


class HybridRetrieverIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        graph, _ = build_structural_graph(
            [
                ("auth.py", "def login_user(username, password):\n    return check_credentials(username)\n"),
                ("cache.py", "def get_cached_session(token):\n    return session_store.get(token)\n"),
            ],
            repo_identity="test-repo",
            generation_id="gen-1",
        )
        cls.graph = graph
        functions = graph.find(kind=graph.nodes[1].kind)
        cls.documents = {
            node.node_id: f"{node.qualified_name} {node.path} auth login session cache"
            for node in functions
        }

    def test_retriever_with_turboquant_vectors(self) -> None:
        retriever = HybridRetriever(self.graph)
        node_ids = list(self.documents.keys())
        query_vec = (1.0, 0.0, 0.0, 0.0)
        # One candidate aligns with query, other is orthogonal
        quantized = {
            node_ids[0]: quantize((1.0, 0.0, 0.0, 0.0), seed=42),
            node_ids[1]: quantize((0.0, 1.0, 0.0, 0.0), seed=42),
        }
        response = retriever.retrieve(
            "login",
            self.documents,
            query_vector=query_vec,
            quantized_vectors=quantized,
            token_budget=200,
        )
        self.assertTrue(response.vector_available)
        self.assertEqual(node_ids[0], response.candidates[0].node_id)
        self.assertIn("vector", response.candidates[0].reason_codes)

    def test_retriever_with_semantic_scorer_success(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = DerivedVectorStore(tmpdir)
            backend = FakeBackend()
            provider = RuntimeEmbeddingProvider(backend, fixture_model())
            scorer = SemanticScorer(provider=provider, store=store)
            retriever = HybridRetriever(self.graph, semantic_scorer=scorer)

            response = retriever.retrieve(
                "login credential",
                self.documents,
                token_budget=200,
            )
            self.assertTrue(response.vector_available)
            self.assertIsNotNone(response.semantic_receipt)
            self.assertFalse(response.semantic_receipt["fallback"]["used"])

    def test_retriever_with_failing_provider_falls_back_deterministically(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = DerivedVectorStore(tmpdir)
            failing_backend = FakeBackend(failure=RuntimeError("Runtime service down"))
            provider = RuntimeEmbeddingProvider(failing_backend, fixture_model())
            scorer = SemanticScorer(provider=provider, store=store)
            retriever = HybridRetriever(self.graph, semantic_scorer=scorer)

            # Should not raise! Deterministic fallback
            response = retriever.retrieve(
                "auth login",
                self.documents,
                token_budget=200,
            )
            self.assertTrue(len(response.candidates) > 0)
            self.assertIsNotNone(response.semantic_receipt)
            self.assertTrue(response.semantic_receipt["fallback"]["used"])

    def test_retriever_with_pareto_selection(self) -> None:
        retriever = HybridRetriever(self.graph)
        response = retriever.retrieve(
            "auth login",
            self.documents,
            token_budget=200,
            use_pareto=True,
            pareto_profile="balanced",
        )
        self.assertTrue(len(response.candidates) > 0)
        self.assertIsNotNone(response.pareto_receipt)
        self.assertEqual("selected", response.pareto_receipt.get("status"))


if __name__ == "__main__":
    unittest.main()
