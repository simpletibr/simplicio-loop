from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.plugin_context_handle import (
    SCHEMA,
    SCHEMA_V2,
    build_plugin_context_handle,
    build_plugin_context_handle_v2,
    invalidate_plugin_context_handles,
    project_v1_handle_to_v2,
    validate_plugin_context_handle,
)


class PluginContextHandleV2Test(unittest.TestCase):
    def setUp(self) -> None:
        invalidate_plugin_context_handles()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_v1_default_is_unchanged(self) -> None:
        payload = build_plugin_context_handle(self.root, ref="main")
        self.assertEqual(payload["schema"], SCHEMA)
        self.assertTrue(validate_plugin_context_handle(payload)["valid"])

    def test_v2_contains_local_cache_provenance_and_generation(self) -> None:
        payload = build_plugin_context_handle_v2(
            self.root,
            ref="main",
            producer_commit="cefbd739b9ab86b7a842637b61da7bac96e48552",
            artifact_digest="sha256:" + "1" * 64,
        )
        self.assertEqual(payload["schema"], SCHEMA_V2)
        self.assertEqual(payload["producer"]["component"], "simplicio-mapper")
        self.assertEqual(payload["producer"]["commit"], "cefbd739b9ab86b7a842637b61da7bac96e48552")
        self.assertEqual(payload["local_map_cache"]["scope"], "local_mapper_artifact")
        self.assertEqual(payload["local_map_cache"]["layer"], "mapper_l1")
        self.assertIsNone(payload["provider_prompt_cache"])
        self.assertTrue(validate_plugin_context_handle(payload)["valid"])

    def test_v2_cache_hit_is_explicitly_mapper_local(self) -> None:
        first = build_plugin_context_handle_v2(self.root, ref="main")
        second = build_plugin_context_handle_v2(self.root, ref="main")
        self.assertEqual(first["context_id"], second["context_id"])
        self.assertEqual(first["local_map_cache"]["status"], "miss")
        self.assertEqual(second["local_map_cache"]["status"], "hit")
        self.assertEqual(second["local_map_cache"]["scope"], "local_mapper_artifact")
        self.assertIsNone(second["provider_prompt_cache"])

    def test_v2_cache_lifecycle_miss_write_hit_invalidation_and_corruption(self) -> None:
        first = build_plugin_context_handle_v2(self.root, ref="main")
        self.assertEqual(first["local_map_cache"]["status"], "miss")
        self.assertTrue(first["local_map_cache"]["receipt"]["produced"])
        second = build_plugin_context_handle_v2(self.root, ref="main")
        self.assertEqual(second["local_map_cache"]["status"], "hit")
        self.assertTrue(second["local_map_cache"]["receipt"]["reused"])
        self.assertTrue(second["local_map_cache"]["receipt"]["consumed"])
        self.assertEqual(second["local_map_cache"]["receipt"]["cache_scope"], "local_mapper")
        self.assertEqual(second["local_map_cache"]["receipt"]["provider_cache"], "unclaimed")

        (self.root / "src" / "app.py").write_text("def app():\n    return 2\n", encoding="utf-8")
        invalidated = build_plugin_context_handle_v2(self.root, ref="main")
        self.assertEqual(invalidated["local_map_cache"]["status"], "miss")
        self.assertEqual(invalidated["local_map_cache"]["lookup_receipt"]["reason"], "invalidated")
        self.assertTrue(invalidated["local_map_cache"]["receipt"]["produced"])
        self.assertNotEqual(invalidated["context_id"], first["context_id"])

        cache_path = self.root / ".simplicio" / "plugin-context-handle.json"
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        for entry in raw["structured"]["entries"].values():
            entry["checksum"] = "corrupt"
        cache_path.write_text(json.dumps(raw), encoding="utf-8")
        corrupted = build_plugin_context_handle_v2(self.root, ref="main")
        self.assertEqual(corrupted["local_map_cache"]["status"], "stale")
        self.assertEqual(corrupted["local_map_cache"]["receipt"]["outcome"], "corrupt")
        self.assertIsNone(corrupted["provider_prompt_cache"])

    def test_v2_partial_coverage_never_claims_complete(self) -> None:
        for index in range(4):
            (self.root / "src" / f"file-{index}.py").write_text("x = " + "1" * 100 + "\n", encoding="utf-8")
        payload = build_plugin_context_handle_v2(self.root, ref="main", token_budget=4)
        self.assertEqual(payload["coverage"]["status"], "partial")
        self.assertTrue(payload["coverage"]["truncated"])
        self.assertGreater(payload["coverage"]["omitted_count"], 0)
        self.assertTrue(validate_plugin_context_handle(payload)["valid"])

    def test_v2_dirty_and_untracked_semantics_are_explicit(self) -> None:
        payload = build_plugin_context_handle(
            self.root,
            ref="origin/main",
            dirty=True,
            schema_version=2,
            untracked_files=["scratch.txt"],
        )
        self.assertTrue(payload["generation"]["dirty_content_included"])
        self.assertEqual(payload["generation"]["untracked_files"], ["scratch.txt"])
        self.assertEqual(payload["local_map_cache"]["status"], "rebuilt")
        self.assertTrue(validate_plugin_context_handle(payload)["valid"])

    def test_unknown_major_and_provider_claim_fail_closed(self) -> None:
        unknown = {"schema": "simplicio.plugin.context-handle/v9"}
        self.assertEqual(validate_plugin_context_handle(unknown)["reason"], "unknown_schema_major")
        payload = build_plugin_context_handle_v2(self.root)
        payload["provider_prompt_cache"] = {"hit": True}
        self.assertEqual(validate_plugin_context_handle(payload)["reason"], "provider_cache_claim_forbidden")

    def test_v1_projection_is_conservative(self) -> None:
        legacy = build_plugin_context_handle(self.root, ref="main")
        projected = project_v1_handle_to_v2(legacy)
        self.assertEqual(projected["schema"], SCHEMA_V2)
        self.assertEqual(projected["local_map_cache"]["scope"], "local_mapper_artifact")
        self.assertIsNone(projected["provider_prompt_cache"])
        self.assertTrue(validate_plugin_context_handle(projected)["valid"])


if __name__ == "__main__":
    unittest.main()
