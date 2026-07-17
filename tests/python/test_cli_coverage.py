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
import os
import subprocess
import sys
import tempfile
import time
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


class BackgroundWorkerNeverInheritsStdinTest(unittest.TestCase):
    """Regression coverage for issue #231 (WinError 6 on inherited stdin).

    On Windows, ``subprocess.Popen``/``subprocess.run`` inherit the parent's
    stdin handle unless told otherwise. When the parent stdin is captured or
    closed (pytest, some Codex/PowerShell hosts), that inheritance attempt
    raises ``OSError: [WinError 6]`` from ``_winapi.DuplicateHandle`` *before*
    the child process is even created. Every subprocess call on the
    background/index worker path must pass an explicit non-inheriting stdin
    so the worker never depends on (or blocks on) the host's stdin.
    """

    def test_spawn_index_process_pins_stdin_devnull(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = Path(tmp.name)
        _write(target, "package.json", json.dumps({"name": "stdin-host"}))

        opts = {
            "root": str(target),
            "out": ".simplicio",
            "stack": None,
            "product_name": None,
            "docs": False,
            "incremental": False,
            "verbose": False,
        }

        real_popen = subprocess.Popen
        captured: dict = {}

        class _FakeChild:
            pid = 123456

            def wait(self, timeout=None):
                return 0

            def poll(self):
                return 0

        def _fake_popen(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return _FakeChild()

        with mock.patch.object(subprocess, "Popen", side_effect=_fake_popen):
            payload, child = cli_background._spawn_index_process(opts)

        self.assertIs(subprocess.Popen, real_popen)  # patch scoped, no leakage
        self.assertEqual(captured["kwargs"].get("stdin"), subprocess.DEVNULL)
        self.assertEqual(payload["pid"], 123456)
        self.assertIsInstance(child, _FakeChild)

    def test_spawn_background_index_survives_closed_os_stdin(self) -> None:
        """End-to-end proof: closing the real OS stdin handle (fd 0) before
        spawning the worker must not raise. This is the literal repro
        described in issue #231 -- a host with an invalid/closed inherited
        stdin handle -- reproduced in a child interpreter so the current
        process's own stdin (needed by the test runner) is left untouched.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = Path(tmp.name)
        _write(target, "package.json", json.dumps({"name": "closed-stdin-host"}))

        script = (
            "import sys, os, json;"
            f"sys.path.insert(0, {str(ROOT)!r});"
            "os.close(0);"
            "from simplicio_mapper.cli._background import _spawn_background_index;"
            "opts = {"
            f"'root': {str(target)!r}, 'out': '.simplicio', 'stack': None,"
            "'product_name': None, 'docs': False, 'incremental': False, 'verbose': False"
            "};"
            "payload = _spawn_background_index(opts);"
            "print(json.dumps(payload))"
        )
        # NOTE: this harness's own subprocess.run call also needs an explicit
        # non-inheriting stdin -- test hosts (this one included) can already
        # have an invalid/captured stdin handle at the OS level, which is
        # exactly the class of host issue #231 describes. Without this, the
        # harness call itself (not the code under test) raises WinError 6.
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertEqual(payload["schema"], "simplicio.background-index/v1")
        self.assertEqual(payload["status"], "started")
        self.assertGreater(payload["pid"], 0)

        # The worker keeps running detached from the child interpreter above
        # (which already exited). Wait for it to finish writing artifacts
        # before the TemporaryDirectory cleanup runs, otherwise cleanup races
        # a still-open log file handle on Windows.
        project_map = target / ".simplicio" / "project-map.json"
        for _ in range(100):
            if project_map.exists():
                break
            time.sleep(0.05)
        self.assertTrue(project_map.exists(), "background worker never produced artifacts")

        # Artifact presence means the worker is done computing, but the
        # detached process can still hold its log file open for a moment
        # while exiting. Poll for the handle to release so cleanup doesn't
        # race a live file lock on Windows.
        log_path = target / ".simplicio" / "background-index.log"
        for _ in range(60):
            try:
                with open(log_path, "a", encoding="utf-8"):
                    pass
                os.rename(log_path, log_path)  # exclusive-open probe
                break
            except OSError:
                time.sleep(0.05)


class TerminateIndexWorkerNeverInheritsStdinTest(unittest.TestCase):
    def test_taskkill_invocation_pins_stdin_devnull_on_windows(self) -> None:
        class _AliveThenDeadChild:
            pid = 987654
            _polled = False

            def poll(self):
                if self._polled:
                    return 0
                self._polled = True
                return None

            def wait(self, timeout=None):
                return 0

        captured: dict = {}

        def _fake_run(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(args, 0)

        with (
            mock.patch.object(status_engine.os, "name", "nt"),
            mock.patch.object(subprocess, "run", side_effect=_fake_run),
        ):
            status_engine._terminate_index_worker(_AliveThenDeadChild())

        self.assertIn("taskkill", captured["args"][0])
        self.assertEqual(captured["kwargs"].get("stdin"), subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
