import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

from simplicio_fast.engine import (
    EngineSelection,
    EngineSelectionError,
    PythonManifestError,
    python_manifest,
    select_engine,
    validate_python_manifest,
)
from simplicio_fast.runtime_backend import RuntimeSelection
from simplicio_fast.cli import main


class EngineSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        from simplicio_fast import cli

        cli._close_rust_sessions()

    def test_auto_selects_python_with_explicit_rust_gap(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("simplicio_fast.engine.shutil.which", return_value=None):
                selection = select_engine("auto")
        self.assertEqual("python", selection.selected)
        self.assertEqual("rust_executable_missing", selection.reason)
        self.assertTrue(selection.manifest["reference"])

    def test_python_selection_never_probes_or_imports_rust_engine(self) -> None:
        with patch("simplicio_fast.engine.probe_rust", side_effect=AssertionError):
            selection = select_engine("python")
        self.assertEqual("python", selection.selected)
        self.assertEqual("explicitly_selected", selection.reason)

    def test_explicit_rust_fails_closed_when_missing(self) -> None:
        with patch("simplicio_fast.engine.shutil.which", return_value=None):
            with self.assertRaises(EngineSelectionError) as raised:
                select_engine("rust")
        self.assertEqual("rust_executable_missing", raised.exception.receipt["reason"])
        self.assertEqual("unavailable", raised.exception.receipt["selected"])

    def test_probe_requires_conformance_before_auto_promotion(self) -> None:
        manifest = {
            "schema": "simplicio.fast.engine-manifest/v1",
            "engine": "rust",
            "status": "available",
            "conformance": {"passed": False},
        }
        with (
            patch("simplicio_fast.engine._rust_executable", return_value="rust.exe"),
            patch("simplicio_fast.engine.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(manifest)
            run.return_value.stderr = ""
            selection = select_engine("auto")
        self.assertEqual("python", selection.selected)
        self.assertEqual("rust_conformance_missing", selection.reason)

    def test_probe_requires_conformance_digest_before_auto_promotion(self) -> None:
        manifest = {
            "schema": "simplicio.fast.engine-manifest/v1",
            "engine": "rust",
            "status": "available",
            "conformance": {"passed": True},
        }
        with (
            patch("simplicio_fast.engine._rust_executable", return_value="rust.exe"),
            patch("simplicio_fast.engine.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(manifest)
            run.return_value.stderr = ""
            selection = select_engine("auto")
        self.assertEqual("python", selection.selected)
        self.assertEqual("rust_conformance_missing", selection.reason)

    def test_manifest_is_versioned_and_declares_reference_capabilities(self) -> None:
        manifest = python_manifest()
        self.assertEqual("simplicio.fast.engine-manifest/v1", manifest["schema"])
        self.assertIn("context", manifest["capabilities"])
        self.assertIn("apply", manifest["capabilities"])
        self.assertEqual(["python"], manifest["source_languages"])
        self.assertEqual("3.11", manifest["minimum_python"])
        self.assertEqual(512 * 1024 * 1024, manifest["limits"]["max_snapshot_bytes"])

    def test_python_manifest_validation_rejects_missing_capability_with_stable_code(
        self,
    ) -> None:
        manifest = python_manifest()
        manifest["capabilities"].remove("query")
        with self.assertRaises(PythonManifestError) as raised:
            validate_python_manifest(manifest)
        self.assertEqual("capability_missing", raised.exception.reason_code)

    def test_python_manifest_validation_rejects_identity_and_format_drift(self) -> None:
        manifest = python_manifest()
        manifest["engine"] = "rust"
        with self.assertRaises(PythonManifestError) as raised:
            validate_python_manifest(manifest)
        self.assertEqual("manifest_field_invalid", raised.exception.reason_code)
        manifest = python_manifest()
        manifest["formats"] = ["SFAST001/v1"]
        with self.assertRaises(PythonManifestError) as raised:
            validate_python_manifest(manifest)
        self.assertEqual("formats_missing", raised.exception.reason_code)

    def test_cli_accepts_engine_selector_after_command(self) -> None:
        output = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                ["simplicio-fast", "capabilities", "--fast-engine", "python"],
            ),
            contextlib.redirect_stdout(output),
        ):
            main()
        payload = json.loads(output.getvalue())
        self.assertEqual("python", payload["engine"]["selected"])

    def test_cli_bridges_runtime_selection_without_legacy_session(self) -> None:
        output = io.StringIO()

        class FakeBackend:
            def __init__(self) -> None:
                self.operation = None
                self.payload = None

            def call(self, operation, payload, *, cancel_event=None):
                self.operation = operation
                self.payload = payload
                return {"matches": [{"name": "save"}]}

        backend = FakeBackend()
        selection = RuntimeSelection("rust", "rust", None, backend=backend)
        with (
            patch.object(
                sys,
                "argv",
                [
                    "simplicio-fast",
                    "query",
                    "save",
                    "--snapshot",
                    "snapshot.sfast",
                    "--fast-engine",
                    "rust",
                ],
            ),
            patch("simplicio_fast.cli.select_engine", return_value=selection),
            patch(
                "simplicio_fast.cli.RustCoreSession",
                side_effect=AssertionError("legacy RustCoreSession must not be used"),
            ),
            contextlib.redirect_stdout(output),
        ):
            main()
        payload = json.loads(output.getvalue())
        self.assertEqual("simplicio.fast.query/v1", payload["schema"])
        self.assertEqual("hbp-stdio", payload["transport"])
        self.assertEqual("query", backend.operation)
        self.assertEqual(50, backend.payload["limit"])

    def test_cli_bridges_rust_query_without_importing_python_snapshot(self) -> None:
        output = io.StringIO()
        selection = EngineSelection(
            "rust",
            "rust",
            "rust_probe_passed",
            "simplicio-fast-rs",
            {
                "schema": "simplicio.fast.engine-manifest/v1",
                "engine": "rust",
                "status": "available",
            },
        )
        class FakeSession:
            def call(self, operation, payload):
                self.operation = operation
                self.payload = payload
                return {"matches": [{"name": "save"}]}

            def close(self):
                pass

        fake = FakeSession()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "simplicio-fast",
                    "query",
                    "save",
                    "--snapshot",
                    "snapshot.sfast",
                    "--fast-engine",
                    "rust",
                ],
            ),
            patch("simplicio_fast.cli.select_engine", return_value=selection),
            patch("simplicio_fast.cli.RustCoreSession", return_value=fake),
            contextlib.redirect_stdout(output),
        ):
            main()
        payload = json.loads(output.getvalue())
        self.assertEqual("simplicio.fast.query/v1", payload["schema"])
        self.assertEqual("rust", payload["engine"])
        self.assertEqual([{"name": "save"}], payload["matches"])
        self.assertEqual("query", fake.operation)
        self.assertEqual(50, fake.payload["limit"])

    def test_cli_bridges_rust_context_with_bounded_limits(self) -> None:
        output = io.StringIO()
        selection = EngineSelection(
            "rust",
            "rust",
            "rust_probe_passed",
            "simplicio-fast-rs",
            {
                "schema": "simplicio.fast.engine-manifest/v1",
                "engine": "rust",
                "status": "available",
            },
        )
        class FakeSession:
            def call(self, operation, payload):
                self.operation = operation
                self.payload = payload
                return {"spans": []}

            def close(self):
                pass

        fake = FakeSession()
        with (
            patch.object(
                sys,
                "argv",
                [
                    "simplicio-fast",
                    "context",
                    "save",
                    "--root",
                    ".",
                    "--snapshot",
                    "snapshot.sfast",
                    "--max-results",
                    "2",
                    "--max-lines",
                    "9",
                    "--max-bytes",
                    "100",
                    "--max-tokens",
                    "30",
                    "--fast-engine",
                    "rust",
                ],
            ),
            patch("simplicio_fast.cli.select_engine", return_value=selection),
            patch("simplicio_fast.cli.RustCoreSession", return_value=fake),
            contextlib.redirect_stdout(output),
        ):
            main()
        payload = json.loads(output.getvalue())
        self.assertEqual("simplicio.fast.context/v1", payload["schema"])
        self.assertEqual("context", fake.operation)
        self.assertEqual(9, fake.payload["max_lines"])

    def test_receipt_exposes_python_selection_contract_without_probe(self) -> None:
        with patch("simplicio_fast.engine.probe_rust", side_effect=AssertionError):
            receipt = select_engine(" Python ").receipt()
        self.assertEqual("simplicio.fast.engine-selection/v1", receipt["schema"])
        self.assertEqual("python", receipt["requested"])
        self.assertEqual("python", receipt["selected_engine"])
        self.assertEqual(python_manifest()["version"], receipt["version"])
        self.assertIn("context", receipt["capabilities"])
        self.assertIsNone(receipt["conformance_digest"])
        self.assertIsNone(receipt["timings"]["probe_ms"])

    def test_rust_receipt_contains_conformance_digest_and_probe_timing(self) -> None:
        manifest = {
            "schema": "simplicio.fast.engine-manifest/v1",
            "engine": "rust",
            "version": "3.0.0",
            "status": "available",
            "capabilities": ["query", "context"],
            "conformance": {"passed": True, "digest": "sha256:test"},
        }
        with (
            patch("simplicio_fast.engine._rust_executable", return_value="rust.exe"),
            patch("simplicio_fast.engine.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(manifest)
            run.return_value.stderr = ""
            receipt = select_engine(" RUST ").receipt()
        self.assertEqual("rust", receipt["requested"])
        self.assertEqual("rust", receipt["selected"])
        self.assertEqual("3.0.0", receipt["version"])
        self.assertEqual(["query", "context"], receipt["capabilities"])
        self.assertEqual("sha256:test", receipt["conformance_digest"])
        self.assertGreaterEqual(receipt["timings"]["probe_ms"], 0)
        run.assert_called_once()

    def test_auto_receipt_records_measured_conformance_fallback(self) -> None:
        manifest = {
            "schema": "simplicio.fast.engine-manifest/v1",
            "engine": "rust",
            "version": "3.0.0",
            "status": "available",
            "conformance": {"passed": False},
        }
        with (
            patch("simplicio_fast.engine._rust_executable", return_value="rust.exe"),
            patch("simplicio_fast.engine.subprocess.run") as run,
        ):
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(manifest)
            run.return_value.stderr = ""
            receipt = select_engine("auto").receipt()
        self.assertEqual("python", receipt["selected"])
        self.assertEqual("rust_conformance_missing", receipt["reason"])
        self.assertGreaterEqual(receipt["timings"]["probe_ms"], 0)

    def test_explicit_rust_error_contains_complete_receipt(self) -> None:
        with patch("simplicio_fast.engine._rust_executable", return_value=None):
            with self.assertRaises(EngineSelectionError) as raised:
                select_engine("rust")
        receipt = raised.exception.receipt
        self.assertEqual("rust", receipt["requested_engine"])
        self.assertEqual("unavailable", receipt["selected"])
        self.assertIsNone(receipt["version"])
        self.assertIsNone(receipt["conformance_digest"])
        self.assertIn("probe_ms", receipt["timings"])
