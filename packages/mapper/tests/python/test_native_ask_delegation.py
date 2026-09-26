"""Tests for native `ask impact`/`ask tests-for` delegation to the `simplicio`
runtime binary (issue #174, "delegação nativa com savings por verbo").

The real `simplicio` runtime binary is not available in this container, so
these tests exercise a REAL subprocess against a controllable fake binary
(`tests/python/fixtures/fake_simplicio_runtime.py`) instead of mocking
`subprocess.run` -- genuine argv construction, real process spawn, and real
stdout/JSON round-tripping through `_runtime_ask_query`. `shutil.which` is
patched to point at the fake script (mirroring `PrecedentVerbTest` in
`test_query.py`, which patches `shutil.which` the same way) since the fake
script cannot be literally named `simplicio` on a shared PATH without
clobbering other tests/CI steps that also patch `shutil.which`.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.query import ASK_SCHEMA, run_query  # noqa: E402

FAKE_BINARY = str(Path(__file__).resolve().parent / "fixtures" / "fake_simplicio_runtime.py")


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class NativeAskDelegationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._env_backup = dict(os.environ)
        _write(self.dir, "package.json", json.dumps({"name": "native-ask-app", "main": "src/main.py"}))
        _write(
            self.dir,
            "src/main.py",
            "from src.writer import persist\ndef main():\n    persist()\n",
        )
        _write(
            self.dir,
            "src/writer.py",
            "def persist():\n    with open('out.json', 'w') as handle:\n        handle.write('{}')\n",
        )
        _write(
            self.dir,
            "tests/test_writer.py",
            "from src.writer import persist\n\ndef test_persist():\n    persist()\n",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _which_fake(self, name: str) -> str | None:
        return FAKE_BINARY if name == "simplicio" else shutil.which(name)

    def _ledger_path(self) -> Path:
        return self.dir / ".simplicio-loop" / "ledger" / "savings-events.jsonl"

    # -- impact ------------------------------------------------------------

    def test_impact_uses_native_runtime_when_binary_present(self) -> None:
        os.environ.pop("SIMPLICIO_MAPPER_NO_RUNTIME_IMPACT", None)
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            payload = run_query(str(self.dir), verb="impact", arg="src/writer.py")
        self.assertEqual(payload["schema"], ASK_SCHEMA)
        self.assertEqual(payload["results"]["affected_symbols"][0]["symbol"], "fake_symbol")

    def test_impact_records_savings_event_on_native_hit(self) -> None:
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            run_query(str(self.dir), verb="impact", arg="src/writer.py")
        ledger = self._ledger_path()
        self.assertTrue(ledger.exists(), "expected a savings-events.jsonl to be written on native hit")
        lines = ledger.read_text(encoding="utf-8").strip().splitlines()
        event = json.loads(lines[-1])
        self.assertEqual(event["schema"], "simplicio.savings-event/v1")
        self.assertEqual(event["source"], "native-delegation:impact")
        self.assertEqual(event["proof_kind"], "estimated")
        self.assertIn("baseline", event["tokens"])
        self.assertIn("actual", event["tokens"])
        self.assertIn("saved", event["tokens"])
        self.assertIn("pct_saved", event["tokens"])

    def test_impact_falls_back_to_local_when_binary_absent(self) -> None:
        with mock.patch("simplicio_mapper.query.shutil.which", return_value=None):
            payload = run_query(str(self.dir), verb="impact", arg="src/writer.py")
        self.assertIn("affected_flows", payload["results"])
        self.assertGreaterEqual(len(payload["results"]["affected_flows"]), 1)
        self.assertFalse(
            self._ledger_path().exists(), "no savings event should be recorded on a local fallback"
        )
        self.assertEqual(payload["delegation"]["reason"], "binary_missing")

    def test_homonymous_agent_binary_is_rejected_before_delegation(self) -> None:
        os.environ["FAKE_SIMPLICIO_MODE"] = "agent-homonym"
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            payload = run_query(str(self.dir), verb="impact", arg="src/writer.py")
        self.assertEqual(payload["source"], "local-python")
        self.assertFalse(payload["delegation"]["used"])
        self.assertEqual(payload["delegation"]["reason"], "identity_mismatch")

    def test_impact_kill_switch_forces_local_even_when_binary_present(self) -> None:
        os.environ["SIMPLICIO_MAPPER_NO_RUNTIME_IMPACT"] = "1"
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            payload = run_query(str(self.dir), verb="impact", arg="src/writer.py")
        self.assertIn("affected_flows", payload["results"])
        self.assertFalse(self._ledger_path().exists())

    def test_impact_falls_back_on_bad_schema(self) -> None:
        os.environ["FAKE_SIMPLICIO_MODE"] = "bad-schema"
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            payload = run_query(str(self.dir), verb="impact", arg="src/writer.py")
        self.assertIn("affected_flows", payload["results"])

    def test_impact_falls_back_on_bad_json(self) -> None:
        os.environ["FAKE_SIMPLICIO_MODE"] = "bad-json"
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            payload = run_query(str(self.dir), verb="impact", arg="src/writer.py")
        self.assertIn("affected_flows", payload["results"])

    def test_impact_falls_back_on_nonzero_exit(self) -> None:
        os.environ["FAKE_SIMPLICIO_MODE"] = "nonzero"
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            payload = run_query(str(self.dir), verb="impact", arg="src/writer.py")
        self.assertIn("affected_flows", payload["results"])

    # -- tests-for -----------------------------------------------------------

    def test_tests_for_uses_native_runtime_when_binary_present(self) -> None:
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            payload = run_query(str(self.dir), verb="tests-for", arg="src/writer.py")
        self.assertEqual(payload["results"], ["tests/test_fake.py"])
        self.assertEqual(
            payload["delegation"],
            {
                "runtime": "simplicio-runtime",
                "used": True,
                "reason": "delegated",
            },
        )

    def test_tests_for_records_savings_event_on_native_hit(self) -> None:
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            run_query(str(self.dir), verb="tests-for", arg="src/writer.py")
        ledger = self._ledger_path()
        self.assertTrue(ledger.exists())
        event = json.loads(ledger.read_text(encoding="utf-8").strip().splitlines()[-1])
        self.assertEqual(event["source"], "native-delegation:tests-for")
        self.assertEqual(event["proof_kind"], "estimated")

    def test_tests_for_falls_back_to_local_when_binary_absent(self) -> None:
        with mock.patch("simplicio_mapper.query.shutil.which", return_value=None):
            payload = run_query(str(self.dir), verb="tests-for", arg="src/writer.py")
        self.assertIn("tests/test_writer.py", payload["results"])

    def test_tests_for_kill_switch_forces_local_even_when_binary_present(self) -> None:
        os.environ["SIMPLICIO_MAPPER_NO_RUNTIME_TESTS_FOR"] = "1"
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            payload = run_query(str(self.dir), verb="tests-for", arg="src/writer.py")
        self.assertIn("tests/test_writer.py", payload["results"])
        self.assertFalse(self._ledger_path().exists())

    def test_precedent_kill_switch_is_unaffected_by_ask_kill_switches(self) -> None:
        # Regression guard: the new per-verb kill-switches must not leak into
        # (or be satisfied by) the pre-existing precedent kill-switch or vice
        # versa -- each verb's native path is independently gated.
        os.environ["SIMPLICIO_MAPPER_NO_RUNTIME_PRECEDENT"] = "1"
        with mock.patch("simplicio_mapper.query.shutil.which", side_effect=self._which_fake):
            payload = run_query(str(self.dir), verb="impact", arg="src/writer.py")
        self.assertEqual(payload["results"]["affected_symbols"][0]["symbol"], "fake_symbol")


if __name__ == "__main__":
    unittest.main()
