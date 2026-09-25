from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.plugin_context_handle import (
    SCHEMA,
    build_plugin_context_handle,
    fetch_plugin_context_handle,
    invalidate_plugin_context_handles,
)

REPO = Path(__file__).resolve().parents[2]


class PluginContextHandleTest(unittest.TestCase):
    def setUp(self) -> None:
        invalidate_plugin_context_handles()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")
        (self.root / "src" / "util.py").write_text("def util():\n    return 2\n", encoding="utf-8")
        self.intent = {"goal": "fix app", "fingerprint": "task-app"}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_identical_task_ref_is_cache_hit(self) -> None:
        first = build_plugin_context_handle(self.root, task_intent=self.intent, ref="main")
        second = build_plugin_context_handle(self.root, task_intent=self.intent, ref="main")
        self.assertEqual(first["schema"], SCHEMA)
        self.assertFalse(first["cache"]["hit"])
        self.assertTrue(second["cache"]["hit"])
        self.assertEqual(first["handle"], second["handle"])

    def test_one_file_change_selectively_invalidates(self) -> None:
        first = build_plugin_context_handle(self.root, task_intent=self.intent, ref="main")
        (self.root / "src" / "app.py").write_text("def app():\n    return 99\n", encoding="utf-8")
        second = build_plugin_context_handle(self.root, task_intent=self.intent, ref="main")
        self.assertFalse(second["cache"]["hit"])
        self.assertNotEqual(first["handle"], second["handle"])
        self.assertNotEqual(first["digest"], second["digest"])

    def test_dirty_overlay_isolated_from_origin_ref(self) -> None:
        clean = build_plugin_context_handle(self.root, task_intent=self.intent, ref="origin/main", dirty=False)
        dirty = build_plugin_context_handle(self.root, task_intent=self.intent, ref="origin/main", dirty=True)
        self.assertNotEqual(clean["handle"], dirty["handle"])
        self.assertTrue(dirty["dirty"])
        self.assertFalse(clean["dirty"])

    def test_token_budget_bounds_serialized_payload(self) -> None:
        payload = build_plugin_context_handle(
            self.root, task_intent=self.intent, ref="main", token_budget=4
        )
        self.assertLessEqual(payload["serialized_tokens"], 8)
        self.assertGreaterEqual(len(payload["spans"]), 1)

    def test_stale_or_tampered_handle_rejected(self) -> None:
        built = build_plugin_context_handle(self.root, task_intent=self.intent, ref="main")
        unknown = fetch_plugin_context_handle("not-a-real-handle")
        self.assertEqual(unknown["status"], "rejected")
        tampered = fetch_plugin_context_handle(built["handle"], expected_digest="0" * 64)
        self.assertEqual(tampered["status"], "rejected")
        self.assertEqual(tampered["reason"], "tampered_or_stale")
        ok = fetch_plugin_context_handle(built["handle"], expected_digest=built["digest"])
        self.assertEqual(ok["handle"], built["handle"])

    def test_schema_and_offline_fixture(self) -> None:
        schema = json.loads((REPO / "contracts/plugin-context-handle/v1/schema.json").read_text(encoding="utf-8"))
        fixture = json.loads((REPO / "fixtures/plugin-context-handle/sample-handle.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["title"], "PluginContextHandle")
        self.assertEqual(fixture["schema"], SCHEMA)


if __name__ == "__main__":
    unittest.main()
