from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simplicio_fast.installation import _smoke_step, report
from simplicio_fast import __version__
from simplicio_fast.installation import python_smoke


class InstallationReportTest(unittest.TestCase):
    def test_python_only_report_is_ready_without_rust_or_network(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("simplicio_fast.installation.shutil.which", return_value=None),
        ):
            payload = report()
        self.assertEqual("simplicio.fast.installation/v1", payload["schema"])
        self.assertEqual("ready", payload["status"])
        self.assertEqual("pass", payload["checks"][1]["status"])
        self.assertEqual("artifact_missing", payload["checks"][2]["reason"])
        self.assertEqual("python", payload["resolution"]["selected_engine"])
        self.assertEqual("rust_artifact_missing", payload["resolution"]["reason_code"])
        self.assertFalse(payload["rollback"]["supported"])

    def test_python_cli_smoke_is_bounded_and_fail_closed_for_rust(self) -> None:
        payload = python_smoke()
        failures = [
            {
                "engine": step["engine"],
                "reason": step.get("reason_code"),
                "error": step.get("error"),
                "returncode": step.get("returncode"),
            }
            for step in payload["steps"]
            if step["status"] != "pass"
        ]
        self.assertIn(
            payload["status"],
            {"pass", "partial"},
            msg=f"launcher={payload['launcher']} reasons={payload['reason_codes']} failures={failures}",
        )
        self.assertEqual("simplicio.fast.python-smoke/v1", payload["schema"])
        self.assertEqual(
            {"auto": "python", "python": "python", "off": "off"},
            payload["engine_selection"],
        )
        self.assertTrue(payload["rust_probe"]["forced_unavailable"])
        self.assertTrue(payload["checks"]["build_refresh_query_context_plan_delivery"])
        self.assertTrue(payload["checks"]["python_fallback"])
        self.assertTrue(payload["checks"]["rust_not_loaded"])
        self.assertTrue(all(step["status"] == "pass" for step in payload["steps"]))

    def test_rust_manifest_and_digest_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "simplicio-fast-rs.exe"
            path.write_bytes(b"artifact")
            manifest = f'{{"schema":"simplicio.fast.engine-manifest/v1","engine":"rust","status":"available","version":"{__version__}"}}'
            completed = type("Completed", (), {"returncode": 0, "stdout": manifest})()
            with (
                patch.dict(os.environ, {"SIMPLICIO_FAST_RUST": str(path)}, clear=True),
                patch(
                    "simplicio_fast.installation.subprocess.run", return_value=completed
                ),
            ):
                payload = report()
        check = payload["checks"][2]
        self.assertEqual("pass", check["status"])
        self.assertEqual("rust", check["manifest"]["engine"])
        self.assertTrue(check["sha256"])
        self.assertEqual("rust", payload["resolution"]["selected_engine"])
        self.assertEqual(
            "rust_manifest_available", payload["resolution"]["reason_code"]
        )

    def test_missing_rust_manifest_version_is_degraded_and_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "simplicio-fast-rs.exe"
            path.write_bytes(b"artifact")
            completed = type(
                "Completed",
                (),
                {
                    "returncode": 0,
                    "stdout": '{"schema":"simplicio.fast.engine-manifest/v1","engine":"rust","status":"available"}',
                },
            )()
            with (
                patch.dict(os.environ, {"SIMPLICIO_FAST_RUST": str(path)}, clear=True),
                patch(
                    "simplicio_fast.installation.subprocess.run", return_value=completed
                ),
            ):
                payload = report()
        check = payload["checks"][2]
        self.assertEqual("degraded", payload["status"])
        self.assertEqual("manifest_version_missing", check["reason"])
        self.assertEqual("python", payload["resolution"]["selected_engine"])

    def test_divergent_rust_manifest_version_is_degraded_and_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "simplicio-fast-rs.exe"
            path.write_bytes(b"artifact")
            completed = type(
                "Completed",
                (),
                {
                    "returncode": 0,
                    "stdout": '{"schema":"simplicio.fast.engine-manifest/v1","engine":"rust","status":"available","version":"9.9.9"}',
                },
            )()
            with (
                patch.dict(os.environ, {"SIMPLICIO_FAST_RUST": str(path)}, clear=True),
                patch(
                    "simplicio_fast.installation.subprocess.run", return_value=completed
                ),
            ):
                payload = report()
        check = payload["checks"][2]
        self.assertEqual("degraded", payload["status"])
        self.assertEqual("manifest_version_mismatch", check["reason"])
        self.assertEqual("python", payload["resolution"]["selected_engine"])

    def test_incompatible_rust_manifest_is_degraded_and_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "simplicio-fast-rs.exe"
            path.write_bytes(b"artifact")
            completed = type(
                "Completed", (), {"returncode": 0, "stdout": '{"schema":"wrong"}'}
            )()
            with (
                patch.dict(os.environ, {"SIMPLICIO_FAST_RUST": str(path)}, clear=True),
                patch(
                    "simplicio_fast.installation.subprocess.run", return_value=completed
                ),
            ):
                payload = report()
        check = payload["checks"][2]
        self.assertEqual("degraded", payload["status"])
        self.assertEqual("fail", check["status"])
        self.assertEqual("manifest_schema_mismatch", check["reason"])
        self.assertEqual("python", payload["resolution"]["selected_engine"])
        self.assertEqual(
            "rust_artifact_unusable:manifest_schema_mismatch",
            payload["resolution"]["reason_code"],
        )

    def test_smoke_retries_windows_invalid_handle_without_inheriting_handles(
        self,
    ) -> None:
        invalid_handle = OSError("invalid handle")
        invalid_handle.winerror = 6
        completed = subprocess.CompletedProcess(
            ["python"], 0, '{"schema":"fixture"}', ""
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "simplicio_fast.installation.subprocess.run",
                side_effect=[invalid_handle, completed],
            ) as run,
        ):
            result = _smoke_step(
                ["python"],
                "python",
                ["capabilities"],
                root=Path(directory),
                environment={},
            )
        self.assertEqual("pass", result["status"])
        self.assertEqual(2, run.call_count)
        self.assertFalse(run.call_args_list[1].kwargs["close_fds"])


def test_source_and_package_versions_match() -> None:
    import tomllib

    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    project_version = pyproject["project"]["version"]
    assert project_version == __version__
