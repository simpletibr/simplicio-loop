from __future__ import annotations

import tempfile
import unittest
import contextlib
import hashlib
import io
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

from simplicio_fast.cli import main
from simplicio_fast.delivery import DeliveryEngine, _deduplicate_spans
from simplicio_fast.engine import select_engine
from simplicio_fast.snapshot import build_snapshot
from simplicio_fast.snapshot import ContextSpan, Snapshot


class DeliveryEngineTest(unittest.TestCase):
    def test_prepare_emits_receipt_and_second_attempt_hits_l0_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def create_user(name):\n    return name\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            engine = DeliveryEngine(root, snapshot)
            selection = select_engine("python").receipt()
            first = engine.prepare(
                "understand create_user and validate tests",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=selection,
            )
            second = engine.prepare(
                "understand create_user and validate tests",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=selection,
            )
            self.assertEqual("simplicio.fast.delivery-engine/v1", first["schema"])
            self.assertEqual("miss", first["cache"]["L0_attempt"])
            self.assertEqual("hit", second["cache"]["L0_attempt"])
            self.assertFalse(first["ownership"]["mutation_applied"])

    def test_prepare_treats_corrupt_or_mismatched_cache_receipts_as_misses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def create_user(name):\n    return name\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            cache = root / "cache"
            build_snapshot(root, snapshot)
            engine = DeliveryEngine(root, snapshot, cache)
            selection = select_engine("python").receipt()
            first = engine.prepare(
                "understand create_user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=selection,
            )
            cache_path = cache / f"{first['cache']['key']}.json"
            cache_path.write_text("{broken", encoding="utf-8")
            rebuilt = engine.prepare(
                "understand create_user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=selection,
            )
            assert rebuilt["cache"]["L0_attempt"] == "miss"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema": "simplicio.fast.delivery-engine/v1",
                        "status": "ready",
                        "cache": {"key": "sha256:wrong"},
                    }
                ),
                encoding="utf-8",
            )
            rebuilt_again = engine.prepare(
                "understand create_user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=selection,
            )
            assert rebuilt_again["cache"]["L0_attempt"] == "miss"

    def test_prepare_rejects_semantically_tampered_cache_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def create_user(name):\n    return name\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            cache = root / "cache"
            build_snapshot(root, snapshot)
            engine = DeliveryEngine(root, snapshot, cache)
            selection = select_engine("python").receipt()
            first = engine.prepare(
                "understand create_user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=selection,
            )
            cache_path = cache / f"{first['cache']['key']}.json"
            tampered = json.loads(cache_path.read_text(encoding="utf-8"))
            tampered["context"]["terms"] = ["forged"]
            cache_path.write_text(json.dumps(tampered), encoding="utf-8")
            rebuilt = engine.prepare(
                "understand create_user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=selection,
            )
            assert rebuilt["cache"]["L0_attempt"] == "miss"

    def test_prepare_uses_exact_tokenizer_and_binds_tokenizer_to_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def create_user(name):\n    return name\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            engine = DeliveryEngine(root, snapshot)
            selection = select_engine("python").receipt()
            exact = engine.prepare(
                "understand create_user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=selection,
                tokenizer_id="test-exact-v1",
                tokenizer=lambda text: len(text.encode("utf-8")),
            )
            changed_config = engine.prepare(
                "understand create_user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=selection,
                tokenizer_id="test-exact-v2",
                tokenizer=lambda text: len(text.encode("utf-8")),
            )
            changed_scoring = engine.prepare(
                "understand create_user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=selection,
                tokenizer_id="test-exact-v1",
                tokenizer=lambda text: len(text.encode("utf-8")),
                scoring_config="semantic-ranking-v2",
            )
            self.assertEqual("exact", exact["context"]["tokenizer"]["mode"])
            self.assertEqual("test-exact-v1", exact["context"]["tokenizer"]["id"])
            self.assertEqual(
                "simplicio.fast.context-request/v2",
                exact["context_request"]["schema"],
            )
            self.assertEqual(
                "test-exact-v1", exact["context_request"]["tokenizer_id"]
            )
            self.assertEqual(["python"], exact["context_request"]["languages"])
            self.assertEqual(
                ["calls", "imports", "references", "tests"],
                exact["context_request"]["requested_relations"],
            )
            self.assertEqual("miss", changed_config["cache"]["L0_attempt"])
            self.assertEqual("semantic-ranking-v2", changed_scoring["context"]["scoring_config"])
            self.assertEqual("miss", changed_scoring["cache"]["L0_attempt"])
            self.assertGreater(exact["context"]["tokens"], 0)
            self.assertGreater(exact["context"]["wrapper_tokens"], 0)
            self.assertEqual(
                exact["context"]["tokens"] + exact["context"]["wrapper_tokens"],
                exact["context"]["total_tokens"],
            )
            self.assertEqual(
                8_000 - exact["context"]["wrapper_tokens"],
                exact["context_request"]["budgets"]["max_selected_tokens"],
            )

    def test_prepare_requires_identity_for_exact_tokenizer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def create_user(name):\n    return name\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            with self.assertRaisesRegex(ValueError, "tokenizer_id"):
                DeliveryEngine(root, snapshot).prepare(
                    "understand create_user",
                    profile="loop-standalone",
                    mode="bootstrap",
                    engine_receipt=select_engine("python").receipt(),
                    tokenizer=lambda text: len(text),
                )

    def test_prepare_resolves_provider_tokenizer_and_separates_fallback_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def create_user(name):\n    return name\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            cache = root / "cache"
            build_snapshot(root, snapshot)
            engine = DeliveryEngine(root, snapshot, cache)
            selection = select_engine("python").receipt()
            def exact_tokenizer(text: str) -> int:
                return 123
            with patch(
                "simplicio_fast.delivery.resolve_tokenizer",
                return_value=exact_tokenizer,
            ) as resolver:
                exact = engine.prepare(
                    "understand create_user",
                    profile="loop-standalone",
                    mode="bootstrap",
                    engine_receipt=selection,
                    tokenizer_id="tiktoken:test-exact-v1",
                )
            resolver.assert_called_once_with("tiktoken:test-exact-v1")
            self.assertEqual("exact", exact["context"]["tokenizer"]["mode"])
            self.assertEqual(123, exact["context"]["tokens"])
            with patch(
                "simplicio_fast.delivery.resolve_tokenizer", return_value=None
            ):
                fallback = engine.prepare(
                    "understand create_user",
                    profile="loop-standalone",
                    mode="bootstrap",
                    engine_receipt=selection,
                    tokenizer_id="tiktoken:test-exact-v1",
                )
            self.assertEqual("estimated", fallback["context"]["tokenizer"]["mode"])
            self.assertEqual(
                "provider_tokenizer_unavailable",
                fallback["context"]["tokenizer"]["reason"],
            )
            self.assertEqual("miss", fallback["cache"]["L0_attempt"])

    def test_prepare_rejects_boolean_token_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def create_user(name):\n    return name\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            with self.assertRaisesRegex(ValueError, "non-negative integer"):
                DeliveryEngine(root, snapshot).prepare(
                    "understand create_user",
                    profile="loop-standalone",
                    mode="bootstrap",
                    engine_receipt=select_engine("python").receipt(),
                    tokenizer_id="test-bool-v1",
                    tokenizer=lambda text: True,
                )

    def test_legacy_regex_selection_is_explicit_and_receipted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def create_user(name):\n    return name\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            receipt = DeliveryEngine(root, snapshot).prepare(
                "understand create_user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=select_engine("python").receipt(),
                selection_mode="legacy-regex",
            )
            self.assertEqual("legacy-regex", receipt["context"]["selection_mode"])
            self.assertEqual(
                "legacy_regex_explicit",
                receipt["context"]["selection"]["fallback"]["reason_code"],
            )

    def test_semantic_selection_rejects_low_confidence_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(8):
                (root / f"module_{index}.py").write_text(
                    f"def user_note_{index}():\n    return 'user'\n",
                    encoding="utf-8",
                )
            (root / "target.py").write_text(
                "def authenticate_user(credentials):\n    return credentials\n",
                encoding="utf-8",
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            receipt = DeliveryEngine(root, snapshot).prepare(
                "authenticate user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=select_engine("python").receipt(),
                tokenizer_id="test-exact-v1",
                tokenizer=lambda text: len(text.split()),
            )
            legacy = DeliveryEngine(root, snapshot).prepare(
                "authenticate user",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=select_engine("python").receipt(),
                selection_mode="legacy-regex",
                tokenizer_id="test-exact-v1",
                tokenizer=lambda text: len(text.split()),
            )
            self.assertEqual(
                ["target.py"],
                [item["file"] for item in receipt["context"]["selected"]],
            )
            self.assertEqual(32, legacy["context"]["tokens"])
            self.assertEqual(4, receipt["context"]["tokens"])
            self.assertLessEqual(
                receipt["context"]["tokens"],
                legacy["context"]["tokens"] * 0.5,
            )
            self.assertGreater(
                len(receipt["context"]["rejected_quality_handles"]),
                0,
            )

    def test_context_many_reuses_one_source_read_across_terms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text(
                "def create_user(name):\n    return name\n\n"
                "def validate_user(name):\n    return bool(name)\n",
                encoding="utf-8",
            )
            snapshot_path = root / "project.sfast"
            build_snapshot(root, snapshot_path)
            original_read_bytes = Path.read_bytes
            reads: list[Path] = []

            def counted_read_bytes(path: Path) -> bytes:
                if path.resolve() == source.resolve():
                    reads.append(path)
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", counted_read_bytes):
                with Snapshot(snapshot_path) as snapshot:
                    spans = snapshot.context_many(
                        root, ("create_user", "validate_user"), max_results=8
                    )
            self.assertEqual(2, len(spans))
            self.assertEqual(1, len(reads))

    def test_overlapping_contained_spans_are_counted_once(self) -> None:
        outer = ContextSpan(
            "service",
            "function",
            "service.py",
            1,
            4,
            "a" * 64,
            "one\ntwo\nthree\nfour",
            "symbol:outer",
        )
        inner = ContextSpan(
            "service.inner",
            "function",
            "service.py",
            2,
            3,
            "a" * 64,
            "two\nthree",
            "symbol:inner",
        )
        selected, rejected = _deduplicate_spans([outer, inner])
        self.assertEqual([outer], selected)
        self.assertEqual(["symbol:inner"], rejected)

    def test_cache_stats_reports_disposable_cache_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def ping():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            engine = DeliveryEngine(root, snapshot)
            self.assertEqual(
                {
                    "schema": "simplicio.fast.delivery-cache/v1",
                    "entries": 0,
                    "bytes": 0,
                },
                engine.cache_stats(),
            )
            engine.prepare(
                "validate ping",
                profile="loop-standalone",
                mode="bootstrap",
                engine_receipt=select_engine("python").receipt(),
            )
            stats = engine.cache_stats()
            self.assertEqual("simplicio.fast.delivery-cache/v1", stats["schema"])
            self.assertEqual(1, stats["entries"])
            self.assertGreater(stats["bytes"], 0)

    def test_full_profile_records_runtime_authority_without_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def ping():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            receipt = DeliveryEngine(root, snapshot).prepare(
                "validate ping",
                profile="full",
                mode="bootstrap",
                engine_receipt=select_engine("python").receipt(),
            )
            self.assertEqual(
                "simplicio-runtime", receipt["ownership"]["full_effect_authority"]
            )
            self.assertFalse(receipt["ownership"]["mutation_applied"])

    def test_cli_delivery_is_a_system_receipt_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def ping():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            output = io.StringIO()
            argv = [
                "simplicio-fast",
                "delivery",
                "validate ping",
                "--root",
                str(root),
                "--snapshot",
                str(snapshot),
                "--fast-engine",
                "python",
                "--mapper-mode",
                "bootstrap",
            ]
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
                main()
            self.assertEqual(
                "simplicio.fast.delivery-engine/v1",
                json.loads(output.getvalue())["schema"],
            )

    def test_loop_delivery_dry_run_write_and_idempotent_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text("def ping():\n    return True\n", encoding="utf-8")
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            changeset = {
                "schema": "simplicio.fast.changeset/v2",
                "changes": [
                    {
                        "path": "service.py",
                        "expected_sha256": expected,
                        "replacements": [
                            {
                                "start_line": 2,
                                "end_line": 2,
                                "content": "    return False",
                            }
                        ],
                    }
                ],
            }
            selection = select_engine("python").receipt()
            engine = DeliveryEngine(root, snapshot)
            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset", return_value=None
            ):
                dry_run = engine.deliver(
                    changeset, profile="loop-standalone", engine_receipt=selection
                )
                self.assertEqual("dry_run", dry_run["status"])
                self.assertTrue(dry_run["apply"]["no_write_proof"])
                self.assertIn("return True", source.read_text(encoding="utf-8"))
                applied = engine.deliver(
                    changeset,
                    profile="loop-standalone",
                    engine_receipt=selection,
                    write=True,
                )
            self.assertEqual("applied", applied["status"])
            self.assertTrue(applied["ownership"]["mutation_applied"])
            self.assertEqual(
                "    return False", source.read_text(encoding="utf-8").splitlines()[1]
            )
            retry = engine.deliver(
                changeset,
                profile="loop-standalone",
                engine_receipt=selection,
                write=True,
            )
            self.assertEqual("hit", retry["cache"]["L0_delivery"])
            self.assertTrue(retry["idempotency"]["replayed"])

    def test_cli_delivery_changeset_uses_guarded_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text("def ping():\n    return True\n", encoding="utf-8")
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            changeset = root / "changeset.json"
            changeset.write_text(
                json.dumps(
                    {
                        "schema": "simplicio.fast.changeset/v2",
                        "changes": [
                            {
                                "path": "service.py",
                                "expected_sha256": expected,
                                "replacements": [
                                    {
                                        "start_line": 2,
                                        "end_line": 2,
                                        "content": "    return False",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            argv = [
                "simplicio-fast",
                "delivery",
                "apply ping",
                "--root",
                str(root),
                "--snapshot",
                str(snapshot),
                "--changeset",
                str(changeset),
                "--write",
                "--fast-engine",
                "python",
            ]
            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset", return_value=None
            ):
                with (
                    patch.dict(os.environ, {"SIMPLICIO_FAST_ALLOW_WRITE": "1"}),
                    patch.object(sys, "argv", argv),
                    contextlib.redirect_stdout(output),
                ):
                    main()
            payload = json.loads(output.getvalue())
            self.assertEqual("applied", payload["status"])
            self.assertEqual("simplicio.fast.delivery-engine/v1", payload["schema"])

    def test_full_write_fails_closed_without_runtime_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text("def ping():\n    return True\n", encoding="utf-8")
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            changeset = {
                "schema": "simplicio.fast.changeset/v2",
                "changes": [
                    {
                        "path": "service.py",
                        "expected_sha256": expected,
                        "replacements": [
                            {
                                "start_line": 2,
                                "end_line": 2,
                                "content": "    return False",
                            }
                        ],
                    }
                ],
            }
            receipt = DeliveryEngine(root, snapshot).deliver(
                changeset,
                profile="full",
                engine_receipt=select_engine("python").receipt(),
                write=True,
            )
            self.assertEqual("blocked", receipt["status"])
            self.assertIn("runtime_authorization_required", receipt["reason_codes"])
            self.assertIn("return True", source.read_text(encoding="utf-8"))

    def test_full_write_delegates_to_coordinator_authorized_runtime_transaction(
        self,
    ) -> None:
        try:
            from simplicio.plan_compiler.authority import (
                EffectAuthorization,
                build_change_proposal,
            )
            from simplicio.plan_compiler.effect_sink import EffectDispatchContext
            from simplicio.plan_compiler.models import (
                EffectPlan,
                PlanDAG,
                PlanNode,
                VerificationPlan,
            )
            from simplicio.plan_compiler.runtime_effect_sink import (
                OfflineRuntimeTransport,
                RuntimeEffectSink,
            )
        except ModuleNotFoundError:
            self.skipTest("simplicio-runtime is not installed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text("def ping():\n    return True\n", encoding="utf-8")
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            original = source.read_bytes()
            expected = hashlib.sha256(original).hexdigest()
            normalized_source_hash = hashlib.sha256(
                "def ping():\n    return True\n".encode("utf-8")
            ).hexdigest()
            range_text = "    return True\n"
            artifact = {
                "schema": "simplicio.mechanical-edit/v1",
                "touched_files": ["service.py"],
                "operations": [
                    {
                        "op": "replace_range",
                        "path": "service.py",
                        "start_line": 2,
                        "end_line": 2,
                        "text": "    return False\n",
                        "file_sha256": normalized_source_hash,
                        "range_sha256": hashlib.sha256(
                            range_text.encode("utf-8")
                        ).hexdigest(),
                    }
                ],
            }
            artifact_path = root / "effect.json"
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
            node = PlanNode(
                node_id="node-1",
                capability="file.write",
                read_set=["service.py"],
                write_set=["service.py"],
                risk="high",
                acceptance_criteria_refs=["ac-1"],
                requires_gate=True,
                rollback_strategy="restore_source",
            )
            plan = PlanDAG(
                plan_id="plan-1",
                goal_id="goal-1",
                context_snapshot_id="snapshot-1",
                revision="1",
                nodes=[node],
                consumer_id="simplicio-runtime",
                context_handle="ctx-1",
            )
            effect = EffectPlan(
                effect_id="effect-1",
                plan_node_id="node-1",
                kind="write",
                authority_required="file.write",
                idempotency_key="effect-idempotency-1",
                preconditions=["source_hash_matches"],
                artifact_ref="effect.json",
                context_handle="ctx-1",
            )
            verification = VerificationPlan(
                verification_id="verify-1",
                plan_node_id="node-1",
                verifier="pytest",
                command_or_capability="python -m pytest",
                timeout_s=30,
                acceptance_criteria_refs=["ac-1"],
            )
            context = EffectDispatchContext(
                plan_id="plan-1",
                goal_id="goal-1",
                plan_node=node,
                verifications=[verification],
                coordinator_kind="simplicio-loop",
                coordinator_id="coordinator-1",
                session_id="session-1",
                turn_id="turn-1",
                policy_revision="policy-1",
                base_hash="base-1",
                source_hash=expected,
                context_handle="ctx-1",
                lease_id="lease-1",
                fencing_token="fence-1",
                plan=plan,
            )
            proposal = build_change_proposal(effect, context)
            authorization = EffectAuthorization.issue(
                proposal,
                authority="simplicio-runtime",
                issuer="simplicio-loop",
                human_gate_receipt="gate-1",
                now=time.time(),
                ttl_s=60.0,
            )
            context = EffectDispatchContext(
                **{**context.__dict__, "authorization": authorization}
            )
            transaction = RuntimeEffectSink(
                OfflineRuntimeTransport(root=root), root=root
            )._transaction(effect, context)
            changeset = {
                "schema": "simplicio.fast.changeset/v2",
                "changes": [
                    {
                        "path": "service.py",
                        "expected_sha256": expected,
                        "replacements": [
                            {
                                "start_line": 2,
                                "end_line": 2,
                                "content": "    return False",
                            }
                        ],
                    }
                ],
            }
            engine = DeliveryEngine(root, snapshot)
            with patch.dict(
                os.environ,
                {
                    "SIMPLICIO_RUNTIME_OFFLINE": "1",
                    "SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT": "1",
                },
                clear=False,
            ):
                receipt = engine.deliver(
                    changeset,
                    profile="full",
                    engine_receipt=select_engine("python").receipt(),
                    write=True,
                    runtime_transaction=transaction,
                )
            self.assertEqual("applied", receipt["status"])
            self.assertEqual("completed", receipt["runtime"]["state"])
            self.assertTrue(receipt["ownership"]["mutation_applied"])
            self.assertIn("return False", source.read_text(encoding="utf-8"))

    def test_full_write_ignores_legacy_boolean_authority_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text("def ping():\n    return True\n", encoding="utf-8")
            snapshot = root / "project.sfast"
            build_snapshot(root, snapshot)
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            changeset = {
                "schema": "simplicio.fast.changeset/v2",
                "changes": [
                    {
                        "path": "service.py",
                        "expected_sha256": expected,
                        "replacements": [],
                    }
                ],
            }
            receipt = DeliveryEngine(root, snapshot).deliver(
                changeset,
                profile="full",
                engine_receipt=select_engine("python").receipt(),
                write=True,
                runtime_authorized=True,
            )
            self.assertEqual("blocked", receipt["status"])
            self.assertIn("runtime_authorization_required", receipt["reason_codes"])
