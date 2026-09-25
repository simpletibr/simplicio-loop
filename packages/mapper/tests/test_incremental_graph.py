from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.incremental_graph import IncrementalGraphIndex


class IncrementalGraphTests(unittest.TestCase):
    def test_only_changed_files_are_parsed_and_removed_files_disappear(self) -> None:
        index = IncrementalGraphIndex("repo", "g1")
        first = index.update({"a.py": "def a():\n    pass\n", "b.py": "def b():\n    pass\n"})
        self.assertEqual(first.parsed_paths, ("a.py", "b.py"))
        second = index.update({"a.py": "def a_changed():\n    pass\n"}, generation_id="g2")
        self.assertEqual(second.changed_paths, ("a.py",))
        self.assertEqual(second.removed_paths, ("b.py",))
        self.assertEqual(second.reused_paths, ())
        self.assertTrue(all(node.generation_id == "g2" for node in index.graph.nodes))
        self.assertFalse(any(node.path == "b.py" for node in index.graph.nodes))

    def test_snapshot_is_atomic_and_integrity_checked(self) -> None:
        index = IncrementalGraphIndex("repo", "g1")
        index.update({"a.py": "def a():\n    pass\n"})
        with tempfile.TemporaryDirectory() as directory:
            path = index.snapshot(Path(directory) / "graph.snapshot")
            restored = IncrementalGraphIndex.restore(path)
            self.assertEqual(restored.graph.digest(), index.graph.digest())
            path.write_text(path.read_text().replace("00", "ff", 1), encoding="ascii")
            with self.assertRaises(ValueError):
                IncrementalGraphIndex.restore(path)

    def test_coverage_manifest_is_generation_bound(self) -> None:
        index = IncrementalGraphIndex("repo", "g1")
        index.update({"a.py": "def a():\n    pass\n"})
        manifest = index.coverage_manifest()
        self.assertEqual(manifest["schema"], "simplicio.mapper-coverage/v1")
        self.assertEqual(manifest["generation_id"], "g1")
        self.assertEqual(manifest["file_count"], 1)


if __name__ == "__main__":
    unittest.main()
