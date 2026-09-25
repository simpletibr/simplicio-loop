"""RED/GREEN tests for issue #1288: rare-term files were ranked below files
that only matched a generic, high-frequency term.

Root cause: ``ProjectProcessor._structural_score`` weighted every matched
query term equally, so a common term (e.g. "apply", matched by many
symbols/files across the snapshot) scored the same per-match as a rare term
(e.g. "economy", matched by a single file). The fix applies inverse document
frequency (IDF) weighting, computed once per query from the snapshot's own
symbol table via ``Snapshot.search``, plus a path/stem match signal.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simplicio_fast.processor import ProjectProcessor


class IdfRankingTest(unittest.TestCase):
    def _build(self, root: Path) -> ProjectProcessor:
        # One file whose path/name only matches the RARE term ("economy").
        (root / "economy_profile.py").write_text(
            "def recommend_prism_slots(config):\n"
            "    return config\n"
        )
        # Many files/symbols matching the COMMON term ("apply"), none of
        # which mention "economy" anywhere in path, name or signature.
        (root / "version_sync.py").write_text(
            "def _apply_pyproject(data):\n"
            "    return data\n"
            "\n"
            "def _apply_lockfile(data):\n"
            "    return data\n"
        )
        (root / "install_executor.py").write_text(
            "def apply(step):\n"
            "    return step\n"
            "\n"
            "def apply_all(steps):\n"
            "    return steps\n"
        )
        (root / "test_apply_behavior.py").write_text(
            "def test_apply_behavior():\n"
            "    assert apply_all([]) == []\n"
            "\n"
            "def test_apply_behavior_again():\n"
            "    assert apply_all([]) == []\n"
        )
        processor = ProjectProcessor(root, root / ".simplicio/fast/project.sfast")
        processor.ingest()
        return processor

    def test_rare_term_file_outranks_files_matching_only_a_common_term(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processor = self._build(root)

            understanding = processor.understand(
                "economy apply persistence on linux", max_results=12
            )

            self.assertIn("economy_profile.py", understanding.files)
            selected_files = [item.file for item in understanding.context]
            self.assertIn("economy_profile.py", selected_files)

            explanations = understanding.selection.get("candidate_explanations", {})
            economy_scores = [
                detail["structural_score"]
                for detail in explanations.values()
                if detail["file"] == "economy_profile.py"
            ]
            apply_only_scores = [
                detail["structural_score"]
                for detail in explanations.values()
                if detail["file"] != "economy_profile.py"
                and detail["matched_terms"] == ["apply"]
            ]
            self.assertTrue(economy_scores)
            self.assertTrue(apply_only_scores)
            self.assertGreater(min(economy_scores), max(apply_only_scores))

            # The rare-term file must rank ahead of every apply-only file.
            economy_rank = selected_files.index("economy_profile.py")
            for other_file in selected_files:
                if other_file == "economy_profile.py":
                    continue
                other_matches = {
                    detail["file"]
                    for detail in explanations.values()
                    if detail["matched_terms"] == ["apply"]
                }
                if other_file in other_matches:
                    self.assertLess(economy_rank, selected_files.index(other_file))

    def test_single_term_query_ranking_is_unchanged(self) -> None:
        # Regression guard: with exactly one query term, IDF weighting must
        # degenerate to the pre-fix behavior (perfect coverage whenever the
        # term matches at all), so relative ordering by name/kind bonuses is
        # preserved.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "users.py").write_text(
                "class UserService:\n"
                "    def apply(self):\n"
                "        return True\n"
            )
            processor = ProjectProcessor(root, root / ".simplicio/fast/project.sfast")
            processor.ingest()

            understanding = processor.understand("apply", max_results=5)
            explanations = understanding.selection.get("candidate_explanations", {})
            self.assertTrue(explanations)
            for detail in explanations.values():
                self.assertEqual(["apply"], detail["matched_terms"])


if __name__ == "__main__":
    unittest.main()
