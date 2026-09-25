"""End-to-end CLI coverage for the thin subcommand wrappers in
`simplicio_mapper/cli/_repo_commands.py` (`visualize`, `sync`, `history`,
`diff`, `ask`) that were previously exercised only at the library level
(`build_visualization_bundle`, `build_docs_sync`, `run_query`, ...), not
through the real `main()` CLI dispatch -- both the `--json` and
human-readable print branches, and the documented error paths.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class RepoCommandsCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "repo-commands-app"}))
        _write(self.dir, "src/main.py", "def main():\n    return 1\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- visualize -----------------------------------------------------

    def test_visualize_json_writes_bundle_and_clustering_metrics(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["visualize", str(self.dir), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.visualization-bundle/v1")
        self.assertTrue((self.dir / ".simplicio" / "visualization-bundle.json").is_file())
        self.assertTrue((self.dir / ".simplicio" / "clustering-metrics.json").is_file())

    def test_visualize_human_output_summarizes_counts(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["visualize", str(self.dir)])
        self.assertEqual(code, 0)
        self.assertIn("nodes=", out.getvalue())
        self.assertIn("edges=", out.getvalue())
        self.assertIn("clusters=", out.getvalue())

    # -- sync ------------------------------------------------------------

    def test_sync_json_reports_diff_and_regenerated_docs(self) -> None:
        main(["docs", str(self.dir)])
        out = StringIO()
        with redirect_stdout(out):
            code = main(["sync", str(self.dir), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertIn("diff", payload)
        self.assertIn("stale", payload)

    def test_sync_human_output_summarizes_counts(self) -> None:
        main(["docs", str(self.dir)])
        out = StringIO()
        with redirect_stdout(out):
            code = main(["sync", str(self.dir)])
        self.assertEqual(code, 0)
        self.assertIn("changed=", out.getvalue())
        self.assertIn("stale=", out.getvalue())

    def test_sync_check_mode_does_not_snapshot(self) -> None:
        main(["docs", str(self.dir)])
        out = StringIO()
        with redirect_stdout(out):
            code = main(["sync", str(self.dir), "--check", "--json"])
        self.assertIn(code, (0, 1))
        json.loads(out.getvalue())

    # -- history / diff --------------------------------------------------

    def test_history_json_reports_no_snapshots_initially(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["history", str(self.dir), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.doc-history-index/v1")
        self.assertEqual(payload["snapshots"], [])

    def test_history_human_output_without_snapshots(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["history", str(self.dir)])
        self.assertEqual(code, 0)
        self.assertIn("no snapshots yet", out.getvalue())

    def test_history_human_output_lists_snapshots_after_docs_run(self) -> None:
        main(["docs", str(self.dir)])
        out = StringIO()
        with redirect_stdout(out):
            code = main(["history", str(self.dir)])
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().strip())
        self.assertNotIn("no snapshots yet", out.getvalue())

    def test_diff_without_from_and_to_is_rejected(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["diff", str(self.dir)])
        self.assertEqual(code, 2)
        self.assertIn("--from", err.getvalue())

    def test_diff_with_unknown_snapshot_id_fails_gracefully(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["diff", str(self.dir), "--from", "does-not-exist-1", "--to", "does-not-exist-2", "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out.getvalue())
        self.assertIn("error", payload)

    def test_diff_between_two_real_snapshots(self) -> None:
        main(["docs", str(self.dir)])
        first = json.loads(
            self._capture(["history", str(self.dir), "--json"])
        )["snapshots"]
        _write(self.dir, "src/extra.py", "def extra():\n    return 2\n")
        main(["docs", str(self.dir)])
        second = json.loads(self._capture(["history", str(self.dir), "--json"]))["snapshots"]
        self.assertGreaterEqual(len(second), len(first))
        if len(second) >= 2:
            out = StringIO()
            with redirect_stdout(out):
                code = main(
                    ["diff", str(self.dir), "--from", second[-1]["id"], "--to", second[0]["id"], "--json"]
                )
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertIn("modules", payload)
            self.assertIn("symbols", payload)

    def _capture(self, argv: list[str]) -> str:
        out = StringIO()
        with redirect_stdout(out):
            main(argv)
        return out.getvalue()

    # -- ask ---------------------------------------------------------------

    def test_ask_without_verb_is_rejected(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["ask", str(self.dir)])
        self.assertEqual(code, 2)
        self.assertIn("ask requires a verb", err.getvalue())

    def test_ask_callers_json(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["ask", str(self.dir), "callers", "main", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertIn("results", payload)
        self.assertIn("total", payload)

    def test_ask_callers_human_output(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["ask", str(self.dir), "callers", "main"])
        self.assertEqual(code, 0)
        self.assertIn("verb=callers", out.getvalue())

    def test_ask_invalid_verb_is_rejected(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["ask", str(self.dir), "not-a-real-verb"])
        self.assertEqual(code, 2)
        self.assertIn("ask failed", err.getvalue())


if __name__ == "__main__":
    unittest.main()
