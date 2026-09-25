from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from simplicio_fast.processor import ProjectProcessor

from scripts.qlt001_operational_flow import (
    DEFAULT_FIXTURE,
    QLT001_SYMBOL,
    QLT001_TARGET,
    QLT001_TASK,
    SIBLING_QUALITY,
    evaluate,
    main,
)

FAST_ROOT = Path(__file__).resolve().parents[1]


class Qlt001InprocessFlowTest(unittest.TestCase):
    def test_fixture_ingest_understand_and_plan(self) -> None:
        report = evaluate(DEFAULT_FIXTURE, mode="inprocess")
        self.assertEqual("pass", report["status"], report)
        self.assertEqual("simplicio.fast.qlt001-operational-flow/v1", report["schema"])
        names = [step["name"] for step in report["steps"]]
        self.assertEqual(
            ["inprocess_ingest", "inprocess_understand", "inprocess_plan"],
            names,
        )
        understand = report["steps"][1]
        self.assertIn(QLT001_TARGET, understand["files"])
        self.assertIn(QLT001_SYMBOL, understand["symbols"])

    def test_unknown_symbol_query_stays_empty(self) -> None:
        snapshot = DEFAULT_FIXTURE / ".simplicio" / "fast" / "project.sfast"
        processor = ProjectProcessor(DEFAULT_FIXTURE, snapshot)
        processor.ingest()
        from simplicio_fast.cli import main as cli_main
        import contextlib
        import io

        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            mock.patch.object(
                sys,
                "argv",
                [
                    "simplicio-fast",
                    "query",
                    "__no_such_symbol_qlt001__",
                    "-s",
                    str(snapshot),
                    "--json",
                ],
            ),
        ):
            code = cli_main()
        self.assertIn(code, (0, None))
        payload = json.loads(output.getvalue())
        self.assertEqual("simplicio.fast.query/v1", payload["schema"])
        self.assertEqual([], payload["matches"])

    def test_missing_snapshot_doctor_is_not_ready(self) -> None:
        from simplicio_fast.cli import main as cli_main
        import contextlib
        import io

        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            mock.patch.object(
                sys,
                "argv",
                [
                    "simplicio-fast",
                    "doctor",
                    "--json",
                    "-s",
                    str(DEFAULT_FIXTURE / "missing.sfast"),
                ],
            ),
            self.assertRaises(SystemExit) as caught,
        ):
            cli_main()
        self.assertEqual(1, int(caught.exception.code))
        payload = json.loads(output.getvalue())
        self.assertFalse(payload.get("ready"))
        self.assertEqual("simplicio.fast.doctor/v1", payload["schema"])

    def test_script_main_inprocess_exits_zero(self) -> None:
        code = main(["--mode", "inprocess", "--repo", str(DEFAULT_FIXTURE)])
        self.assertEqual(0, code)


class Qlt001LiveQualityFlowTest(unittest.TestCase):
    def test_live_mapper_and_fast_on_quality_issue_repo(self) -> None:
        repo = (
            Path(os.environ["SIMPLICIO_QLT001_REPO"])
            if os.environ.get("SIMPLICIO_QLT001_REPO")
            else SIBLING_QUALITY
        )
        if not (repo / "src" / "simplicio_loop_quality" / "loop_invoker.py").is_file():
            self.skipTest("simplicio-loop-quality sibling is not checked out")
        report = evaluate(repo, mode="live")
        self.assertEqual("pass", report["status"], json.dumps(report, indent=2)[:4000])
        required = {
            "mapper_handoff",
            "fast_ingest",
            "fast_doctor",
            "fast_understand",
            "fast_plan",
            "fast_query",
            "fast_context",
            "fast_impact",
            "fast_query_unknown_empty",
            "fast_ingest_idempotent",
            "fast_doctor_missing_snapshot_fails_closed",
        }
        names = {step["name"] for step in report["steps"]}
        self.assertTrue(required.issubset(names), names)
        understand = next(
            step for step in report["steps"] if step["name"] == "fast_understand"
        )
        self.assertIn(QLT001_TARGET, understand["files"])
        self.assertIn(QLT001_SYMBOL, understand["symbols"])
        self.assertIn("architecture", QLT001_TASK)
