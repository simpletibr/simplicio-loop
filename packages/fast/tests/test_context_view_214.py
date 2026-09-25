from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from simplicio_fast.context_view import (
    CACHE_SCHEMA,
    ContextAuthority,
    ContextBudget,
    ContextIdentity,
    ContextItem,
    ContextViewCache,
    ContextViewError,
    ContextViewRequest,
    ContextViewService,
    decode_hbp,
    encode_hbp,
    verify_context_view,
    verify_context_view_hbp,
)


class ContextViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = ContextAuthority(
            "loop-stage-agent",
            "fence-1",
            ("context:read", "review:evidence"),
            ("src", "tests", "receipts"),
        )
        self.budget = ContextBudget(max_tokens=100, max_bytes=2_000, max_nodes=8)

    def identity(
        self,
        *,
        task: str = "task-1",
        attempt: int = 1,
        agent: str = "agent-1",
        stage: str = "implementer",
    ) -> ContextIdentity:
        return ContextIdentity("prism-1", "slot-1", task, attempt, agent, stage)

    def request(
        self,
        *,
        identity: ContextIdentity | None = None,
        authority: ContextAuthority | None = None,
        overlay: str | None = None,
        budget: ContextBudget | None = None,
        capability: str = "context:read",
        ttl: int = 300,
    ) -> ContextViewRequest:
        authority = authority or self.authority
        return ContextViewRequest(
            repository="owner/repo",
            identity=identity or self.identity(),
            base_generation="base-g1",
            overlay_digest=overlay,
            requested_capability=capability,
            goal_fragment="repair context view",
            budget=budget or self.budget,
            authority_digest=authority.digest,
            fence=authority.fence,
            ttl_seconds=ttl,
        )

    def item(
        self,
        handle: str,
        content: str,
        *,
        kind: str = "fact",
        tokens: int = 4,
        path: str = "src/service.py",
        overlay: str | None = None,
        visibility: str = "shared",
        relevance: float = 1.0,
    ) -> ContextItem:
        return ContextItem.create(
            kind=kind,
            handle=handle,
            content=content,
            base_generation="base-g1",
            token_count=tokens,
            path=path,
            overlay_digest=overlay,
            visibility=visibility,
            relevance=relevance,
            provenance=("mapper:pack-1",),
        )

    def assert_reason(self, reason: str, operation) -> None:
        with self.assertRaises(ContextViewError) as caught:
            operation()
        self.assertEqual(reason, caught.exception.reason_code)

    def test_materializes_complete_lineage_and_content_address(self) -> None:
        request = self.request()
        view = ContextViewService().materialize(
            request,
            self.authority,
            [
                self.item("fact-1", "ContextView is bounded."),
                self.item(
                    "test-1",
                    "test_context_view passed",
                    kind="test",
                    path="tests/test_context_view.py",
                ),
            ],
        )

        verified = verify_context_view(view, request=request, authority=self.authority)

        self.assertTrue(view.handle.startswith("CTX-"))
        self.assertEqual("base-g1", verified["provenance"]["base_generation"])
        self.assertEqual("task-1", verified["provenance"]["task_id"])
        self.assertEqual("agent-1", verified["provenance"]["agent_id"])
        self.assertEqual(2, view.usage["nodes"])
        self.assertEqual(1.0, view.quality["coverage"])
        self.assertIsNone(view.abstention)

    def test_request_and_result_hbp_round_trip_detect_tamper(self) -> None:
        request = self.request()
        decoded_request = ContextViewRequest.from_hbp(request.to_hbp())
        self.assertEqual(request, decoded_request)
        view = ContextViewService().materialize(
            request, self.authority, [self.item("fact", "bounded")]
        )
        verified = verify_context_view_hbp(
            view.to_hbp(), request=request, authority=self.authority
        )
        self.assertEqual(view.handle, verified["handle"])

        row = view.to_hbp()
        replacement = "A" if row[-1] != "A" else "B"
        self.assert_reason(
            "hbp_tampered",
            lambda: decode_hbp(row[:-1] + replacement, expected_kind="result"),
        )
        self.assert_reason(
            "hbp_schema_invalid",
            lambda: decode_hbp(request.to_hbp(), expected_kind="result"),
        )
        with self.assertRaises(ValueError):
            encode_hbp("other", {})

    def test_authority_capability_and_fence_fail_closed(self) -> None:
        request = self.request()
        other = ContextAuthority("intruder", "fence-1", ("context:read",), ("src",))
        self.assert_reason(
            "authority_mismatch",
            lambda: ContextViewService().materialize(
                request, other, [self.item("fact", "x")]
            ),
        )
        stale_request = replace(request, fence="fence-old")
        self.assert_reason(
            "fence_stale",
            lambda: ContextViewService().materialize(
                stale_request, self.authority, [self.item("fact", "x")]
            ),
        )
        denied = self.request(capability="admin:write")
        self.assert_reason(
            "capability_denied",
            lambda: ContextViewService().materialize(
                denied, self.authority, [self.item("fact", "x")]
            ),
        )

    def test_takeover_rotates_authority_and_view_identity(self) -> None:
        old_request = self.request()
        old_view = ContextViewService().materialize(
            old_request, self.authority, [self.item("fact", "x")]
        )
        takeover = ContextAuthority(
            "review-takeover",
            "fence-2",
            ("context:read", "review:evidence"),
            ("src", "tests", "receipts"),
        )
        takeover_request = self.request(
            identity=self.identity(attempt=2, agent="agent-2"),
            authority=takeover,
        )
        new_view = ContextViewService().materialize(
            takeover_request, takeover, [self.item("fact", "x")]
        )
        self.assertNotEqual(old_view.handle, new_view.handle)
        self.assert_reason(
            "view_request_hash_mismatch",
            lambda: verify_context_view(
                old_view, request=takeover_request, authority=takeover
            ),
        )

    def test_base_selection_reuses_cache_between_tasks_but_views_stay_bound(
        self,
    ) -> None:
        cache = ContextViewCache()
        service = ContextViewService(cache)
        first = service.materialize(
            self.request(identity=self.identity(task="task-a")),
            self.authority,
            [self.item("fact", "shared base")],
        )
        second = service.materialize(
            self.request(identity=self.identity(task="task-b")),
            self.authority,
            [self.item("fact", "shared base")],
        )
        self.assertEqual("miss", first.cache["outcome"])
        self.assertEqual("hit", second.cache["outcome"])
        self.assertEqual(first.cache_key, second.cache_key)
        self.assertNotEqual(first.handle, second.handle)
        self.assertEqual(second.usage["tokens"], second.cache["tokens_reused_observed"])
        self.assertIsNone(second.cache["token_savings"])

    def test_overlay_selection_never_reuses_across_tasks(self) -> None:
        overlay = hashlib.sha256(b"overlay-a").hexdigest()
        service = ContextViewService()
        item = self.item("overlay", "task-local", overlay=overlay)
        first = service.materialize(
            self.request(identity=self.identity(task="task-a"), overlay=overlay),
            self.authority,
            [item],
        )
        second = service.materialize(
            self.request(identity=self.identity(task="task-b"), overlay=overlay),
            self.authority,
            [item],
        )
        self.assertEqual("miss", first.cache["outcome"])
        self.assertEqual("miss", second.cache["outcome"])
        self.assertNotEqual(first.cache_key, second.cache_key)

    def test_overlay_and_generation_mismatch_block_before_cache(self) -> None:
        overlay_a = hashlib.sha256(b"a").hexdigest()
        overlay_b = hashlib.sha256(b"b").hexdigest()
        self.assert_reason(
            "overlay_scope_mismatch",
            lambda: ContextViewService().materialize(
                self.request(overlay=overlay_a),
                self.authority,
                [self.item("overlay", "x", overlay=overlay_b)],
            ),
        )
        stale = replace(self.item("stale", "x"), base_generation="base-old")
        self.assert_reason(
            "stale_generation",
            lambda: ContextViewService().materialize(
                self.request(), self.authority, [stale]
            ),
        )

    def test_reviewer_gets_evidence_not_implementer_prompt(self) -> None:
        reviewer = self.identity(stage="reviewer", agent="reviewer-1")
        request = self.request(identity=reviewer, capability="review:evidence")
        view = ContextViewService().materialize(
            request,
            self.authority,
            [
                self.item(
                    "private-prompt",
                    "Implement it by changing X",
                    kind="implementer_prompt",
                    visibility="implementer",
                ),
                self.item("diff", "@@ -1 +1 @@", kind="diff"),
                self.item(
                    "test",
                    "all passed",
                    kind="test",
                    path="tests/test_service.py",
                ),
            ],
        )
        kinds = {item["kind"] for item in view.selected}
        self.assertEqual({"diff", "test"}, kinds)
        self.assertGreaterEqual(view.quality["evidence_nodes"], 2)
        self.assertIsNone(view.abstention)

    def test_reviewer_abstains_without_independent_evidence(self) -> None:
        request = self.request(
            identity=self.identity(stage="reviewer"),
            capability="review:evidence",
        )
        view = ContextViewService().materialize(
            request, self.authority, [self.item("fact", "claim only")]
        )
        self.assertEqual("reviewer_evidence_missing", view.abstention["reason_code"])
        self.assertEqual("abstained", view.quality["fidelity"])

    def test_empty_or_overflowing_selection_abstains_with_bounded_usage(self) -> None:
        tiny = ContextBudget(max_tokens=1, max_bytes=1, max_nodes=1)
        view = ContextViewService().materialize(
            self.request(budget=tiny),
            self.authority,
            [self.item("large", "too large", tokens=3)],
        )
        self.assertEqual(0, view.usage["nodes"])
        self.assertEqual(0, view.usage["bytes"])
        self.assertEqual("insufficient_evidence", view.abstention["reason_code"])
        self.assertEqual(1, view.quality["budget_rejections"])

        empty = ContextViewService().materialize(
            self.request(identity=self.identity(task="empty")),
            self.authority,
            [],
        )
        self.assertEqual("insufficient_evidence", empty.abstention["reason_code"])

    def test_priority_and_budget_are_deterministic_and_auditable(self) -> None:
        budget = ContextBudget(max_tokens=4, max_bytes=100, max_nodes=1)
        items = [
            self.item("span", "code", kind="span", tokens=4),
            self.item("test", "pass", kind="test", tokens=4, path="tests/test_x.py"),
        ]
        first = ContextViewService().materialize(
            self.request(budget=budget), self.authority, items
        )
        second = ContextViewService().materialize(
            self.request(budget=budget), self.authority, reversed(items)
        )
        self.assertEqual("test", first.selected[0]["kind"])
        self.assertEqual(first.selected, second.selected)
        self.assertEqual("bounded", first.quality["fidelity"])
        self.assertLessEqual(first.usage["tokens"], budget.max_tokens)
        self.assertLessEqual(first.usage["bytes"], budget.max_bytes)
        self.assertLessEqual(first.usage["nodes"], budget.max_nodes)

    def test_secret_redaction_and_root_policy(self) -> None:
        view = ContextViewService().materialize(
            self.request(),
            self.authority,
            [
                self.item(
                    "secret",
                    "api_key = abcdef123456; Authorization: Bearer abcdefghijk",
                )
            ],
        )
        payload = view.selected[0]["content"]
        self.assertNotIn("abcdef123456", payload)
        self.assertNotIn("abcdefghijk", payload)
        self.assertIn("<redacted>", payload)
        self.assertEqual(1, view.usage["redactions"])

        denied = self.item("docs", "x", path="docs/private.md")
        self.assert_reason(
            "path_denied",
            lambda: ContextViewService().materialize(
                self.request(identity=self.identity(task="denied")),
                self.authority,
                [denied],
            ),
        )
        self.assert_reason(
            "path_escape",
            lambda: self.item("escape", "x", path="../secret.txt"),
        )

    def test_item_content_tamper_blocks_even_if_cache_would_hit(self) -> None:
        valid = self.item("fact", "trusted")
        request = self.request()
        service = ContextViewService()
        service.materialize(request, self.authority, [valid])
        tampered = replace(valid, content="altered")
        self.assert_reason(
            "item_tampered",
            lambda: service.materialize(request, self.authority, [tampered]),
        )

    def test_conflicting_mapper_handles_fail_closed(self) -> None:
        first = self.item("same-handle", "first")
        second = self.item("same-handle", "second")
        self.assert_reason(
            "item_handle_collision",
            lambda: ContextViewService().materialize(
                self.request(), self.authority, [first, second]
            ),
        )
        deduplicated = ContextViewService().materialize(
            self.request(identity=self.identity(task="deduplicated")),
            self.authority,
            [first, first],
        )
        self.assertEqual(1, deduplicated.usage["nodes"])

    def test_result_tamper_and_lineage_mismatch_block(self) -> None:
        request = self.request()
        view = ContextViewService().materialize(
            request, self.authority, [self.item("fact", "trusted")]
        )
        tampered = view.record()
        tampered["selected"][0]["content"] = "forged"
        self.assert_reason(
            "view_tampered",
            lambda: verify_context_view(
                tampered, request=request, authority=self.authority
            ),
        )
        other_request = self.request(identity=self.identity(task="other"))
        self.assert_reason(
            "view_request_hash_mismatch",
            lambda: verify_context_view(
                view, request=other_request, authority=self.authority
            ),
        )

    def test_cache_reopens_expires_evicts_and_detects_file_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "context-cache.json"
            now = [10.0]

            def clock() -> float:
                return now[0]

            cache = ContextViewCache(path, max_entries=1, clock=clock)
            service = ContextViewService(cache)
            request = self.request(ttl=2)
            service.materialize(request, self.authority, [self.item("first", "first")])
            reopened = ContextViewService(
                ContextViewCache(path, max_entries=1, clock=clock)
            )
            warm = reopened.materialize(
                request, self.authority, [self.item("first", "first")]
            )
            self.assertEqual("hit", warm.cache["outcome"])

            second_request = replace(request, goal_fragment="other goal")
            reopened.materialize(
                second_request, self.authority, [self.item("second", "second")]
            )
            self.assertEqual(1, reopened.cache.metrics["evicted"])
            miss = reopened.materialize(
                request, self.authority, [self.item("first", "first")]
            )
            self.assertEqual("miss", miss.cache["outcome"])

            now[0] = 20.0
            expired = reopened.materialize(
                request, self.authority, [self.item("first", "first")]
            )
            self.assertEqual("miss", expired.cache["outcome"])
            self.assertEqual(1, reopened.cache.metrics["expired"])

            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(CACHE_SCHEMA, value["schema"])
            entry = next(iter(value["entries"].values()))
            entry["payload"]["usage"]["bytes"] += 1
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assert_reason(
                "cache_tampered",
                lambda: ContextViewCache(path, max_entries=1, clock=clock),
            )

    def test_invalid_contract_values_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            ContextBudget(0, 1, 1)
        with self.assertRaises(ValueError):
            self.identity(attempt=0)
        with self.assertRaises(ValueError):
            ContextAuthority("", "f", ("context:read",))
        with self.assertRaises(ValueError):
            ContextAuthority("p", "f", ())
        with self.assertRaises(ValueError):
            ContextViewCache(max_entries=0)
        with self.assertRaises(ValueError):
            replace(self.request(), ttl_seconds=0)
        with self.assertRaises(ValueError):
            replace(self.request(), schema="unsupported")
        with self.assertRaises(TypeError):
            ContextViewService().materialize("not-a-request", self.authority, [])
        with self.assertRaises(TypeError):
            ContextViewService().materialize(self.request(), "not-authority", [])
        with self.assertRaises(TypeError):
            ContextViewService().materialize(self.request(), self.authority, [object()])


if __name__ == "__main__":
    unittest.main()
