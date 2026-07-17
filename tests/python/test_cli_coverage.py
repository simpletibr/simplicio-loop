"""Coverage for documented Python CLI paths not previously exercised (#103).

These tests close the gap in tests/python/test_cli.py:

- `--docs-only` routing on `index`/`map`/`update` short-circuits to docs render.
- `--json-only` / `--changed-only` aliases map to `--no-docs` / incremental.
- `--stack` / `--product-name` flow into `product.stack` / `product.name` in the
  emitted project-map when `.starter-meta.json` is absent.
- `index` exception boundary returns exit code 1 with a `status="failed"` JSON
  payload that carries the original `error`.
- A bounded `_watch` test confirms the loop exits cleanly on `KeyboardInterrupt`
  without crashing the process.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper import cli as cli_module  # noqa: E402
from simplicio_mapper.cli import _status_engine as status_engine  # noqa: E402

# `time` moved into cli/_background.py as part of the issue #159 god-file
# split (cli.py -> cli/ package) -- __init__.py itself no longer imports the
# stdlib `time` module directly, so patch it where `_watch` actually calls it.
from simplicio_mapper.cli import _background as cli_background  # noqa: E402
from simplicio_mapper.cli import main  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _run(argv: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class StackAndProductHintInjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "hint-host"}))
        _write(self.dir, "src/index.py", "def run() -> int:\n    return 1\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_stack_and_product_name_flow_into_project_map(self) -> None:
        code, _, _ = _run([
            "map",
            "--root", str(self.dir),
            "--stack", "python-fastapi",
            "--product-name", "Hint Host",
            "--silent",
        ])
        self.assertEqual(code, 0)
        project_map = json.loads(
            (self.dir / ".simplicio" / "project-map.json").read_text()
        )
        self.assertEqual(project_map["product"]["stack"], "python-fastapi")
        self.assertEqual(project_map["product"]["name"], "Hint Host")


class JsonOnlyAndChangedOnlyAliasesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "alias-host"}))
        _write(self.dir, "src/index.js", "export function run(){}\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_json_only_keeps_docs_disabled(self) -> None:
        code, _, _ = _run([
            "index", str(self.dir), "--json", "--json-only",
        ])
        self.assertEqual(code, 0)
        # docs should not have been rendered as a side effect.
        self.assertFalse((self.dir / ".simplicio" / "docs").exists())

    def test_changed_only_triggers_incremental_refresh(self) -> None:
        # First run primes the cache.
        _run(["map", "--root", str(self.dir), "--silent"])
        _write(self.dir, "src/index.js", "export function run(){return 1;}\n")
        code, _, _ = _run([
            "map", "--root", str(self.dir), "--changed-only", "--silent",
        ])
        self.assertEqual(code, 0)
        project_map = json.loads(
            (self.dir / ".simplicio" / "project-map.json").read_text()
        )
        self.assertEqual(project_map["update_mode"], "incremental")


class DocsOnlyShortCircuitTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "docs-only-host"}))
        _write(self.dir, "src/index.js", "export function run(){}\n")
        # Seed JSON artifacts so docs-only has something to render from.
        _run(["map", "--root", str(self.dir), "--silent"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_docs_only_on_index_renders_docs_without_rewriting_json(self) -> None:
        project_map_path = self.dir / ".simplicio" / "project-map.json"
        before = project_map_path.read_text()
        code, _, _ = _run([
            "index", str(self.dir), "--docs-only", "--json",
        ])
        self.assertEqual(code, 0)
        after = project_map_path.read_text()
        # JSON payload is not rewritten by --docs-only.
        self.assertEqual(before, after)
        # At least one markdown file is rendered.
        docs_dir = self.dir / ".simplicio" / "docs"
        self.assertTrue(docs_dir.exists())
        self.assertTrue(any(docs_dir.rglob("*.md")))


class IndexFailureBoundaryTest(unittest.TestCase):
    def test_index_failure_returns_exit_1_with_failed_status_json(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = Path(tmp.name)
        _write(target, "package.json", json.dumps({"name": "fail-host"}))

        boom = RuntimeError("boom")
        with mock.patch.object(cli_module, "_run_index", side_effect=boom):
            code, stdout, _ = _run([
                "index", str(target), "--json",
            ])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.strip())
        self.assertEqual(payload["status"], "failed")
        self.assertIn("boom", payload.get("error", ""))


class WatchLoopExitsOnInterruptTest(unittest.TestCase):
    def test_watch_loop_handles_keyboard_interrupt_cleanly(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = Path(tmp.name)
        _write(target, "package.json", json.dumps({"name": "watch-host"}))
        _write(target, "src/index.js", "export function run(){}\n")

        opts = {
            "command": "map",
            "root": str(target),
            "out": ".simplicio",
            "stack": "",
            "product_name": "",
            "incremental": True,
            "watch": True,
            "silent": True,
            "json": False,
            "verbose": False,
            "docs": False,
            "docs_only": False,
            "background": False,
            "against": "",
            "target": "",
        }

        # Replace time.sleep so the watch loop hits a single iteration then exits
        # via the documented KeyboardInterrupt branch.
        with mock.patch.object(cli_background.time, "sleep", side_effect=KeyboardInterrupt):
            # Should return cleanly without raising — that is the contract.
            with contextlib.redirect_stdout(io.StringIO()):
                cli_module._watch(opts)


class SynchronousScanTimeoutTest(unittest.TestCase):
    def test_sync_scan_timeout_is_terminal_and_nonzero(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = Path(tmp.name)
        _write(target, "package.json", json.dumps({"name": "timeout-host"}))
        _write(target, "src/index.js", "export function run(){}\n")

        class StuckWorker:
            pid = 424242

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired(["fake-index"], timeout)

            def poll(self):
                return None

        spawned = {
            "pid": 424242,
            "process_start": "fake-start",
            "log": str(target / ".simplicio" / "background-index.log"),
        }
        with (
            mock.patch.object(status_engine, "_spawn_index_process", return_value=(spawned, StuckWorker())),
            mock.patch.object(status_engine, "_terminate_index_worker"),
        ):
            code, stdout, _ = _run([
                "scan", str(target), "--sync", "--timeout", "1", "--json",
            ])

        self.assertEqual(code, 1)
        payload = json.loads(stdout.strip())
        self.assertEqual(payload["phase"], "timeout")
        self.assertTrue(payload["sync"])
        self.assertEqual(payload["deep"]["failure_reason"], "scan_timeout")
        self.assertEqual(payload["deep"]["timeout_seconds"], 1)

        status_out = io.StringIO()
        with contextlib.redirect_stdout(status_out):
            self.assertEqual(cli_module.main(["status", str(target), "--json"]), 0)
        status = json.loads(status_out.getvalue().strip())
        self.assertEqual(status["phase"], "failed")
        self.assertTrue(status["terminal"])
        self.assertEqual(status["failure_reason"], "scan_timeout")


if __name__ == "__main__":
    unittest.main()
