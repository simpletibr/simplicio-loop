import hashlib
import tempfile
import unittest
from pathlib import Path

from simplicio_fast.navigation import NavigationError, NavigationIndex, navigate
from simplicio_fast.snapshot import Snapshot, build_snapshot


class NavigationContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "service.py").write_text(
            "def target():\n    return True\n\n"
            "def caller():\n    return target()\n\n"
            "def test_target():\n    return target()\n",
            encoding="utf-8",
        )
        self.snapshot_path = self.root / "project.sfast"
        build_snapshot(self.root, self.snapshot_path)
        self.snapshot = Snapshot(self.snapshot_path)
        self.index = NavigationIndex(self.snapshot)

    def tearDown(self) -> None:
        self.snapshot.close()
        self.directory.cleanup()

    def test_definition_callers_and_callees_use_snapshot_ids(self) -> None:
        target = self.snapshot.find_exact("target")[0]
        caller = self.snapshot.find_exact("caller")[0]
        definition = self.index.navigate(
            target.symbol_id,
            "definition",
            "outgoing",
            10,
            generation=self.index.generation,
        )
        self.assertEqual("simplicio.fast-navigation/v1", definition.schema)
        self.assertEqual(
            "simplicio.fast.provenance/v1", definition.provenance["schema"]
        )
        self.assertEqual((target.symbol_id,), definition.ids)
        self.assertEqual(self.index.generation, definition.generation)
        self.assertEqual(target.symbol_id, definition.items[0].id)

        callers = navigate(
            self.snapshot, target.symbol_id, "callers", "incoming", {"max_nodes": 10}
        )
        self.assertIn(caller.symbol_id, callers.ids)
        callees = self.index.navigate(
            caller.symbol_id, "callees", "outgoing", {"max_nodes": 10}
        )
        self.assertEqual((target.symbol_id,), callees.ids)
        self.assertEqual(0.8, callees.items[0].confidence)
        self.assertEqual(caller.symbol_id, callees.items[0].provenance["source_id"])

    def test_cursor_is_opaque_bounded_and_deterministic(self) -> None:
        target = self.snapshot.find_exact("target")[0]
        page = self.index.navigate(target.symbol_id, "callers", "incoming", 1)
        self.assertTrue(page.truncated)
        self.assertIsNotNone(page.cursor)
        next_page = self.index.navigate(
            target.symbol_id, "callers", "incoming", 1, cursor=page.cursor
        )
        self.assertNotEqual(page.ids, next_page.ids)
        self.assertLessEqual(len(str(page.to_dict()).encode("utf-8")), 8192)

    def test_stale_and_invalid_inputs_have_stable_reason_codes(self) -> None:
        target = self.snapshot.find_exact("target")[0]
        with self.assertRaises(NavigationError) as stale:
            self.index.navigate(
                target.symbol_id,
                "definition",
                "outgoing",
                1,
                generation="SFAST001:" + "0" * 64,
            )
        self.assertEqual("stale_generation", stale.exception.reason_code)
        with self.assertRaises(NavigationError) as unknown:
            self.index.navigate("f" * 64, "definition", "outgoing", 1)
        self.assertEqual("unknown_handle", unknown.exception.reason_code)
        with self.assertRaises(NavigationError) as invalid_cursor:
            self.index.navigate(
                target.symbol_id, "definition", "outgoing", 1, cursor="not-a-cursor"
            )
        self.assertEqual("invalid_cursor", invalid_cursor.exception.reason_code)

    def test_next_executable_hop_selects_highest_confidence_callee(self) -> None:
        caller = self.snapshot.find_exact("caller")[0]
        page = self.index.navigate(
            caller.symbol_id, "next_executable_hop", "outgoing", {"max_nodes": 1}
        )
        self.assertEqual("simplicio.fast-navigation/v1", page.schema)
        self.assertEqual(("target",), tuple(item.qualified_name for item in page.items))
        self.assertEqual(
            ("call",), tuple(item.provenance["relation_kind"] for item in page.items)
        )
        self.assertFalse(page.truncated)
        incoming = self.index.navigate(
            caller.symbol_id, "next_executable_hop", "incoming", {"max_nodes": 1}
        )
        self.assertFalse(incoming.complete)
        self.assertEqual("next_executable_hop_requires_outgoing", incoming.residual)

    def test_previous_executable_hop_selects_incoming_caller(self) -> None:
        target = self.snapshot.find_exact("target")[0]
        page = self.index.navigate(
            target.symbol_id, "previous_executable_hop", "incoming", {"max_nodes": 1}
        )
        self.assertEqual(("caller",), tuple(item.qualified_name for item in page.items))
        self.assertEqual(
            ("call",), tuple(item.provenance["relation_kind"] for item in page.items)
        )
        self.assertEqual(0.8, page.items[0].confidence)
        outgoing = self.index.navigate(
            target.symbol_id, "previous_executable_hop", "outgoing", {"max_nodes": 1}
        )
        self.assertFalse(outgoing.complete)
        self.assertEqual("previous_executable_hop_requires_incoming", outgoing.residual)

    def test_unmaterialized_relations_are_explicit_and_navigation_does_not_write(
        self,
    ) -> None:
        target = self.snapshot.find_exact("target")[0]
        before = hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest()
        page = self.index.navigate(
            target.symbol_id, "imports", "outgoing", {"max_nodes": 1}
        )
        after = hashlib.sha256(self.snapshot_path.read_bytes()).hexdigest()
        self.assertFalse(page.complete)
        self.assertEqual("relation_not_materialized_by_sfast_v2", page.residual)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
