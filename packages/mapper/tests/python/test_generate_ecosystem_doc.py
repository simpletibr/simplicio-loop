"""Tests for scripts/generate-ecosystem-doc.py (issue #156).

Loaded via importlib.util (the script file uses a hyphenated name to match
the CLI-script naming convention used elsewhere in this repo, e.g.
scripts/check-version-sync.js, so it cannot be imported with a plain
`import` statement).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "generate-ecosystem-doc.py"
DIVERGENT_FIXTURE = ROOT / "tests" / "fixtures" / "ecosystem-consumers-divergent.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_ecosystem_doc", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VersionParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def test_compare_versions_equal(self) -> None:
        self.assertEqual(self.mod.compare_versions("0.15.0", "0.15.0"), 0)

    def test_compare_versions_less_than(self) -> None:
        self.assertLess(self.mod.compare_versions("0.10.0", "0.15.0"), 0)

    def test_compare_versions_greater_than(self) -> None:
        self.assertGreater(self.mod.compare_versions("1.0.0", "0.15.0"), 0)

    def test_compare_versions_tolerates_prerelease_suffix(self) -> None:
        # A trailing `-rc1`/`+build` style suffix must not blow up parsing.
        self.assertEqual(self.mod.compare_versions("0.15.0-rc1", "0.15.0"), 0)


class DivergenceDetectionTest(unittest.TestCase):
    """Proves the detector correctly flags both directions of drift using
    tests/fixtures/ecosystem-consumers-divergent.json (issue #156 AC:
    "test/fixture covers at least one divergent-constraint case")."""

    def setUp(self) -> None:
        self.mod = _load_module()
        self.current_version = "0.15.0"
        with open(DIVERGENT_FIXTURE, encoding="utf-8") as handle:
            self.consumers = json.load(handle)["consumers"]

    def test_old_constraint_is_flagged_behind(self) -> None:
        report = self.mod.build_report(self.consumers, self.current_version)
        behind_entry = next(e for e in report if e["name"] == "simplicio-fixture-behind")
        self.assertEqual(behind_entry["status"], "behind")
        # behind is a note, not a hard failure
        self.assertNotIn(behind_entry, self.mod.divergent_consumers(report))

    def test_newer_constraint_is_flagged_ahead_and_divergent(self) -> None:
        report = self.mod.build_report(self.consumers, self.current_version)
        ahead_entry = next(e for e in report if e["name"] == "simplicio-fixture-ahead")
        self.assertEqual(ahead_entry["status"], "ahead")
        self.assertIn(ahead_entry, self.mod.divergent_consumers(report))

    def test_current_constraint_is_flagged_current(self) -> None:
        report = self.mod.build_report(
            [{"name": "x", "min_version": "0.15.0"}], self.current_version
        )
        self.assertEqual(report[0]["status"], "current")

    def test_rendered_markdown_notes_behind_consumer_without_failing(self) -> None:
        report = self.mod.build_report(self.consumers, self.current_version)
        markdown = self.mod.render_markdown(self.current_version, report, "2026-01-01T00:00:00Z")
        self.assertIn("simplicio-fixture-behind", markdown)
        self.assertIn("atrás da versão atual", markdown)

    def test_rendered_markdown_calls_out_ahead_consumer_as_divergence(self) -> None:
        report = self.mod.build_report(self.consumers, self.current_version)
        markdown = self.mod.render_markdown(self.current_version, report, "2026-01-01T00:00:00Z")
        self.assertIn("simplicio-fixture-ahead", markdown)
        self.assertIn("divergência", markdown)


class CheckModeTest(unittest.TestCase):
    """`--check` must fail on a stale doc and pass right after regeneration,
    without flapping purely because of the timestamp line."""

    def setUp(self) -> None:
        self.mod = _load_module()

    def test_check_fails_when_doc_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = _load_module()
            mod.ECOSYSTEM_DOC_PATH = os.path.join(tmp, "SIMPLICIO_ECOSYSTEM.md")
            mod.PYPROJECT_PATH = str(ROOT / "pyproject.toml")
            mod.PACKAGE_JSON_PATH = str(ROOT / "package.json")
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", dir=tmp, delete=False
            ) as consumers_file:
                consumers_file.write('{"consumers": []}')
                consumers_path = consumers_file.name
            self.assertEqual(mod.cmd_check(consumers_path), 1)

    def test_write_then_check_round_trips_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = _load_module()
            mod.ECOSYSTEM_DOC_PATH = os.path.join(tmp, "SIMPLICIO_ECOSYSTEM.md")
            mod.PYPROJECT_PATH = str(ROOT / "pyproject.toml")
            mod.PACKAGE_JSON_PATH = str(ROOT / "package.json")
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", dir=tmp, delete=False
            ) as consumers_file:
                consumers_file.write('{"consumers": [{"name": "x", "min_version": "0.1.0"}]}')
                consumers_path = consumers_file.name
            self.assertEqual(mod.cmd_write(consumers_path), 0)
            self.assertEqual(mod.cmd_check(consumers_path), 0)

    def test_check_fails_after_hand_edit_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = _load_module()
            mod.ECOSYSTEM_DOC_PATH = os.path.join(tmp, "SIMPLICIO_ECOSYSTEM.md")
            mod.PYPROJECT_PATH = str(ROOT / "pyproject.toml")
            mod.PACKAGE_JSON_PATH = str(ROOT / "package.json")
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", dir=tmp, delete=False
            ) as consumers_file:
                consumers_file.write('{"consumers": []}')
                consumers_path = consumers_file.name
            self.assertEqual(mod.cmd_write(consumers_path), 0)
            # Simulate a hand edit / drift after generation.
            with open(mod.ECOSYSTEM_DOC_PATH, "a", encoding="utf-8") as handle:
                handle.write("\nhand-edited line that should not be here\n")
            self.assertEqual(mod.cmd_check(consumers_path), 1)

    def test_check_fails_on_ahead_consumer_even_if_doc_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod = _load_module()
            mod.ECOSYSTEM_DOC_PATH = os.path.join(tmp, "SIMPLICIO_ECOSYSTEM.md")
            mod.PYPROJECT_PATH = str(ROOT / "pyproject.toml")
            mod.PACKAGE_JSON_PATH = str(ROOT / "package.json")
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", dir=tmp, delete=False
            ) as consumers_file:
                consumers_file.write(
                    json.dumps({"consumers": [{"name": "x", "min_version": "999.0.0"}]})
                )
                consumers_path = consumers_file.name
            # cmd_write itself must report failure for an ahead consumer...
            self.assertEqual(mod.cmd_write(consumers_path), 1)
            # ...and --check must also fail even though the doc it just wrote
            # matches (the divergence, not just staleness, is the failure).
            self.assertEqual(mod.cmd_check(consumers_path), 1)


if __name__ == "__main__":
    unittest.main()
