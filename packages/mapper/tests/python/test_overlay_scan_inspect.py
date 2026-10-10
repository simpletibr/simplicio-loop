"""`scan` and `inspect` on a worktree that holds an overlay over the central base (#1673).

The overlay serves project-map, symbol-index and precedent-index. `scan` must refresh it and answer
fresh without starting a full index; `inspect` must call it valid and name what it does not serve.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from simplicio_mapper.cli import main  # noqa: E402
from test_central_overlay import _git, make_repo  # noqa: E402

HEAVY = ("call-graph.json", "architecture-inventory.json", "retrieval-index.json", "artifact-manifest.json")


def _run(*argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(list(argv))
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


class OverlayScanInspectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.main_repo = base / "main"
        self.rels = make_repo(self.main_repo)
        os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = str(base / "cache")
        self.addCleanup(os.environ.pop, "SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
        self.wt = base / "wt"
        _git(["worktree", "add", "-q", "-b", "b-wt", str(self.wt), "main"], self.main_repo)
        code, _ = _run("canonical", "overlay", str(self.wt), "--json")
        self.assertEqual(code, 0)
        self.state = self.wt / ".simplicio-loop"

    def _full_index_counter(self):
        spawn = mock.patch(
            "simplicio_mapper.cli._status_engine._spawn_index_process", side_effect=AssertionError("full index")
        )
        background = mock.patch(
            "simplicio_mapper.cli._status_engine._spawn_background_index", side_effect=AssertionError("full index")
        )
        return spawn, background

    def test_scan_on_a_valid_overlay_runs_no_full_index_and_answers_fresh(self) -> None:
        (self.wt / self.rels[0]).write_text("def edited():\n    return 1\n", encoding="utf-8")
        spawn, background = self._full_index_counter()
        with spawn as spawned, background as backgrounded:
            code, envelope = _run("scan", str(self.wt), "--sync", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(spawned.call_count + backgrounded.call_count, 0)
        self.assertEqual(envelope["phase"], "complete")
        self.assertEqual(envelope["deep"]["skipped_reason"], "served_by_overlay")
        self.assertEqual(envelope["artifact_service"]["mode"], "overlay")
        self.assertTrue((self.state / "overlay.json").exists(), "scan keeps the overlay")
        for name in HEAVY:
            self.assertFalse((self.state / name).exists(), name)
        state = json.loads((self.state / "overlay.json").read_text(encoding="utf-8"))
        self.assertIn(self.rels[0], state["delta"]["modified"], "scan refreshed the overlay")

    def test_inspect_calls_the_overlay_valid_and_names_what_it_does_not_serve(self) -> None:
        code, payload = _run("inspect", str(self.wt), "--json")
        self.assertEqual(code, 0)
        status = payload["status"]
        self.assertTrue(status["artifacts_present"])
        self.assertTrue(status["fresh"])
        service = status["artifact_service"]
        self.assertEqual(service["mode"], "overlay")
        self.assertEqual(service["served_by_overlay"], ["project_map", "symbol_index", "precedent_index"])
        self.assertEqual(
            service["not_served_by_overlay"], ["call_graph", "architecture_inventory", "retrieval_index"]
        )
        artifacts = payload["evidence"]["artifacts"]
        for name in ("project_map", "symbol_index", "precedent_index"):
            self.assertEqual(artifacts[name]["state"], "served_by_overlay")
        for name in ("call_graph", "architecture_inventory", "retrieval_index"):
            self.assertEqual(artifacts[name]["state"], "not_served_by_overlay")

    def test_inspect_text_form_is_fresh(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            main(["inspect", str(self.wt)])
        self.assertIn("fresh=True", out.getvalue())

    def test_inspect_is_not_fresh_after_an_edit_until_scan_refreshes_the_overlay(self) -> None:
        (self.wt / self.rels[0]).write_text("def edited():\n    return 1\n", encoding="utf-8")
        _, before = _run("inspect", str(self.wt), "--json")
        self.assertFalse(before["status"]["fresh"])
        spawn, background = self._full_index_counter()
        with spawn, background:
            _run("scan", str(self.wt), "--sync", "--json")
        _, after = _run("inspect", str(self.wt), "--json")
        self.assertTrue(after["status"]["fresh"])

    def test_handoff_does_not_build_the_unserved_artifacts(self) -> None:
        spawn, background = self._full_index_counter()
        with spawn as spawned, background as backgrounded:
            code, _payload = _run("handoff", str(self.wt), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(spawned.call_count + backgrounded.call_count, 0)
        for name in HEAVY:
            self.assertFalse((self.state / name).exists(), name)

    def test_ask_declares_the_cost_of_the_artifacts_it_builds(self) -> None:
        code, answer = _run("ask", str(self.wt), "callers", "func_0_a", "--json")
        self.assertEqual(code, 0)
        cost = answer["on_demand_cost"]
        self.assertEqual(cost["verb"], "callers")
        self.assertIn("call_graph", cost["built"])
        self.assertFalse(cost["persisted"])
        self.assertGreaterEqual(cost["seconds"], 0)
        self.assertTrue((self.state / "overlay.json").exists(), "ask leaves the overlay alone")

    def test_a_missing_base_makes_the_overlay_invalid_for_inspect(self) -> None:
        state = json.loads((self.state / "overlay.json").read_text(encoding="utf-8"))
        state["base_digest"] = "0" * 64
        (self.state / "overlay.json").write_text(json.dumps(state), encoding="utf-8")
        _, payload = _run("inspect", str(self.wt), "--json")
        self.assertFalse(payload["status"]["artifacts_present"])
        self.assertFalse(payload["status"]["fresh"])


if __name__ == "__main__":
    unittest.main()
