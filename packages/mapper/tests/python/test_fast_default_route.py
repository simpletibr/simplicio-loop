"""Default mapper route: macro now, target corridor in front, deep in background."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.cli._args import _parse_args  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class FastDefaultRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self._tmp.name)
        _write(self.dir, "src/app.py", "class App:\n    def run(self):\n        return 1\n")
        _write(self.dir, "tests/test_app.py", "def test_run():\n    assert True\n")
        self._ci = mock.patch.dict(os.environ, {"CI": ""}, clear=False)
        self._ci.start()

    def tearDown(self) -> None:
        self._ci.stop()
        self._tmp.cleanup()

    def test_bare_invocation_defaults_to_scan(self) -> None:
        opts = _parse_args([str(self.dir), "--json"])
        self.assertEqual("scan", opts["command"])
        self.assertEqual(str(self.dir), opts["root"])

    def test_map_without_watch_uses_scan_envelope(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["map", str(self.dir), "--json"])
        self.assertEqual(0, code)
        payload = json.loads(out.getvalue())
        self.assertEqual("simplicio.map-job/v1", payload["schema"])
        self.assertIn(payload["phase"], {"macro_done", "complete"})
        self.assertIn(payload["route"], {"macro_then_background", "reuse"})
        self.assertFalse(payload["sync"])

    def test_cold_scan_with_target_attaches_corridor(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["scan", str(self.dir), "--target", "src/app.py", "--json"])
        self.assertEqual(0, code)
        payload = json.loads(out.getvalue())
        self.assertEqual("macro_then_target_then_background", payload["route"])
        corridor = payload.get("corridor") or {}
        self.assertTrue(corridor.get("ready"), corridor)
        paths = [item.get("path") for item in corridor.get("spans") or corridor.get("selected_paths") or []]
        self.assertTrue(any(str(path).endswith("src/app.py") for path in paths), paths)

    def test_second_scan_reuses_fresh_artifacts(self) -> None:
        first = StringIO()
        with redirect_stdout(first):
            self.assertEqual(0, main(["scan", str(self.dir), "--sync", "--json"]))
        first_payload = json.loads(first.getvalue())
        self.assertEqual("complete", first_payload["phase"])
        second = StringIO()
        with redirect_stdout(second):
            self.assertEqual(0, main(["scan", str(self.dir), "--json"]))
        payload = json.loads(second.getvalue())
        self.assertEqual("complete", payload["phase"])
        self.assertEqual("already_fresh", payload["deep"]["skipped_reason"])
        self.assertEqual("reuse", payload["route"])
        self.assertNotIn("pid", payload["deep"])

    def test_warm_scan_with_target_attaches_handoff(self) -> None:
        with redirect_stdout(StringIO()):
            self.assertEqual(0, main(["scan", str(self.dir), "--sync", "--json"]))
        out = StringIO()
        with redirect_stdout(out):
            code = main(
                [
                    "scan",
                    str(self.dir),
                    "--goal",
                    "change App.run",
                    "--target",
                    "src/app.py",
                    "--json",
                ]
            )
        self.assertEqual(0, code)
        payload = json.loads(out.getvalue())
        self.assertEqual("reuse_then_target", payload["route"])
        handoff = payload.get("handoff") or {}
        self.assertEqual("simplicio.map-handoff/v1", handoff.get("schema"))
        self.assertIn("src/app.py", handoff.get("targets") or [])
