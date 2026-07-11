import tempfile
import unittest
from pathlib import Path
from shutil import copytree

from simplicio_mapper.incremental import compute_delta, initial_snapshot, run_incremental_scan


class IncrementalDeltaTests(unittest.TestCase):
    def test_operations_are_sorted_and_rename_is_remove_add(self):
        old = {"schema": "simplicio.graph-snapshot/v1", "version": 1, "revision": "r000001", "snapshot_id": "old", "entities": [
            {"id": "file:old.py", "kind": "file", "path": "old.py", "name": "old.py"},
            {"id": "file:keep.py", "kind": "file", "path": "keep.py", "name": "keep.py"},
            {"id": "file:other.py", "kind": "file", "path": "other.py", "name": "other.py"},
        ], "edges": [{"id": "edge:1", "type": "calls", "source": "keep.py::caller", "target": "keep.py", "path": "keep.py"}]}
        new = {"schema": "simplicio.graph-snapshot/v1", "version": 1, "revision": "r000002", "snapshot_id": "new", "entities": [
            {"id": "file:new.py", "kind": "file", "path": "new.py", "name": "new.py"},
            {"id": "file:keep.py", "kind": "file", "path": "keep.py", "name": "keep.py", "content_hash": "changed"},
            {"id": "symbol:keep.py:keep", "kind": "symbol", "path": "keep.py", "name": "keep"},
            {"id": "symbol:keep.py:keep.py::caller", "kind": "symbol", "path": "keep.py", "name": "caller", "qualified_name": "keep.py::caller"},
            {"id": "file:other.py", "kind": "file", "path": "other.py", "name": "other.py"},
        ], "edges": [{"id": "edge:1", "type": "calls", "source": "other.py", "target": "keep.py", "path": "keep.py"}]}
        delta = compute_delta(old, new, changed_paths=["keep.py"])
        self.assertEqual([event["op"] for event in delta["events"]], sorted(event["op"] for event in delta["events"]))
        self.assertEqual(delta["events"][0]["order"], 1)
        self.assertTrue(any(event["id"] == "file:old.py" and event["op"] == "remove" for event in delta["events"]))
        self.assertTrue(any(event["id"] == "file:new.py" and event["op"] == "add" for event in delta["events"]))
        self.assertTrue(any(event["op"] == "invalidate" for event in delta["events"]))

    def test_real_scan_persists_initial_then_delta_and_full_rescan(self):
        source = Path("contracts/mapper-artifacts/v1/fixtures/python-minimal/source").resolve()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            copytree(source, root)
            first = run_incremental_scan(str(root))
            self.assertEqual(first["event_type"], "initial_snapshot")
            (root / "src" / "app.py").write_text((root / "src" / "app.py").read_text() + "\n# changed\n", encoding="utf-8")
            second = run_incremental_scan(str(root), changed_paths=["src/app.py"])
            self.assertEqual(second["event_type"], "delta")
            self.assertEqual(second["base_revision"], "r000001")
            self.assertTrue(any(event["op"] == "update" for event in second["events"]))
            reset = run_incremental_scan(str(root), full_rescan=True)
            self.assertTrue(reset["full_rescan"])
            self.assertEqual(reset["mode"], "full-rescan")

    def test_snapshot_ids_are_stable_for_unchanged_source(self):
        source = Path("contracts/mapper-artifacts/v1/fixtures/python-minimal/source").resolve()
        first = initial_snapshot(str(source))
        second = initial_snapshot(str(source))
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual([item["id"] for item in first["entities"]], [item["id"] for item in second["entities"]])

    def test_incompatible_base_requests_resynchronization(self):
        source = Path("contracts/mapper-artifacts/v1/fixtures/python-minimal/source").resolve()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            copytree(source, root)
            (root / ".simplicio").mkdir(exist_ok=True)
            (root / ".simplicio" / "graph-snapshot.json").write_text('{"schema":"old/v0","revision":"r9"}', encoding="utf-8")
            result = run_incremental_scan(str(root))
            self.assertEqual(result["event_type"], "resync_required")
            self.assertTrue(result["fallback"]["required"])


if __name__ == "__main__":
    unittest.main()
