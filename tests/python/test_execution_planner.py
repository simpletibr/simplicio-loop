"""Tests for issue #325 default-async planning and rollback controls."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper import emit as emit_module  # noqa: E402
from simplicio_mapper.mapper.emit import build_artifacts, write_mapping_artifacts  # noqa: E402
from simplicio_mapper.mapper.execution_planner import (  # noqa: E402
    ASYNC_KILL_SWITCH_ENV,
    EXECUTION_PROFILE_ENV,
    ExecutionProfile,
    plan_execution,
)


def _make_tree(root: Path, count: int) -> None:
    for i in range(count):
        target = root / f"mod_{i}.py"
        target.write_text(f"def f_{i}():\n    return {i}\n", encoding="utf-8")


class ExecutionPlannerUnitTest(unittest.TestCase):
    def test_auto_selects_async_below_threshold_with_reason(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            plan = plan_execution(file_count=4, threshold=5)
        self.assertEqual(plan.selected_profile, ExecutionProfile.ASYNC.value)
        self.assertIn("bounded async pipeline", plan.reason)

    def test_auto_selects_async_at_threshold_with_reason(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            plan = plan_execution(file_count=5, threshold=5)
        self.assertEqual(plan.selected_profile, ExecutionProfile.ASYNC.value)
        self.assertIn("bounded async pipeline", plan.reason)

    def test_explicit_sync_overrides_auto(self) -> None:
        with mock.patch.dict(os.environ, {EXECUTION_PROFILE_ENV: "sync"}, clear=True):
            plan = plan_execution(file_count=999, threshold=5)
        self.assertEqual(plan.selected_profile, "sync")
        self.assertEqual(plan.source, "env")

    def test_async_kill_switch_wins_over_explicit_async(self) -> None:
        with mock.patch.dict(
            os.environ,
            {EXECUTION_PROFILE_ENV: "async", ASYNC_KILL_SWITCH_ENV: "1"},
            clear=True,
        ):
            plan = plan_execution(file_count=999, threshold=5)
        self.assertEqual(plan.selected_profile, "sync")
        self.assertTrue(plan.async_disabled)
        self.assertEqual(plan.source, "kill-switch")

    def test_reserved_future_profile_falls_back_deterministically(self) -> None:
        with mock.patch.dict(os.environ, {EXECUTION_PROFILE_ENV: "hub"}, clear=True):
            plan = plan_execution(file_count=1, threshold=5)
        self.assertEqual(plan.requested_profile, "hub")
        self.assertEqual(plan.selected_profile, "async")
        self.assertEqual(plan.source, "fallback")

    def test_unknown_profile_value_falls_back_to_auto(self) -> None:
        with mock.patch.dict(os.environ, {EXECUTION_PROFILE_ENV: "not-a-real-profile"}, clear=True):
            plan = plan_execution(file_count=999, threshold=5)
        self.assertEqual(plan.requested_profile, ExecutionProfile.AUTO.value)
        self.assertEqual(plan.selected_profile, ExecutionProfile.ASYNC.value)
        self.assertEqual(plan.source, "env")


class ExecutionPlannerIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_build_artifacts_publishes_route_receipt(self) -> None:
        _make_tree(self.root, 2)
        with mock.patch.dict(os.environ, {EXECUTION_PROFILE_ENV: "sync"}, clear=True):
            artifacts = build_artifacts(str(self.root))
        receipt = artifacts["execution_plan"]
        self.assertEqual(receipt["schema"], "simplicio.execution-plan/v1")
        self.assertEqual(receipt["requested_profile"], "sync")
        self.assertEqual(receipt["selected_profile"], "sync")
        self.assertIn("reason", receipt)

    def test_write_mapping_artifacts_publishes_execution_plan_file(self) -> None:
        _make_tree(self.root, 2)
        with mock.patch.dict(os.environ, {EXECUTION_PROFILE_ENV: "sync"}, clear=True):
            result = write_mapping_artifacts(str(self.root))
        path = Path(result["execution_plan_path"])
        self.assertTrue(path.exists())
        self.assertEqual(result["execution_plan"]["selected_profile"], "sync")

    def test_kill_switch_routes_large_tree_to_sync(self) -> None:
        _make_tree(self.root, 6)
        with mock.patch.dict(
            os.environ,
            {
                "SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "5",
                ASYNC_KILL_SWITCH_ENV: "true",
            },
            clear=True,
        ), mock.patch.object(
            emit_module, "_build_artifacts_sync", wraps=emit_module._build_artifacts_sync
        ) as spy_sync:
            artifacts = build_artifacts(str(self.root))
        spy_sync.assert_called_once()
        self.assertTrue(artifacts["execution_plan"]["async_disabled"])


class ExecutionPlannerSystemTest(unittest.TestCase):
    """Exercise profile selection through the real Python CLI process."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _make_tree(self.root, 2)

    def _run_index(self, extra_env: dict[str, str] | None = None) -> dict:
        env = os.environ.copy()
        env.pop(EXECUTION_PROFILE_ENV, None)
        env.pop(ASYNC_KILL_SWITCH_ENV, None)
        env["PYTHONPATH"] = str(ROOT)
        env.update(extra_env or {})
        completed = subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.cli", "index", str(self.root), "--json"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_real_cli_defaults_to_async_and_writes_receipt(self) -> None:
        payload = self._run_index()

        self.assertEqual(payload["execution_plan"]["selected_profile"], "async")
        receipt_path = Path(payload["paths"]["execution_plan"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema"], "simplicio.execution-plan/v1")
        self.assertEqual(receipt["selected_profile"], "async")
        self.assertEqual(receipt["source"], "auto")

    def test_real_cli_kill_switch_forces_sync_rollback(self) -> None:
        payload = self._run_index({ASYNC_KILL_SWITCH_ENV: "1"})

        receipt = payload["execution_plan"]
        self.assertEqual(receipt["selected_profile"], "sync")
        self.assertTrue(receipt["async_disabled"])
        self.assertEqual(receipt["source"], "kill-switch")


if __name__ == "__main__":
    unittest.main()
