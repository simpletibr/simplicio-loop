"""The overlay re-runs the C#/Razor semantic pass only when C#/Razor changed (#1631).

Oracle: ``base + overlay`` equals a fresh full mapping (``build_artifacts``) of the worktree. The semantic
service is a fake command (``SIMPLICIO_MAPPER_SEMANTIC_COMMAND``) that logs every invocation, so the tests
count how many times the global semantic pass actually ran -- black-box, independent of internal names.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_central_overlay import NAMES, OverlayCase, _git, semantic  # noqa: E402

from simplicio_mapper.mapper.central_overlay import compute_overlay  # noqa: E402
from simplicio_mapper.mapper.emit import build_artifacts  # noqa: E402

FAKE_SERVICE = textwrap.dedent(
    """
    import json, os, sys
    request = json.load(sys.stdin)
    with open(os.environ["FAKE_SEM_LOG"], "a", encoding="utf-8") as log:
        log.write(request["language"] + "\\n")
    tag = sys.argv[1] if len(sys.argv) > 1 else "t"
    symbols = [s for s in request["symbols"] if s["defined_in"].endswith((".cs", ".razor"))]
    first = {}
    for s in symbols:
        first.setdefault(s["name"], s)
    out_symbols = [
        {"defined_in": s["defined_in"], "line": s["line"], "name": s["name"],
         "symbol_id": "Fake." + s["name"] + "#" + tag, "signature": s["name"] + "()"}
        for s in symbols
    ]
    resolutions = [
        {"source_file": c["source_file"], "line": c["line"], "name": c["name"],
         "target_symbol": "Fake." + c["name"] + "#" + tag}
        for c in request["call_sites"] if c["name"] in first
    ]
    json.dump({"schema": "simplicio.mapper-semantic-result/v1", "protocol": "v1", "provider": "fake",
               "provider_version": "syms=%d" % len(request["symbols"]),
               "symbols": out_symbols, "resolutions": resolutions}, sys.stdout)
    """
)
SVC = "public class Svc {\n  public int Run(int x) { return Helper(x); }\n  public int Helper(int x) { return x; }\n}\n"
VIEW = "@code {\n  void Click() { Svc.Run(1); }\n}\n"


class SemanticReuseCase(OverlayCase):
    def setUp(self) -> None:
        super().setUp()
        self.log = self.base / "sem.log"
        script = self.base / "fake_sem.py"
        script.write_text(FAKE_SERVICE, encoding="utf-8")
        for key, value in {
            "SIMPLICIO_MAPPER_SEMANTIC_COMMAND": f"{sys.executable} {script}",
            "FAKE_SEM_LOG": str(self.log),
        }.items():
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)
        self.script = script
        (self.main / "src").mkdir()
        (self.main / "src" / "Svc.cs").write_text(SVC, encoding="utf-8")
        (self.main / "src" / "View.razor").write_text(VIEW, encoding="utf-8")
        _git(["add", "-A"], self.main)
        _git(["commit", "-q", "-m", "csharp"], self.main)
        self.wt = self.worktree()
        # The first overlay builds the central base (which runs the semantic pass once per language).
        self.assertIsNotNone(compute_overlay(str(self.wt)).artifacts)

    def runs(self) -> int:
        return len(self.log.read_text(encoding="utf-8").split()) if self.log.exists() else 0

    def overlay_runs(self, wt: Path) -> tuple[dict, dict, int]:
        before = self.runs()
        outcome = compute_overlay(str(wt))
        self.assertIsNotNone(outcome.artifacts, outcome.receipt)
        return outcome.artifacts, outcome.receipt, self.runs() - before

    def assert_same_as_full(self, artifacts: dict, wt: Path) -> None:
        got, want = semantic(artifacts), semantic(build_artifacts(str(wt)))
        for name in NAMES:
            self.assertEqual(got[name], want[name], f"{name} differs from a fresh full mapping")


class UnchangedCSharpTests(SemanticReuseCase):
    def test_python_only_delta_reuses_the_base_semantic_artifacts(self) -> None:
        (self.wt / self.rels[0]).write_text("def plain_edit():\n    return 1\n", encoding="utf-8")
        artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertEqual(runs, 0, "the semantic service must not run when C#/Razor are untouched")
        self.assertEqual(receipt["semantic"], "reused_from_base")
        self.assert_same_as_full(artifacts, self.wt)

    def test_new_python_symbols_do_not_leak_into_the_semantic_request(self) -> None:
        """The fake reports ``len(request.symbols)``: only C#/Razor symbols may reach the service."""
        for i in range(5):
            (self.wt / f"extra_{i}.py").write_text(f"def extra_{i}():\n    return {i}\n", encoding="utf-8")
        artifacts, _receipt, runs = self.overlay_runs(self.wt)
        self.assertEqual(runs, 0)
        self.assert_same_as_full(artifacts, self.wt)

    def test_clean_worktree_reuses_and_matches(self) -> None:
        artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertEqual((runs, receipt["semantic"]), (0, "reused_from_base"))
        self.assert_same_as_full(artifacts, self.wt)


class ChangedCSharpTests(SemanticReuseCase):
    def check_recomputed(self) -> None:
        artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertGreater(runs, 0, "a C#/Razor change must re-run the semantic pass")
        self.assertTrue(receipt["semantic"].startswith("recomputed"), receipt["semantic"])
        self.assert_same_as_full(artifacts, self.wt)

    def test_modified_csharp(self) -> None:
        (self.wt / "src" / "Svc.cs").write_text(SVC.replace("Helper", "Other"), encoding="utf-8")
        self.check_recomputed()

    def test_modified_razor(self) -> None:
        (self.wt / "src" / "View.razor").write_text(VIEW.replace("Click", "Tap"), encoding="utf-8")
        self.check_recomputed()

    def test_added_csharp(self) -> None:
        (self.wt / "src" / "New.cs").write_text("public class New {\n  public void Go() { Svc.Run(2); }\n}\n", encoding="utf-8")
        self.check_recomputed()

    def test_removed_csharp(self) -> None:
        (self.wt / "src" / "Svc.cs").unlink()
        self.check_recomputed()

    def test_renamed_csharp_with_identical_content(self) -> None:
        _git(["mv", "src/Svc.cs", "src/Service.cs"], self.wt)
        self.check_recomputed()

    def test_same_size_csharp_edit(self) -> None:
        (self.wt / "src" / "Svc.cs").write_text(SVC.replace("Helper", "Hepler"), encoding="utf-8")
        self.check_recomputed()

    def test_removing_every_csharp_file_leaves_no_semantic_pass(self) -> None:
        (self.wt / "src" / "Svc.cs").unlink()
        (self.wt / "src" / "View.razor").unlink()
        artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertEqual((runs, receipt["semantic"]), (0, "not_required"))
        self.assert_same_as_full(artifacts, self.wt)

    def test_a_base_built_under_another_service_config_is_not_reused(self) -> None:
        os.environ["SIMPLICIO_MAPPER_SEMANTIC_COMMAND"] = f"{sys.executable} {self.script} other"
        (self.wt / self.rels[0]).write_text("def plain_edit():\n    return 1\n", encoding="utf-8")
        artifacts, receipt, runs = self.overlay_runs(self.wt)
        self.assertGreater(runs, 0)
        self.assertTrue(receipt["semantic"].startswith("recomputed"), receipt["semantic"])
        self.assert_same_as_full(artifacts, self.wt)

    def test_csharp_without_call_sites_still_matches(self) -> None:
        (self.wt / "src" / "Empty.cs").write_text("public class Empty { }\n", encoding="utf-8")
        artifacts, _receipt, _runs = self.overlay_runs(self.wt)
        self.assert_same_as_full(artifacts, self.wt)


class ReceiptTests(OverlayCase):
    def test_a_repo_without_csharp_is_not_required(self) -> None:
        wt = self.worktree()
        outcome = compute_overlay(str(wt))
        self.assertEqual(outcome.receipt["semantic"], "not_required")
        json.dumps(outcome.receipt)  # the receipt stays serialisable


if __name__ == "__main__":
    unittest.main()
