"""End-to-end CLI coverage for `simplicio-mapper snapshot [build|summary|validate|dag]`
(`simplicio_mapper/cli/_snapshot.py`) -- issue #208 Step 1's observer surface.

Unlike `tests/python/test_context_snapshot.py` (library-level unit tests for
`build_context_snapshot`), this drives the real CLI entry point (`main()`)
end to end against a scratch repo, exactly as a user invoking
`simplicio-mapper snapshot ...` would, closing a full-CLI-dispatch coverage
gap (`cli/_snapshot.py` was previously untested end to end).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path

from simplicio_mapper.cli import main


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class SnapshotCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _write(self.root, "package.json", json.dumps({"name": "snapshot-cli-app"}))
        _write(self.root, "src/main.py", "def main():\n    return 1\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_writes_snapshot_and_prints_human_summary(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["snapshot", "build", "--root", str(self.root)])
        self.assertEqual(code, 0)
        dest = self.root / ".simplicio" / "context-snapshot.json"
        self.assertTrue(dest.is_file())
        snapshot = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["schema"], "simplicio.context-snapshot/v1")
        self.assertIn("snapshot", out.getvalue())
        self.assertIn("wrote", out.getvalue())

    def test_build_json_emits_full_snapshot_on_stdout(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["snapshot", "build", "--root", str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.context-snapshot/v1")

    def test_default_argv_with_no_subcommand_builds(self) -> None:
        # `run_snapshot_cli([])` (bare `simplicio-mapper snapshot`) defaults
        # to `build` against the current working directory.
        import os

        cwd = os.getcwd()
        try:
            os.chdir(self.root)
            out = StringIO()
            with redirect_stdout(out):
                code = main(["snapshot"])
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 0)
        self.assertTrue((self.root / ".simplicio" / "context-snapshot.json").is_file())

    def test_summary_without_prior_build_fails_with_guidance(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["snapshot", "summary", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("snapshot build", err.getvalue())

    def test_summary_after_build_reprints_same_snapshot_id(self) -> None:
        main(["snapshot", "build", "--root", str(self.root)])
        out = StringIO()
        with redirect_stdout(out):
            code = main(["snapshot", "summary", "--root", str(self.root)])
        self.assertEqual(code, 0)
        dest = self.root / ".simplicio" / "context-snapshot.json"
        snapshot = json.loads(dest.read_text(encoding="utf-8"))
        self.assertIn(snapshot["snapshot_id"][:16], out.getvalue())

    def test_validate_reports_ok_for_a_real_snapshot(self) -> None:
        main(["snapshot", "build", "--root", str(self.root)])
        dest = self.root / ".simplicio" / "context-snapshot.json"
        out = StringIO()
        with redirect_stdout(out):
            code = main(["snapshot", "validate", str(dest)])
        self.assertEqual(code, 0)
        self.assertIn("[ok]", out.getvalue())

    def test_validate_reports_fail_for_a_broken_snapshot(self) -> None:
        main(["snapshot", "build", "--root", str(self.root)])
        dest = self.root / ".simplicio" / "context-snapshot.json"
        snapshot = json.loads(dest.read_text(encoding="utf-8"))
        del snapshot["snapshot_id"]
        dest.write_text(json.dumps(snapshot), encoding="utf-8")
        out = StringIO()
        with redirect_stdout(out):
            code = main(["snapshot", "validate", str(dest)])
        self.assertEqual(code, 1)
        self.assertIn("[fail]", out.getvalue())

    def test_validate_without_paths_prints_usage_and_fails(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["snapshot", "validate", "--root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("usage", err.getvalue())

    def test_dag_build_writes_context_dag_and_journal(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["snapshot", "dag", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / ".simplicio" / "context-dag.json").is_file())
        self.assertTrue((self.root / ".simplicio" / "context-dag-journal.jsonl").is_file())

    def test_dag_build_json_emits_journal_entry(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["snapshot", "dag", "--root", str(self.root), "--json"])
        self.assertEqual(code, 0)
        entry = json.loads(out.getvalue())
        self.assertEqual(entry["schema"], "simplicio.context-dag-journal/v1")
        self.assertIn("dag_id", entry)

    def test_help_flag_prints_usage_without_side_effects(self) -> None:
        # A bare `snapshot --help` (dash-prefixed first token) is caught by
        # the *top-level* arg parser's generic `-h`/`--help` handling before
        # ever reaching `_snapshot.py` (the top-level parser only hands off
        # to `run_snapshot_cli` once it sees a non-dash first token -- see
        # `_args.py`'s `command == "snapshot" and not arg.startswith("-")`
        # break condition). Exercise `_snapshot.py`'s own `--help` branch via
        # `snapshot build --help`, which does break through correctly.
        out = StringIO()
        with redirect_stdout(out):
            code = main(["snapshot", "build", "--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage", out.getvalue())
        self.assertFalse((self.root / ".simplicio").exists())

    def test_unknown_option_is_rejected(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["snapshot", "build", "--root", str(self.root), "--not-a-real-flag"])
        self.assertEqual(code, 2)
        self.assertIn("unknown snapshot option", err.getvalue())

    def test_refresh_forces_a_full_rescan(self) -> None:
        main(["snapshot", "build", "--root", str(self.root)])
        _write(self.root, "src/extra.py", "def extra():\n    return 2\n")
        out = StringIO()
        with redirect_stdout(out):
            code = main(["snapshot", "build", "--root", str(self.root), "--refresh", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.context-snapshot/v1")
        project_map = json.loads((self.root / ".simplicio" / "project-map.json").read_text(encoding="utf-8"))
        self.assertTrue(any(f["path"] == "src/extra.py" for f in project_map["files"]))


if __name__ == "__main__":
    unittest.main()
