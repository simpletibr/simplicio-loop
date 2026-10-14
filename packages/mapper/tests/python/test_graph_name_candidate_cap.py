"""The per-call-site cap on name-lookup candidates (#1631): configurable, counted in the artifact, deterministic."""

from __future__ import annotations

import gc
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.mapper.emit import build_artifacts

ENV = "SIMPLICIO_MAPPER_CALL_NAME_CANDIDATE_LIMIT"


def _repo(root: Path, definitions: int) -> None:
    for i in range(definitions):
        (root / f"m{i:02d}.py").write_text(f"class K{i}:\n    def run(self):\n        return {i}\n", encoding="utf-8")
    (root / "use.py").write_text("def go(x):\n    return x.run()\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=a@b.c", "commit", "-qm", "i"], cwd=root, check=True)


class NameCandidateCapTests(unittest.TestCase):
    def graph(self, definitions: int, limit: str | None = None) -> dict:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _repo(root, definitions)
        if limit is not None:
            os.environ[ENV] = limit
            self.addCleanup(os.environ.pop, ENV, None)
        try:
            return build_artifacts(str(root))["call_graph"]
        finally:
            gc.collect()

    def targets(self, graph: dict) -> list[str]:
        return [e["target_file"] for e in graph["edges"] if e["source_file"] == "use.py"]

    def test_default_cap_leaves_a_small_name_untouched(self) -> None:
        graph = self.graph(32)
        self.assertEqual(len(self.targets(graph)), 32)
        self.assertEqual(graph["coverage"]["name_candidate_limit"], 32)
        self.assertEqual((graph["coverage"]["name_capped_call_sites"], graph["coverage"]["name_edges_discarded"]), (0, 0))

    def test_default_cap_counts_what_it_drops_in_the_artifact(self) -> None:
        graph = self.graph(40)
        self.assertEqual(len(self.targets(graph)), 32)
        coverage = graph["coverage"]
        self.assertEqual((coverage["name_capped_call_sites"], coverage["name_edges_discarded"]), (1, 8))
        self.assertEqual(coverage["status"], "degraded")
        edge = next(e for e in graph["edges"] if e["source_file"] == "use.py")
        self.assertEqual(edge["provenance"]["candidate_count"], 40, "the count reports what the name matched, not what was kept")

    def test_cap_is_configurable_and_keeps_the_first_in_a_fixed_order(self) -> None:
        graph = self.graph(40, limit="5")
        self.assertEqual(sorted(self.targets(graph)), [f"m{i:02d}.py" for i in range(5)])
        self.assertEqual(graph["coverage"]["name_edges_discarded"], 35)
        self.assertEqual(graph["coverage"]["name_candidate_limit"], 5)

    def test_invalid_limit_falls_back_to_the_default(self) -> None:
        self.assertEqual(self.graph(3, limit="nope")["coverage"]["name_candidate_limit"], 32)

    def test_a_huge_limit_reproduces_the_uncapped_graph(self) -> None:
        graph = self.graph(40, limit="1000000")
        self.assertEqual(len(self.targets(graph)), 40)
        self.assertEqual(graph["coverage"]["name_edges_discarded"], 0)


if __name__ == "__main__":
    unittest.main()
