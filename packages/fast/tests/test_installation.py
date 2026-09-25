from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simplicio_fast.installation import _smoke_step, report
from simplicio_fast import __version__
from simplicio_fast.installation import python_smoke


class InstallationReportTest(unittest.TestCase):
    def test_python_only_report_is_ready_without_network(self) -> None:
        payload = report()
        self.assertEqual("simplicio.fast.installation/v1", payload["schema"])
        self.assertEqual("ready", payload["status"])
        self.assertEqual("pass", payload["checks"][1]["status"])
        self.assertEqual("python", payload["resolution"]["selected_engine"])
        self.assertEqual("python_only", payload["resolution"]["reason_code"])
        self.assertFalse(payload["rollback"]["supported"])

    def test_python_cli_smoke_is_bounded(self) -> None:
        payload = python_smoke()
        failures = [
            {
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
        self.assertTrue(payload["checks"]["build_refresh_query_context_plan_delivery"])
        self.assertTrue(all(step["status"] == "pass" for step in payload["steps"]))

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
