"""Guards on reusing the base's C#/Razor semantic resolution in the overlay (post-merge audit of #1639).

Reuse is wrong whenever re-running the service would answer differently: a project/SDK file the service
reads changed, the service itself changed, or the base recorded a failed run.
"""

from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_central_overlay_semantic_reuse as reuse  # noqa: E402
from simplicio_mapper.mapper.graph import semantic_input_key  # noqa: E402

FAILING = "import os, sys\nif os.environ.get('FAKE_SEM_FAIL'):\n    sys.exit(3)\n"


class ProjectFileChangeTests(reuse.SemanticReuseCase):
    def check_recomputed(self, rel: str, reason: str) -> None:
        target = self.wt / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("<Project><PropertyGroup><LangVersion>12</LangVersion></PropertyGroup></Project>\n", encoding="utf-8")
        artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertEqual(receipt["semantic"], reason)
        self.assertGreater(runs, 0, "the service reads the project, so it must run again")
        self.assert_same_as_full(artifacts, self.wt)

    def test_new_csproj(self) -> None:
        self.check_recomputed("src/App.csproj", "recomputed:semantic_context_changed")

    def test_new_directory_build_props(self) -> None:
        self.check_recomputed("Directory.Build.props", "recomputed:semantic_context_changed")

    def test_new_global_json(self) -> None:
        self.check_recomputed("global.json", "recomputed:semantic_context_changed")

    def test_unrelated_xml_does_not_force_a_recompute(self) -> None:
        (self.wt / "notes.xml").write_text("<a/>\n", encoding="utf-8")
        _artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertEqual((runs, receipt["semantic"]), (0, "reused_from_base"))

    def test_service_file_touched(self) -> None:
        os.utime(self.script, (1, 1))
        _artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertEqual(receipt["semantic"], "recomputed:semantic_input_changed")
        self.assertGreater(runs, 0)


class KeyTests(reuse.SemanticReuseCase):
    def test_timeout_change_recomputes(self) -> None:
        os.environ["SIMPLICIO_MAPPER_SEMANTIC_TIMEOUT_S"] = "77"
        self.addCleanup(os.environ.pop, "SIMPLICIO_MAPPER_SEMANTIC_TIMEOUT_S", None)
        _artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertEqual(receipt["semantic"], "recomputed:semantic_input_changed")
        self.assertGreater(runs, 0)

    def test_base_without_input_key_is_recomputed(self) -> None:
        for path in Path(self.cache).rglob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(document, dict) and isinstance(document.get("semantic_resolution"), dict):
                document["semantic_resolution"].pop("input_key", None)
                path.write_text(json.dumps(document), encoding="utf-8")
        artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertEqual(receipt["semantic"], "recomputed:base_without_input_key")
        self.assertGreater(runs, 0)
        self.assert_same_as_full(artifacts, self.wt)

    def test_file_without_hash_has_no_provable_key(self) -> None:
        unhashed = SimpleNamespace(path="a.cs", language="csharp", file_hash="")
        self.assertIsNone(semantic_input_key([unhashed]))


class CrossFileSymbolTests(reuse.SemanticReuseCase):
    """A service whose answer for one file depends on the others: untouched C#/Razor files are re-resolved too."""

    def setUp(self) -> None:
        coupled = reuse.FAKE_SERVICE.replace('s["name"] + "()"', 's["name"] + "(%d)" % len(symbols)')
        self.assertNotEqual(coupled, reuse.FAKE_SERVICE)
        patcher = mock.patch.object(reuse, "FAKE_SERVICE", coupled)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def test_editing_one_file_refreshes_the_symbols_of_the_untouched_ones(self) -> None:
        (self.wt / "src" / "Svc.cs").write_text(reuse.SVC.replace("Helper", "Other"), encoding="utf-8")
        artifacts, receipt, _runs = self.overlay_runs(self.wt)
        self.assertTrue(receipt["semantic"].startswith("recomputed"))
        self.assert_same_as_full(artifacts, self.wt)


class FailedBaseRunTests(reuse.SemanticReuseCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(reuse, "FAKE_SERVICE", FAILING + reuse.FAKE_SERVICE)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ["FAKE_SEM_FAIL"] = "1"  # the base is built while the service is failing
        try:
            super().setUp()
        finally:
            os.environ.pop("FAKE_SEM_FAIL", None)

    def test_failed_base_run_is_not_served_to_a_healthy_service(self) -> None:
        (self.wt / self.rels[0]).write_text("def plain_edit():\n    return 1\n", encoding="utf-8")
        artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertEqual(receipt["semantic"], "recomputed:base_semantic_unavailable")
        self.assertGreater(runs, 0)
        self.assertEqual(artifacts["symbol_index"]["semantic_resolution"]["status"], "available")
        self.assert_same_as_full(artifacts, self.wt)


if __name__ == "__main__":
    unittest.main()
