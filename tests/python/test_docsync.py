"""Unit tests for simplicio_mapper.docsync (F5 diff-driven docs sync).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.docsync import DOCS_SYNC_SCHEMA, build_docs_sync  # noqa: E402
from simplicio_mapper.mapper import write_architecture_docs  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class DocsSyncGitRepoTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "sync-app"}))
        _write(self.dir, "moduleA/a.py", "def a():\n    return 1\n")
        _write(self.dir, "moduleB/b.py", "def b():\n    return 2\n")
        _write(self.dir, "docs/architecture-map.md", "See moduleA/a.py for details.\n")
        _git(self.dir, "init", "-q")
        _git(self.dir, "config", "user.email", "test@example.com")
        _git(self.dir, "config", "user.name", "Test")
        _git(self.dir, "add", "-A")
        _git(self.dir, "commit", "-q", "-m", "initial")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_changes_is_a_noop(self) -> None:
        payload = build_docs_sync(str(self.dir))
        self.assertEqual(payload["schema"], DOCS_SYNC_SCHEMA)
        self.assertEqual(payload["changed_files"], [])
        self.assertEqual(payload["affected_flows"], [])
        self.assertEqual(payload["regenerated_docs"], [])
        self.assertFalse(payload["stale"])

    def test_editing_one_module_only_regenerates_that_module_doc(self) -> None:
        # Baseline: write module docs for both modules once (full docs pass).
        write_architecture_docs(str(self.dir))
        module_b_doc = self.dir / ".simplicio" / "docs" / "modules" / "moduleb.md"
        module_a_doc = self.dir / ".simplicio" / "docs" / "modules" / "modulea.md"
        self.assertTrue(module_a_doc.exists())
        self.assertTrue(module_b_doc.exists())
        before_b = module_b_doc.read_text(encoding="utf-8")
        before_b_mtime = module_b_doc.stat().st_mtime_ns

        _write(self.dir, "moduleA/a.py", "def a():\n    return 999\n")

        payload = build_docs_sync(str(self.dir))
        self.assertIn("moduleA/a.py", payload["changed_files"])
        self.assertTrue(any(doc.endswith("modules/modulea.md") for doc in payload["regenerated_docs"]))
        self.assertFalse(any(doc.endswith("modules/moduleb.md") for doc in payload["regenerated_docs"]))
        self.assertEqual(module_b_doc.read_text(encoding="utf-8"), before_b)
        self.assertEqual(module_b_doc.stat().st_mtime_ns, before_b_mtime)

    def test_manual_doc_referencing_changed_file_is_flagged_not_edited(self) -> None:
        doc_path = self.dir / "docs" / "architecture-map.md"
        before = doc_path.read_text(encoding="utf-8")

        _write(self.dir, "moduleA/a.py", "def a():\n    return 2\n")
        payload = build_docs_sync(str(self.dir))

        self.assertTrue(any(item["doc"] == "docs/architecture-map.md" for item in payload["needs_review"]))
        self.assertEqual(doc_path.read_text(encoding="utf-8"), before)

    def test_check_mode_reports_stale_without_writing(self) -> None:
        write_architecture_docs(str(self.dir))
        architecture_doc = self.dir / ".simplicio" / "docs" / "architecture.md"
        before = architecture_doc.read_text(encoding="utf-8")

        _write(self.dir, "moduleA/c.py", "def c():\n    return 3\n")
        payload = build_docs_sync(str(self.dir), check=True)

        self.assertTrue(payload["stale"])
        self.assertEqual(architecture_doc.read_text(encoding="utf-8"), before)

    def test_check_mode_clean_after_sync(self) -> None:
        _write(self.dir, "moduleA/c.py", "def c():\n    return 3\n")
        build_docs_sync(str(self.dir))
        payload = build_docs_sync(str(self.dir), check=True)
        self.assertFalse(payload["stale"])

    def test_global_diagram_svgs_regenerate_alongside_architecture_docs(self) -> None:
        _write(self.dir, "moduleA/c.py", "def c():\n    return 3\n")
        payload = build_docs_sync(str(self.dir))
        self.assertTrue(any(doc.endswith("diagrams/architecture-modules.svg") for doc in payload["regenerated_docs"]))
        svg_path = self.dir / ".simplicio" / "docs" / "diagrams" / "architecture-modules.svg"
        self.assertTrue(svg_path.exists())


class DocsSyncFlowDiagramTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "sync-flow-app", "main": "src/main.py"}))
        _write(self.dir, "src/main.py", "from src.writer import persist\ndef main():\n    persist()\n")
        _write(self.dir, "src/writer.py", "def persist():\n    with open('out.json', 'w') as handle:\n        handle.write('{}')\n")
        _git(self.dir, "init", "-q")
        _git(self.dir, "config", "user.email", "test@example.com")
        _git(self.dir, "config", "user.name", "Test")
        _git(self.dir, "add", "-A")
        _git(self.dir, "commit", "-q", "-m", "initial")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_flow_diagram_svgs_regenerate_when_flow_is_touched(self) -> None:
        _write(self.dir, "src/main.py", "from src.writer import persist\ndef main():\n    persist()\n    persist()\n")
        payload = build_docs_sync(str(self.dir))
        self.assertTrue(payload["affected_flows"])
        self.assertTrue(any("diagrams/flows/" in doc for doc in payload["regenerated_docs"]))
        diagrams_dir = self.dir / ".simplicio" / "docs" / "diagrams" / "flows"
        self.assertTrue(diagrams_dir.exists())
        self.assertTrue(list(diagrams_dir.glob("*.svg")))


class DocsSyncNoGitTest(unittest.TestCase):
    def test_falls_back_to_cache_diff_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write(base, "package.json", json.dumps({"name": "no-git-app"}))
            _write(base, "src/main.py", "def main():\n    return 1\n")
            payload = build_docs_sync(str(base))
            self.assertEqual(payload["diff"]["source"], "cache")


if __name__ == "__main__":
    unittest.main()
