"""Unit tests for WI-471 CLI contract: `preflight` subcommand + `status --json`.

Covers the two contracts the published `simplicio-loop 3.36.1` install was missing:
  * `simplicio-loop preflight --repo .` must exist and emit a machine-readable JSON doc.
  * `simplicio-loop status --repo . --json` must accept `--json` and emit JSON (never
    "unrecognized arguments"), and must not raise on a repo with no runs.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]


def _run_cli(args: list[str], *, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Invoke the CLI module as a subprocess; return (rc, stdout, stderr)."""
    # Python 3.14 on Windows can reject pytest's captured pipe handles while
    # creating another child. Regular temporary files avoid inheriting those
    # host capture handles while preserving the CLI output assertions.
    with tempfile.TemporaryDirectory() as scratch:
        stdout_path = Path(scratch) / "stdout.txt"
        stderr_path = Path(scratch) / "stderr.txt"
        with stdout_path.open("w+", encoding="utf-8") as stdout, stderr_path.open(
            "w+", encoding="utf-8"
        ) as stderr:
            proc = subprocess.run(
                [sys.executable, "-m", "simplicio_loop.cli", *args],
                cwd=str(REPO), stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL,
                text=True, timeout=60, env=env,
            )
            stdout.seek(0)
            stderr.seek(0)
            return proc.returncode, stdout.read(), stderr.read()


class _CliShimTestCase(TestCase):
    """Run CLI contracts against deterministic operator executables only."""

    def setUp(self) -> None:
        self._shim_dir = tempfile.TemporaryDirectory()
        bin_dir = Path(self._shim_dir.name)
        versions = {
            "simplicio-mapper": "simplicio-mapper 0.23.1",
            "simplicio-dev-cli": "simplicio-dev-cli 0.16.1",
            "simplicio-py": "simplicio-py 0.16.1",
            "simplicio-fast": "simplicio-fast 2.0.22",
            "simplicio": "simplicio-runtime 1.0.0",
        }
        for name, version in versions.items():
            if os.name == "nt":
                shim = bin_dir / f"{name}.cmd"
                shim.write_text(f"@echo off\necho {version}\n", encoding="utf-8")
            else:
                shim = bin_dir / name
                shim.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\n", encoding="utf-8")
                shim.chmod(0o755)
        # Keep Windows runtime variables (SystemRoot/TEMP/etc.) required by
        # asyncio and subprocess, while excluding host operators from PATH.
        self.cli_env = {**os.environ, "PATH": str(bin_dir)}

    def tearDown(self) -> None:
        self._shim_dir.cleanup()

    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        return _run_cli(args, env=self.cli_env)


class PreflightContractTest(_CliShimTestCase):
    def test_preflight_exists_and_emits_json(self):
        rc, out, err = self.run_cli(["preflight", "--repo", ".", "--json"])
        self.assertEqual(rc, 0, msg=f"preflight exited {rc}; stderr={err}")
        doc = json.loads(out)
        self.assertEqual(doc["schema"], "simplicio.preflight/v1")
        self.assertIn("all_present", doc)
        self.assertIn("operators", doc)
        self.assertIsInstance(doc["operators"], list)
        self.assertTrue(len(doc["operators"]) >= 3)

    def test_preflight_text_mode_names_operators(self):
        rc, out, err = self.run_cli(["preflight", "--repo", "."])
        self.assertEqual(rc, 0, msg=f"stderr={err}")
        self.assertIn("simplicio-loop preflight", out)
        self.assertIn("simplicio-mapper", out)
        self.assertIn("simplicio-runtime", out)

    def test_preflight_rejects_unknown_subcommand_still_absent(self):
        # Sanity: a genuinely unknown command must still error (proves we only ADDED preflight).
        rc, _out, err = self.run_cli(["nonexistent-xyz"])
        self.assertNotEqual(rc, 0)
        self.assertIn("invalid choice", err)


class StatusJsonContractTest(_CliShimTestCase):
    def test_status_json_accepted_without_runs(self):
        rc, out, err = self.run_cli(["status", "--repo", ".", "--json"])
        self.assertEqual(rc, 0, msg=f"status --json crashed; stderr={err}")
        self.assertEqual(err.count("unrecognized arguments"), 0,
                         msg="--json must be accepted, not 'unrecognized arguments'")
        doc = json.loads(out)
        # Without runs we expect a controlled UNVERIFIED doc, not a traceback.
        self.assertIn(doc.get("status"), ("UNVERIFIED", "ok"))
        self.assertIn("schema", doc)

    def test_status_json_flag_never_unrecognized(self):
        # The exact regression from issue #471: public install rejected `--json`.
        rc, _out, err = self.run_cli(["status", "--repo", ".", "--json"])
        self.assertEqual(rc, 0)
        self.assertNotIn("unrecognized arguments: --json", err)

    def test_status_text_mode_without_runs_does_not_traceback(self):
        rc, out, err = self.run_cli(["status", "--repo", ".", "--text"])
        self.assertEqual(rc, 0, msg=f"text status crashed; stderr={err}")
        self.assertNotIn("Traceback", err)
        self.assertIn("simplicio-loop run status", out)


class DirectCallCoverageTest(TestCase):
    """Import-level calls to raise line/branch coverage of the patched functions."""

    @staticmethod
    def _present_operator_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        names = {
            "simplicio-mapper": "simplicio-mapper 0.23.1",
            "simplicio-dev-cli": "simplicio-dev-cli 0.16.1",
            "simplicio-py": "simplicio-py 0.16.1",
            "simplicio": "simplicio-runtime 1.0.0",
            "simplicio-fast": "simplicio-fast 2.0.16",
        }
        return subprocess.CompletedProcess(command, 0, stdout=names[command[0]] + "\n", stderr="")

    def test_preflight_direct_call_text(self):
        from simplicio_loop import cli, strict_mode
        buf = io.StringIO()
        with patch.object(cli.subprocess, "run", side_effect=self._present_operator_run), \
             patch.object(strict_mode.shutil, "which", side_effect=lambda name: name), \
             patch.object(strict_mode, "RUNTIME_BIN_ENV_KEYS", ()), \
             patch.object(strict_mode, "_runtime_candidate_paths", return_value=["simplicio"]), \
             contextlib.redirect_stdout(buf):
            rc = cli.preflight(str(REPO), as_json=False)
        self.assertEqual(rc, 0)
        self.assertIn("simplicio-loop preflight", buf.getvalue())

    def test_preflight_direct_call_json(self):
        from simplicio_loop import cli, strict_mode
        buf = io.StringIO()
        with patch.object(cli.subprocess, "run", side_effect=self._present_operator_run), \
             patch.object(strict_mode.shutil, "which", side_effect=lambda name: name), \
             patch.object(strict_mode, "RUNTIME_BIN_ENV_KEYS", ()), \
             patch.object(strict_mode, "_runtime_candidate_paths", return_value=["simplicio"]), \
             contextlib.redirect_stdout(buf):
            rc = cli.preflight(str(REPO), as_json=True)
        self.assertEqual(rc, 0)
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["schema"], "simplicio.preflight/v1")

    def test_preflight_direct_call_missing_core_operator_blocks(self):
        from simplicio_loop import cli, finding_router, strict_mode

        def missing_mapper(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if command[0] == "simplicio-mapper":
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="not installed")
            return self._present_operator_run(command)

        buf = io.StringIO()
        with patch.object(cli.subprocess, "run", side_effect=missing_mapper), \
             patch.object(strict_mode.shutil, "which", side_effect=lambda name: name), \
             patch.object(strict_mode, "RUNTIME_BIN_ENV_KEYS", ()), \
             patch.object(strict_mode, "_runtime_candidate_paths", return_value=["simplicio"]), \
             patch.object(finding_router, "route_finding"), \
             contextlib.redirect_stdout(buf):
            rc = cli.preflight(str(REPO), as_json=True)
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(buf.getvalue())["all_present"])

    def test_status_direct_call_no_runs_json(self):
        from simplicio_loop import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.status(str(REPO), "", as_json=True)
        self.assertEqual(rc, 0)
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["reason_code"], "run_missing")

    def test_status_direct_call_no_runs_text(self):
        from simplicio_loop import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.status(str(REPO), "", as_text=True)
        self.assertEqual(rc, 0)
        self.assertIn("simplicio-loop run status", buf.getvalue())


class RenderStatusTextUnitTest(TestCase):
    """Isolated coverage of the patched _render_status_text helper."""

    def test_render_with_full_payload(self):
        from simplicio_loop import cli
        payload = {
            "run_dir": "/tmp/x",
            "execution_route": {
                "route": "worker", "receipt_sha": "route-sha-1",
                "backend": "deterministic-worker",
            },
            "state": {
                "phase": "executing",
                "completion": {"tag": "VERIFIED", "coverage": "3/3"},
                "delivery": {"ready": True},
            },
        }
        out = cli._render_status_text(payload)
        self.assertIn("run_dir: /tmp/x", out)
        self.assertIn("phase: executing", out)
        self.assertIn("completion_tag: VERIFIED", out)
        self.assertIn("coverage: 3/3", out)
        self.assertIn("delivery_ready: True", out)
        self.assertIn("execution_route: worker", out)
        self.assertIn("route_receipt_sha: route-sha-1", out)
        self.assertIn("route_backend: deterministic-worker", out)

    def test_render_with_minimal_payload(self):
        from simplicio_loop import cli
        payload = {"state": {}}
        out = cli._render_status_text(payload)
        self.assertIn("phase: UNKNOWN", out)
        self.assertIn("completion_tag: UNVERIFIED", out)
        self.assertIn("delivery_ready: False", out)
