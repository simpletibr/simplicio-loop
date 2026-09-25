from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from simplicio_fast.semantic_scoring import (
    ARTIFACT_SCHEMA,
    INFERENCE_BACKEND_SCHEMA,
    DerivedVectorStore,
    LocalLiteRTAdapter,
    ModelIdentity,
    RuntimeEmbeddingProvider,
    SemanticBudgets,
    SemanticScorer,
    SemanticScoringError,
    SourceDocument,
    lexical_score,
    semantic_capabilities,
)


MODEL_SHA = "1" * 64


def model(*, sha: str = MODEL_SHA, dimension: int = 4) -> ModelIdentity:
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


class FailingProvider:
    identity = model()

    def embed(self, texts, *, deadline, cancel_event):
        raise SemanticScoringError("DEVICE_UNAVAILABLE")


class FakeSession:
    def __init__(self, *, failure: bool = False):
        self.failure = failure

    def embed(self, texts):
        if self.failure:
            raise RuntimeError("boom")
        return [vectorize(text) for text in texts]


class BoostReranker:
    def rerank(self, query, candidates, *, deadline, cancel_event):
        return {
            item.canonical_id: (1.0 if item.canonical_id == "b" else 0.0)
            for item in candidates
        }


class BadReranker:
    def __init__(self, value):
        self.value = value

    def rerank(self, query, candidates, *, deadline, cancel_event):
        return self.value


class ModelAndContractsTests(unittest.TestCase):
    def test_model_identity_carries_all_cache_scope(self):
        value = model()
        record = value.record()
        self.assertEqual(MODEL_SHA, record["sha256"])
        self.assertEqual(64, len(record["preprocessing_hash"]))
        self.assertEqual("test-fixture-only", record["license"])

    def test_model_rejects_invalid_contract(self):
        for kwargs in (
            {"sha256": "bad"},
            {"dimension": 0},
            {"max_tokens": 0},
            {"model": ""},
        ):
            values = {
                "model": "m",
                "version": "1",
                "sha256": MODEL_SHA,
                "preprocessing": "p",
                "dimension": 2,
                "max_tokens": 1,
                "license": "fixture",
                **kwargs,
            }
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ModelIdentity(**values)

    def test_source_hash_is_authoritative(self):
        source = SourceDocument.create("id", "hello", structural_score=0.5)
        self.assertEqual(64, len(source.source_sha256))
        with self.assertRaises(ValueError):
            SourceDocument("id", "changed", source.source_sha256)
        with self.assertRaises(ValueError):
            SourceDocument.create("id", "text", structural_score=2)

    def test_budgets_are_bounded_and_coherent(self):
        with self.assertRaises(ValueError):
            SemanticBudgets(max_candidates=1, max_selected=2)
        with self.assertRaises(ValueError):
            SemanticBudgets(max_index_bytes=2, max_memory_bytes=1)
        with self.assertRaises(ValueError):
            SemanticBudgets(max_batch_size=0)

    def test_lexical_is_normalized_and_deterministic(self):
        self.assertEqual(0.5, lexical_score("cache retry", "CACHE works"))
        self.assertEqual(0.0, lexical_score("", "cache"))

    def test_lexical_normalizes_identifier_boundaries(self):
        self.assertEqual(
            1.0,
            lexical_score("reuse computed values", "reuse_computed_values"),
        )
        self.assertEqual(1.0, lexical_score("memo store", "MemoStore"))


class RuntimeProviderTests(unittest.TestCase):
    def test_runtime_provider_handshake_and_request_contract(self):
        backend = FakeBackend()
        provider = RuntimeEmbeddingProvider(backend, model())
        vectors = provider.embed(
            ("login", "cache"), deadline=time.monotonic() + 2, cancel_event=None
        )
        self.assertEqual(((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0)), vectors)
        request = backend.requests[0]
        self.assertEqual("simplicio.inference-request/v1", request["schema"])
        self.assertEqual("embeddings", request["operation"])
        self.assertEqual(MODEL_SHA, request["model"]["sha256"])

    def test_runtime_provider_rejects_bad_handshake(self):
        with self.assertRaises(SemanticScoringError) as caught:
            RuntimeEmbeddingProvider(FakeBackend(schema="wrong"), model())
        self.assertEqual("INFERENCE_BACKEND_ABI_MISMATCH", caught.exception.reason_code)
        with self.assertRaises(SemanticScoringError) as caught:
            RuntimeEmbeddingProvider(FakeBackend(operations=("rerank",)), model())
        self.assertEqual(
            "INFERENCE_BACKEND_CAPABILITY_MISSING", caught.exception.reason_code
        )

    def test_runtime_provider_rejects_response_drift(self):
        cases = (
            (FakeBackend(result_schema="wrong"), "INFERENCE_RESPONSE_SCHEMA_MISMATCH"),
            (FakeBackend(result_model="2" * 64), "INFERENCE_MODEL_MISMATCH"),
            (FakeBackend(malformed=[[1.0]]), "INFERENCE_DIMENSION_MISMATCH"),
            (FakeBackend(malformed=[[math.nan] * 4]), "INFERENCE_VECTOR_NONFINITE"),
            (FakeBackend(malformed=[]), "INFERENCE_RESPONSE_COUNT_MISMATCH"),
            (FakeBackend(malformed="bad"), "INFERENCE_RESPONSE_MALFORMED"),
        )
        for backend, reason in cases:
            with self.subTest(reason=reason):
                provider = RuntimeEmbeddingProvider(backend, model())
                with self.assertRaises(SemanticScoringError) as caught:
                    provider.embed(
                        ["login"], deadline=time.monotonic() + 2, cancel_event=None
                    )
                self.assertEqual(reason, caught.exception.reason_code)

    def test_runtime_failure_and_deadline_cancel_have_reason_codes(self):
        provider = RuntimeEmbeddingProvider(
            FakeBackend(failure=RuntimeError("down")), model()
        )
        with self.assertRaises(SemanticScoringError) as caught:
            provider.embed(["x"], deadline=time.monotonic() + 1, cancel_event=None)
        self.assertEqual("INFERENCE_BACKEND_FAILURE", caught.exception.reason_code)
        provider = RuntimeEmbeddingProvider(FakeBackend(), model())
        with self.assertRaises(SemanticScoringError) as caught:
            provider.embed(["x"], deadline=time.monotonic() - 1, cancel_event=None)
        self.assertEqual("INFERENCE_DEADLINE_EXCEEDED", caught.exception.reason_code)
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(SemanticScoringError) as caught:
            provider.embed(["x"], deadline=time.monotonic() + 1, cancel_event=cancelled)
        self.assertEqual("INFERENCE_CANCELLED", caught.exception.reason_code)

    def test_litert_adapter_is_explicitly_test_only(self):
        with self.assertRaises(SemanticScoringError) as caught:
            LocalLiteRTAdapter(FakeSession(), model())
        self.assertEqual("DIRECT_LITERT_FORBIDDEN", caught.exception.reason_code)
        with self.assertRaises(SemanticScoringError) as caught:
            LocalLiteRTAdapter(object(), model(), isolated_test=True)
        self.assertEqual("LITERT_SESSION_INVALID", caught.exception.reason_code)
        adapter = LocalLiteRTAdapter(FakeSession(), model(), isolated_test=True)
        self.assertEqual(
            ((1.0, 0.0, 0.0, 0.0),),
            adapter.embed(["login"], deadline=time.monotonic() + 1, cancel_event=None),
        )
        adapter = LocalLiteRTAdapter(
            FakeSession(failure=True), model(), isolated_test=True
        )
        with self.assertRaises(SemanticScoringError) as caught:
            adapter.embed(["login"], deadline=time.monotonic() + 1, cancel_event=None)
        self.assertEqual("LITERT_INFERENCE_FAILURE", caught.exception.reason_code)


class DerivedStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = DerivedVectorStore(self.temporary.name)
        self.backend = FakeBackend()
        self.provider = RuntimeEmbeddingProvider(self.backend, model())
        self.budgets = SemanticBudgets(max_batch_size=1)
        self.sources = (
            SourceDocument.create("a", "login identity"),
            SourceDocument.create("b", "cache store"),
        )

    def refresh(self, sources=None, generation="g1", provider=None, budgets=None):
        return self.store.refresh(
            generation,
            (provider or self.provider).identity,
            sources or self.sources,
            provider or self.provider,
            budgets or self.budgets,
            deadline=time.monotonic() + 5,
        )

    def test_content_addressed_refresh_and_incremental_reuse(self):
        first = self.refresh()
        self.assertEqual(2, first["embedded"])
        self.assertEqual(2, first["batches"])
        second = self.refresh()
        self.assertEqual(0, second["embedded"])
        self.assertEqual(2, second["reused"])
        self.assertEqual(first["artifact_sha256"], second["artifact_sha256"])
        manifest, vectors = self.store.load("g1", model())
        self.assertEqual(ARTIFACT_SCHEMA, manifest["schema"])
        self.assertEqual({"a", "b"}, set(vectors))

    def test_only_changed_source_is_recomputed_and_removed_is_pruned(self):
        self.refresh()
        changed = (
            SourceDocument.create("a", "login credential changed"),
            self.sources[1],
        )
        receipt = self.refresh(changed)
        self.assertEqual(1, receipt["embedded"])
        self.assertEqual(1, receipt["reused"])
        receipt = self.refresh((changed[0],))
        self.assertEqual(1, receipt["removed"])
        _, vectors = self.store.load("g1", model())
        self.assertEqual({"a"}, set(vectors))

    def test_generation_model_and_preprocessing_never_cross(self):
        self.refresh()
        self.refresh(generation="g2")
        other = model(sha="2" * 64)
        other_provider = RuntimeEmbeddingProvider(
            FakeBackend(result_model="2" * 64), other
        )
        self.refresh(generation="g1", provider=other_provider)
        keys = {
            self.store.cache_key("g1", model()),
            self.store.cache_key("g2", model()),
            self.store.cache_key("g1", other),
        }
        self.assertEqual(3, len(keys))

    def test_corrupt_artifact_is_discarded_and_rebuilt(self):
        self.refresh()
        manifest, _ = self.store.load("g1", model())
        path = Path(self.temporary.name) / "objects" / manifest["vectors_file"]
        path.write_bytes(b"truncated")
        rebuilt = self.refresh()
        self.assertTrue(rebuilt["corrupt_rebuilt"])
        self.assertEqual(2, rebuilt["embedded"])
        self.store.load("g1", model())

    def test_store_fails_closed_on_scope_and_manifest_corruption(self):
        with self.assertRaises(SemanticScoringError) as caught:
            self.store.load("missing", model())
        self.assertEqual("VECTOR_ARTIFACT_MISSING", caught.exception.reason_code)
        self.refresh()
        manifest_path = self.store._manifest_path("g1", model())
        value = json.loads(manifest_path.read_text())
        value["generation"] = "other"
        manifest_path.write_text(json.dumps(value))
        with self.assertRaises(SemanticScoringError) as caught:
            self.store.load("g1", model())
        self.assertEqual("VECTOR_ARTIFACT_SCOPE_MISMATCH", caught.exception.reason_code)

    def test_store_enforces_batch_request_index_and_memory_budgets(self):
        with self.assertRaises(SemanticScoringError) as caught:
            self.refresh(
                budgets=SemanticBudgets(
                    max_candidates=1,
                    max_selected=1,
                    max_batch_size=1,
                )
            )
        self.assertEqual("CANDIDATE_BUDGET_EXCEEDED", caught.exception.reason_code)
        with self.assertRaises(SemanticScoringError) as caught:
            self.refresh(
                budgets=SemanticBudgets(
                    max_request_bytes=1,
                    max_index_bytes=1024,
                    max_memory_bytes=2048,
                )
            )
        self.assertEqual("REQUEST_BYTES_BUDGET_EXCEEDED", caught.exception.reason_code)
        with self.assertRaises(SemanticScoringError) as caught:
            self.refresh(
                budgets=SemanticBudgets(
                    max_index_bytes=1,
                    max_memory_bytes=1024,
                )
            )
        self.assertEqual("INDEX_BYTES_BUDGET_EXCEEDED", caught.exception.reason_code)


class ScorerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.candidates = (
            SourceDocument.create("a", "login identity handler", structural_score=0.4),
            SourceDocument.create("b", "cache memo store", structural_score=0.2),
            SourceDocument.create("c", "syntax parser ast", structural_score=0.1),
        )

    def test_offline_path_is_complete_stable_and_provenanced(self):
        scorer = SemanticScorer(
            budgets=SemanticBudgets(max_selected=2), minimum_confidence=0
        )
        first = scorer.score(generation="g1", query="cache", candidates=self.candidates)
        second = scorer.score(
            generation="g1", query="cache", candidates=tuple(reversed(self.candidates))
        )
        self.assertEqual(
            [item["canonical_id"] for item in first["selected"]],
            [item["canonical_id"] for item in second["selected"]],
        )
        self.assertEqual("b", first["selected"][0]["canonical_id"])
        self.assertTrue(first["fallback"]["used"])
        self.assertEqual(
            "INFERENCE_BACKEND_UNAVAILABLE", first["fallback"]["reason_code"]
        )
        self.assertEqual("snapshot_and_source_sha256", first["authority"]["source"])
        self.assertIsNone(first["selected"][0]["provenance"]["model_sha256"])

    def test_runtime_semantic_recovers_synonym_and_scopes_cache(self):
        provider = RuntimeEmbeddingProvider(FakeBackend(), model())
        scorer = SemanticScorer(
            provider=provider,
            store=DerivedVectorStore(self.temporary.name),
            minimum_confidence=0,
        )
        receipt = scorer.score(
            generation="g1", query="authentication", candidates=self.candidates
        )
        self.assertEqual("a", receipt["selected"][0]["canonical_id"])
        self.assertFalse(receipt["fallback"]["used"])
        self.assertEqual(MODEL_SHA, receipt["model"]["sha256"])
        self.assertEqual(
            MODEL_SHA, receipt["selected"][0]["provenance"]["model_sha256"]
        )
        cached = scorer.score(
            generation="g1", query="authentication", candidates=self.candidates
        )
        self.assertTrue(cached["cache"]["hit"])
        self.assertEqual(0, cached["cache"]["refresh"]["embedded"])

    def test_provider_failure_falls_back_with_reason(self):
        scorer = SemanticScorer(
            provider=FailingProvider(),
            store=DerivedVectorStore(self.temporary.name),
            minimum_confidence=0,
        )
        receipt = scorer.score(
            generation="g1", query="cache", candidates=self.candidates
        )
        self.assertTrue(receipt["fallback"]["used"])
        self.assertEqual("DEVICE_UNAVAILABLE", receipt["fallback"]["reason_code"])
        self.assertEqual("b", receipt["selected"][0]["canonical_id"])

    def test_reranker_spi_is_auxiliary_and_invalid_output_falls_back(self):
        provider = RuntimeEmbeddingProvider(FakeBackend(), model())
        scorer = SemanticScorer(
            provider=provider,
            reranker=BoostReranker(),
            store=DerivedVectorStore(self.temporary.name),
            minimum_confidence=0,
        )
        receipt = scorer.score(
            generation="g1", query="login", candidates=self.candidates
        )
        by_id = {item["canonical_id"]: item for item in receipt["results"]}
        self.assertEqual(1.0, by_id["b"]["components"]["reranker"])
        scorer = SemanticScorer(
            provider=provider,
            reranker=BadReranker({"unknown": 1.0}),
            store=DerivedVectorStore(Path(self.temporary.name) / "other"),
            minimum_confidence=0,
        )
        receipt = scorer.score(
            generation="g1", query="login", candidates=self.candidates
        )
        self.assertEqual("RERANK_ID_UNKNOWN", receipt["fallback"]["reason_code"])
        self.assertTrue(
            all(item["components"]["reranker"] is None for item in receipt["results"])
        )

    def test_abstention_never_forces_uncovered_results(self):
        receipt = SemanticScorer().score(
            generation="g1", query="not-present", candidates=self.candidates
        )
        self.assertEqual([], receipt["selected"])
        self.assertEqual("NO_QUERY_COVERAGE", receipt["abstention"]["reason"])
        empty = SemanticScorer().score(generation="g1", query="anything", candidates=())
        self.assertEqual("NO_CANDIDATES", empty["abstention"]["reason"])

    def test_candidate_request_token_and_backpressure_budgets(self):
        scorer = SemanticScorer(
            budgets=SemanticBudgets(max_candidates=1, max_selected=1)
        )
        with self.assertRaises(SemanticScoringError) as caught:
            scorer.score(generation="g", query="x", candidates=self.candidates)
        self.assertEqual("CANDIDATE_BUDGET_EXCEEDED", caught.exception.reason_code)
        scorer = SemanticScorer(
            budgets=SemanticBudgets(
                max_candidates=3,
                max_selected=1,
                max_request_bytes=2,
                max_index_bytes=10,
                max_memory_bytes=20,
            )
        )
        with self.assertRaises(SemanticScoringError) as caught:
            scorer.score(generation="g", query="x", candidates=self.candidates)
        self.assertEqual("REQUEST_BYTES_BUDGET_EXCEEDED", caught.exception.reason_code)
        scorer = SemanticScorer(budgets=SemanticBudgets(max_queue_depth=1))
        scorer._pending = 1
        with self.assertRaises(SemanticScoringError) as caught:
            scorer.score(generation="g", query="x", candidates=())
        self.assertEqual("INFERENCE_BACKPRESSURE", caught.exception.reason_code)

    def test_cancel_is_observed_before_any_inference(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(SemanticScoringError) as caught:
            SemanticScorer().score(
                generation="g",
                query="x",
                candidates=self.candidates,
                cancel_event=cancelled,
            )
        self.assertEqual("INFERENCE_CANCELLED", caught.exception.reason_code)

    def test_capabilities_never_download_or_claim_unavailable_rust(self):
        offline = semantic_capabilities()
        self.assertFalse(offline["available"])
        self.assertFalse(offline["implicit_model_download"])
        self.assertFalse(offline["hard_dependency_litert"])
        provider = RuntimeEmbeddingProvider(FakeBackend(), model())
        runtime = semantic_capabilities(provider)
        self.assertEqual("runtime", runtime["mode"])
        self.assertEqual(
            "RUST_SEMANTIC_SURFACE_UNAVAILABLE", runtime["parity"]["reason"]
        )


class CliSeamTests(unittest.TestCase):
    def test_semantic_cli_offline_receipt(self):
        with TemporaryDirectory() as temporary:
            candidates = Path(temporary) / "candidates.json"
            candidates.write_text(
                json.dumps(
                    [
                        {"canonical_id": "a", "text": "login identity"},
                        {"canonical_id": "b", "text": "cache store"},
                    ]
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "simplicio_fast.cli",
                    "semantic-score",
                    "cache",
                    "--generation",
                    "g1",
                    "--candidates",
                    str(candidates),
                    "--no-model",
                ],
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        self.assertEqual(0, completed.returncode, completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual("b", receipt["selected"][0]["canonical_id"])
        self.assertEqual(
            "INFERENCE_BACKEND_UNAVAILABLE", receipt["fallback"]["reason_code"]
        )


if __name__ == "__main__":
    unittest.main()
