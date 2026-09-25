"""Coverage for `simplicio_mapper/cli/_args.py`'s argv-validation error
paths (`--<flag> requires a value` / `Invalid --<flag> value`), driven
through the real `main()` CLI entry point. Each of these branches
`sys.exit(2)`s with a specific stderr message; they were previously
untested because every other CLI test only ever passes well-formed argv.
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main


class ArgsValidationCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _expect_exit_2(self, argv: list[str], expected_message_fragment: str) -> None:
        # `_args.py`'s validation branches call `sys.exit(2)` directly
        # (argparse-style), which raises `SystemExit` through `main()`
        # rather than returning an int -- unlike the rest of the CLI's
        # `return <code>` error paths.
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            main(argv)
        self.assertEqual(ctx.exception.code, 2, err.getvalue())
        self.assertIn(expected_message_fragment, err.getvalue())

    def test_minimum_query_coverage_out_of_range_is_rejected(self) -> None:
        self._expect_exit_2(
            ["orient", str(self.dir), "--minimum-query-coverage", "1.5"],
            "--minimum-query-coverage requires a number between 0 and 1",
        )

    def test_minimum_query_coverage_non_numeric_is_rejected(self) -> None:
        self._expect_exit_2(
            ["orient", str(self.dir), "--minimum-query-coverage", "not-a-number"],
            "--minimum-query-coverage requires a number between 0 and 1",
        )

    def test_token_budget_zero_is_rejected(self) -> None:
        self._expect_exit_2(
            ["orient", str(self.dir), "--token-budget", "0"],
            "--token-budget requires a positive integer",
        )

    def test_token_budget_non_numeric_is_rejected(self) -> None:
        self._expect_exit_2(
            ["orient", str(self.dir), "--token-budget", "abc"],
            "--token-budget requires a positive integer",
        )

    def test_depth_non_numeric_is_rejected(self) -> None:
        self._expect_exit_2(["ask", str(self.dir), "reaches", "x", "--depth", "abc"], "Invalid --depth value")

    def test_limit_non_numeric_is_rejected(self) -> None:
        self._expect_exit_2(["ask", str(self.dir), "callers", "x", "--limit", "abc"], "Invalid --limit value")

    def test_drift_threshold_non_numeric_is_rejected(self) -> None:
        self._expect_exit_2(["drift", str(self.dir), "--threshold", "abc"], "Invalid --threshold value")

    def test_drift_scope_invalid_value_is_rejected(self) -> None:
        self._expect_exit_2(
            ["drift", str(self.dir), "--scope", "not-a-real-scope"],
            "--scope requires all, product, or template",
        )

    def test_retention_non_numeric_is_rejected(self) -> None:
        self._expect_exit_2(["sync", str(self.dir), "--retention", "abc"], "Invalid --retention value")

    def test_background_timeout_non_numeric_is_rejected(self) -> None:
        self._expect_exit_2(
            ["index", str(self.dir), "--background", "--timeout", "abc"],
            "Invalid --timeout value",
        )

    def test_for_llm_unknown_format_is_rejected(self) -> None:
        self._expect_exit_2(
            ["orient", str(self.dir), "--for-llm", "not-a-real-format"],
            "Unknown --for-llm format",
        )

    def test_for_llm_missing_value_is_rejected(self) -> None:
        self._expect_exit_2(["orient", str(self.dir), "--for-llm"], "--for-llm requires a value")

    def test_confidence_unknown_tag_is_rejected(self) -> None:
        self._expect_exit_2(
            ["index", str(self.dir), "--confidence", "not-a-real-tag"],
            "Unknown --confidence tag",
        )

    def test_confidence_missing_value_is_rejected(self) -> None:
        self._expect_exit_2(["index", str(self.dir), "--confidence"], "--confidence requires a value")

    def test_goal_missing_value_is_rejected(self) -> None:
        self._expect_exit_2(["orient", str(self.dir), "--goal"], "--goal requires a value")

    def test_task_file_missing_value_is_rejected(self) -> None:
        self._expect_exit_2(["orient", str(self.dir), "--task-file"], "--task-file requires a value")


if __name__ == "__main__":
    unittest.main()
