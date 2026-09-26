"""Unit tests for simplicio_mapper.query (F10 `ask`).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.query import ASK_SCHEMA, _query_cacheable_paths, run_query  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class QueryCacheablePathsWorktreeExclusionTest(unittest.TestCase):
    """Issue #234: the context-cache path enumeration must not include
    nested `.claude/worktrees/<name>/...` agent worktrees, while root
    `.claude` configuration (settings.json, skills/*.md) stays cacheable."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "src/keep.py", "x = 1\n")
        _write(self.dir, ".claude/settings.json", "{}\n")
        _write(self.dir, ".claude/skills/foo/SKILL.md", "# foo\n")
        _write(self.dir, ".claude/worktrees/worker/src.py", "print('dup')\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_excludes_worktrees_but_keeps_root_claude_config(self) -> None:
        rel_paths = set(_query_cacheable_paths(str(self.dir), ".simplicio-loop"))
        self.assertIn("src/keep.py", rel_paths)
        self.assertIn(str(Path(".claude") / "settings.json").replace("\\", "/"), {p.replace("\\", "/") for p in rel_paths})
        self.assertTrue(all(".claude/worktrees" not in p.replace("\\", "/") for p in rel_paths))


class QueryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "ask-app", "main": "src/main.py"}))
        _write(
            self.dir,
            "src/main.py",
            "from src.writer import persist\ndef main():\n    persist()\n",
        )
        _write(
            self.dir,
            "src/writer.py",
            "def persist():\n    with open('out.json', 'w') as handle:\n        handle.write('{}')\n",
        )
        _write(
            self.dir,
            "tests/test_writer.py",
            "from src.writer import persist\n\ndef test_persist():\n    persist()\n",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_callers_finds_call_site(self) -> None:
        payload = run_query(str(self.dir), verb="callers", arg="persist")
        self.assertEqual(payload["schema"], ASK_SCHEMA)
        self.assertGreaterEqual(payload["total"], 1)
        self.assertEqual(payload["results"][0]["source_file"], "src/main.py")

    def test_callees_of_main_includes_persist(self) -> None:
        payload = run_query(str(self.dir), verb="callees", arg="main")
        targets = {r["target_symbol"] for r in payload["results"]}
        self.assertTrue(any(t and "persist" in t for t in targets))

    def test_reaches_from_entry_file(self) -> None:
        payload = run_query(str(self.dir), verb="reaches", arg="src/main.py", depth=2)
        paths = {item["path"] for item in payload["results"]}
        self.assertIn("src/writer.py", paths)

    def test_impact_reports_affected_flow(self) -> None:
        payload = run_query(str(self.dir), verb="impact", arg="src/writer.py")
        self.assertIn("affected_flows", payload["results"])
        self.assertGreaterEqual(len(payload["results"]["affected_flows"]), 1)

    def test_tests_for_finds_matching_test_file(self) -> None:
        payload = run_query(str(self.dir), verb="tests-for", arg="src/writer.py")
        self.assertIn("tests/test_writer.py", payload["results"])

    def test_rules_without_business_index_notes_missing(self) -> None:
        payload = run_query(str(self.dir), verb="rules")
        self.assertEqual(payload["results"], [])
        self.assertIsNotNone(payload["note"])

    def test_unknown_verb_raises(self) -> None:
        with self.assertRaises(ValueError):
            run_query(str(self.dir), verb="bogus")

    def test_ask_command_end_to_end(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["ask", str(self.dir), "callers", "persist", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], ASK_SCHEMA)


class PrecedentVerbTest(unittest.TestCase):
    """`ask precedent` (F10 extension): native-first search over the
    simplicio runtime, falling back to local tag/summary keyword overlap
    over the in-memory precedent-index when the runtime is unavailable."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "precedent-app"}))
        # First line matches the `route` precedent pattern, so
        # _build_precedent_items produces exactly one item here whose
        # summary is "route precedent in src/api/routes.py".
        _write(self.dir, "src/api/routes.py", "router.get('/x')\ndef handler():\n    return 1\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_native_runtime_used_when_binary_on_path(self) -> None:
        native_payload = {
            "schema": "simplicio.precedent-search/v1",
            "candidates": [
                {
                    "precedent_id": "p1",
                    "score": 0.92,
                    "reuse_level": "high",
                    "suggested_next_action": "reuse as-is",
                }
            ],
        }
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(native_payload))
        with (
            mock.patch("simplicio_mapper.query.shutil.which", return_value="/usr/local/bin/simplicio"),
            mock.patch("simplicio_mapper.query._validated_runtime_binary", return_value=(True, "validated")),
            mock.patch("simplicio_mapper.query.subprocess.run", return_value=completed) as run_mock,
            mock.patch(
                "simplicio_mapper.query.build_artifacts",
                side_effect=AssertionError("should stay artifact-lazy"),
            ),
        ):
            payload = run_query(str(self.dir), verb="precedent", arg="route")

        self.assertEqual(payload["schema"], ASK_SCHEMA)
        self.assertEqual(payload["source"], "runtime-precedent-search")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["results"][0]["precedent_id"], "p1")
        self.assertEqual(payload["results"][0]["reuse_level"], "high")
        self.assertEqual(payload["cache"]["receipt"]["outcome"], "bypass")
        called_argv = run_mock.call_args[0][0]
        self.assertEqual(called_argv[0], "/usr/local/bin/simplicio")
        self.assertIn("--text", called_argv)
        self.assertIn("route", called_argv)

    def test_native_impact_success_stays_artifact_lazy(self) -> None:
        native_payload = {
            "schema": ASK_SCHEMA,
            "results": {"affected_symbols": [], "affected_flows": [], "needs_review": []},
            "total": 0,
        }
        with (
            mock.patch("simplicio_mapper.query.shutil.which", return_value="/usr/local/bin/simplicio"),
            mock.patch("simplicio_mapper.query._validated_runtime_binary", return_value=(True, "validated")),
            mock.patch(
                "simplicio_mapper.query.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(native_payload)
                ),
            ),
            mock.patch(
                "simplicio_mapper.query.build_artifacts",
                side_effect=AssertionError("should stay artifact-lazy"),
            ),
        ):
            payload = run_query(str(self.dir), verb="impact", arg="src/api/routes.py")
        self.assertEqual(payload["source"], "runtime-ask-impact")
        self.assertEqual(payload["cache"]["receipt"]["outcome"], "bypass")

    def test_native_tests_for_success_stays_artifact_lazy(self) -> None:
        native_payload = {"schema": ASK_SCHEMA, "results": ["tests/test_routes.py"], "total": 1}
        with (
            mock.patch("simplicio_mapper.query.shutil.which", return_value="/usr/local/bin/simplicio"),
            mock.patch("simplicio_mapper.query._validated_runtime_binary", return_value=(True, "validated")),
            mock.patch(
                "simplicio_mapper.query.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(native_payload)
                ),
            ),
            mock.patch(
                "simplicio_mapper.query.build_artifacts",
                side_effect=AssertionError("should stay artifact-lazy"),
            ),
        ):
            payload = run_query(str(self.dir), verb="tests-for", arg="src/api/routes.py")
        self.assertEqual(payload["source"], "runtime-ask-tests-for")
        self.assertEqual(payload["cache"]["receipt"]["outcome"], "bypass")

    def test_fallback_to_local_tag_overlap_when_binary_absent(self) -> None:
        with mock.patch("simplicio_mapper.query.shutil.which", return_value=None):
            payload = run_query(str(self.dir), verb="precedent", arg="route")

        self.assertEqual(payload["source"], "local-tag-overlap")
        self.assertGreaterEqual(payload["total"], 1)
        self.assertTrue(any("routes.py" in item.get("path", "") for item in payload["results"]))

    def test_fallback_on_subprocess_timeout(self) -> None:
        with (
            mock.patch("simplicio_mapper.query.shutil.which", return_value="/usr/local/bin/simplicio"),
            mock.patch("simplicio_mapper.query._validated_runtime_binary", return_value=(True, "validated")),
            mock.patch(
                "simplicio_mapper.query.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="simplicio", timeout=10),
            ),
        ):
            payload = run_query(str(self.dir), verb="precedent", arg="route")
        self.assertEqual(payload["source"], "local-tag-overlap")

    def test_fallback_on_malformed_json(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="not-json{")
        with (
            mock.patch("simplicio_mapper.query.shutil.which", return_value="/usr/local/bin/simplicio"),
            mock.patch("simplicio_mapper.query._validated_runtime_binary", return_value=(True, "validated")),
            mock.patch("simplicio_mapper.query.subprocess.run", return_value=completed),
        ):
            payload = run_query(str(self.dir), verb="precedent", arg="route")
        self.assertEqual(payload["source"], "local-tag-overlap")

    def test_fallback_on_wrong_precedent_schema(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"schema": "simplicio.ask/v1", "candidates": []}),
        )
        with (
            mock.patch("simplicio_mapper.query.shutil.which", return_value="/usr/local/bin/simplicio"),
            mock.patch("simplicio_mapper.query._validated_runtime_binary", return_value=(True, "validated")),
            mock.patch("simplicio_mapper.query.subprocess.run", return_value=completed),
        ):
            payload = run_query(str(self.dir), verb="precedent", arg="route")
        self.assertEqual(payload["source"], "local-tag-overlap")
        self.assertEqual(payload["delegation"]["reason"], "invalid_response_schema")

    def test_fallback_on_non_zero_exit(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with (
            mock.patch("simplicio_mapper.query.shutil.which", return_value="/usr/local/bin/simplicio"),
            mock.patch("simplicio_mapper.query._validated_runtime_binary", return_value=(True, "validated")),
            mock.patch("simplicio_mapper.query.subprocess.run", return_value=completed),
        ):
            payload = run_query(str(self.dir), verb="precedent", arg="route")
        self.assertEqual(payload["source"], "local-tag-overlap")

    def test_empty_precedent_index_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as empty_dir_name:
            empty_dir = Path(empty_dir_name)
            _write(empty_dir, "package.json", json.dumps({"name": "empty-precedent-app"}))
            _write(empty_dir, "README.md", "This project has no code yet, only plans and ideas.\n")
            with mock.patch("simplicio_mapper.query.shutil.which", return_value=None):
                payload = run_query(str(empty_dir), verb="precedent", arg="anything")
            self.assertEqual(payload["source"], "local-tag-overlap")
            self.assertEqual(payload["results"], [])
            self.assertEqual(payload["total"], 0)

    def test_local_precedent_second_identical_request_hits_persisted_cache(self) -> None:
        with mock.patch("simplicio_mapper.query.shutil.which", return_value=None):
            first = run_query(str(self.dir), verb="precedent", arg="route")
        self.assertEqual(first["cache"]["receipt"]["outcome"], "miss")
        with (
            mock.patch("simplicio_mapper.query.shutil.which", return_value=None),
            mock.patch(
                "simplicio_mapper.query.build_artifacts",
                side_effect=AssertionError("cache hit should skip artifacts"),
            ),
        ):
            second = run_query(str(self.dir), verb="precedent", arg="route")
        self.assertEqual(second["source"], "local-tag-overlap")
        self.assertEqual(second["cache"]["receipt"]["outcome"], "hit")
        self.assertTrue(second["cache"]["diagnostics"]["present"])


if __name__ == "__main__":
    unittest.main()
