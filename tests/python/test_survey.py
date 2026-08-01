"""Unit tests for simplicio_mapper.survey (F1 onboarding survey).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.business import build_business_rules  # noqa: E402
from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.flows import build_flow_inventory  # noqa: E402
from simplicio_mapper.mapper import build_artifacts  # noqa: E402
from simplicio_mapper.survey import ONBOARDING_SCHEMA, build_survey, render_survey_markdown  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class SurveyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _app(self) -> Path:
        app_dir = self.dir / "app"
        _write(app_dir, "package.json", json.dumps({
            "name": "survey-app",
            "main": "src/main.py",
            "scripts": {"test": "pytest", "lint": "ruff check ."},
        }))
        _write(
            app_dir,
            "src/main.py",
            "from src.core import run\n"
            "def main():\n"
            "    run()\n",
        )
        _write(
            app_dir,
            "src/core.py",
            "def run():\n"
            "    with open('out.txt', 'w') as handle:\n"
            "        handle.write('done')\n",
        )
        _write(app_dir, "tests/test_core.py", "def test_run():\n    pass\n")
        _write(app_dir, "CONTRIBUTING.md", "# Contributing\n")
        return app_dir

    def _build(self, app_dir: Path) -> dict:
        artifacts = build_artifacts(str(app_dir))
        flow_inventory = build_flow_inventory(str(app_dir), artifacts)
        business_rules = build_business_rules(str(app_dir), artifacts)
        return build_survey(str(app_dir), artifacts, flow_inventory, business_rules)

    def test_survey_reports_project_and_run_commands(self) -> None:
        app_dir = self._app()
        survey = self._build(app_dir)
        self.assertEqual(survey["schema"], ONBOARDING_SCHEMA)
        self.assertEqual(survey["project"]["name"], "survey-app")
        commands = {c["command"] for c in survey["run_commands"]}
        self.assertIn("npm run test", commands)
        self.assertIn("npm run lint", commands)

    def test_reading_order_starts_with_entry_point(self) -> None:
        app_dir = self._app()
        survey = self._build(app_dir)
        self.assertTrue(survey["reading_order"])
        self.assertEqual(survey["reading_order"][0]["path"], "src/main.py")

    def test_help_sources_detects_contributing_doc(self) -> None:
        app_dir = self._app()
        survey = self._build(app_dir)
        paths = {item["path"] for item in survey["help_sources"]}
        self.assertIn("CONTRIBUTING.md", paths)

    def test_empty_repo_reports_nothing_detected_explicitly(self) -> None:
        app_dir = self.dir / "empty-app"
        _write(app_dir, "package.json", json.dumps({"name": "empty-app"}))
        survey = self._build(app_dir)
        self.assertEqual(survey["run_commands"], [])
        self.assertEqual(survey["top_flows"], [])
        markdown = render_survey_markdown(survey)
        self.assertIn("Nothing detected", markdown)

    def test_markdown_has_all_eight_sections(self) -> None:
        app_dir = self._app()
        survey = self._build(app_dir)
        markdown = render_survey_markdown(survey)
        for heading in [
            "## 1. What is this project",
            "## 2. How to run it",
            "## 3. Mental map",
            "## 4. Suggested reading order",
            "## 5. Main flows",
            "## 6. Business rules & glossary",
            "## 7. Observed conventions",
            "## 8. Where to ask for help",
        ]:
            self.assertIn(heading, markdown)

    def test_survey_command_writes_doc(self) -> None:
        app_dir = self._app()
        out = StringIO()
        with redirect_stdout(out):
            code = main(["survey", str(app_dir), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], ONBOARDING_SCHEMA)
        self.assertTrue((app_dir / ".simplicio" / "docs" / "onboarding.md").exists())

    def test_survey_command_target_copies_to_root(self) -> None:
        app_dir = self._app()
        code = main(["survey", str(app_dir), "--target", "ONBOARDING.md"])
        self.assertEqual(code, 0)
        self.assertTrue((app_dir / "ONBOARDING.md").exists())


    def test_survey_command_rejects_existing_target_without_clobbering(self) -> None:
        app_dir = self._app()
        target = app_dir / "scripts" / "release.py"
        original = b"print('keep me')\n"
        target.parent.mkdir(parents=True)
        target.write_bytes(original)
        code = main(["survey", str(app_dir), "--target", "scripts/release.py"])
        self.assertEqual(code, 2)
        self.assertEqual(target.read_bytes(), original)

    def test_survey_command_rejects_target_created_after_precheck(self) -> None:
        app_dir = self._app()
        target = app_dir / "scripts" / "release.py"
        original = b"print('race winner')\n"
        real_exists = os.path.exists

        def create_after_precheck(path):
            if os.path.abspath(path) == str(target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original)
                return False
            return real_exists(path)

        with patch("simplicio_mapper.cli._repo_commands.os.path.exists", side_effect=create_after_precheck):
            code = main(["survey", str(app_dir), "--target", "scripts/release.py"])
        self.assertEqual(code, 2)
        self.assertEqual(target.read_bytes(), original)

if __name__ == "__main__":
    unittest.main()
