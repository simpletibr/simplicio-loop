"""Tests for scripts/regen_contract_fixtures.py (issue #157).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import importlib.util
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "regen_contract_fixtures.py"


def _load_module():
    # scripts/regen_contract_fixtures.py itself inserts ROOT onto sys.path
    # and imports simplicio_mapper.contract at module scope, so it must be
    # importable the normal way, not just via file location — but since the
    # filename has underscores (unlike generate-ecosystem-doc.py) a plain
    # spec_from_file_location + exec still works fine here.
    spec = importlib.util.spec_from_file_location("regen_contract_fixtures", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NormalizeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def test_normalizes_source_dir_occurrences(self) -> None:
        payload = {"root": "/abs/fixture/source", "files": [{"path": "src/app.py"}]}
        normalized = self.mod._normalize(payload, "/abs/fixture/source")
        self.assertEqual(normalized["root"], self.mod.NORMALIZED_ROOT_PLACEHOLDER)
        # Relative paths untouched.
        self.assertEqual(normalized["files"][0]["path"], "src/app.py")

    def test_normalizes_out_dir_occurrences_distinctly_from_source_dir(self) -> None:
        payload = {"paths": {"project_map": "/abs/tmp-out/project-map.json"}}
        normalized = self.mod._normalize(payload, "/abs/fixture/source", "/abs/tmp-out")
        self.assertEqual(
            normalized["paths"]["project_map"],
            f"{self.mod.NORMALIZED_ROOT_PLACEHOLDER}/.simplicio-loop/project-map.json",
        )

    def test_pins_generated_at_regardless_of_value(self) -> None:
        payload = {
            "generated_at": "2099-01-01T00:00:00Z",
            "files": [{"last_modified": "2099-01-01T00:00:00Z"}],
        }
        normalized = self.mod._normalize(payload, "/abs/fixture/source")
        self.assertEqual(normalized["generated_at"], self.mod.NORMALIZED_TIMESTAMP)
        self.assertEqual(
            normalized["files"][0]["last_modified"],
            self.mod.NORMALIZED_LAST_MODIFIED,
        )

    def test_recurses_into_nested_lists_and_dicts(self) -> None:
        payload = {"a": [{"b": {"root": "/abs/fixture/source/x"}}]}
        normalized = self.mod._normalize(payload, "/abs/fixture/source")
        self.assertEqual(
            normalized["a"][0]["b"]["root"], f"{self.mod.NORMALIZED_ROOT_PLACEHOLDER}/x"
        )


class CheckCommandTest(unittest.TestCase):
    """End-to-end: runs the real mapper CLI against the committed fixture
    source repos and validates the fresh output. This is the same command
    CI runs (python-ci.yml, issue #156/#157 checks)."""

    def test_check_passes_against_committed_fixture_sources(self) -> None:
        mod = _load_module()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = mod.cmd_check()
        output = buffer.getvalue()
        self.assertEqual(code, 0, output)
        self.assertIn("contract check OK", output)

    def test_check_rejects_golden_fixture_drift(self) -> None:
        mod = _load_module()
        expected_path = (
            ROOT / "simplicio_mapper" / "contracts"
            / "mapper-artifacts"
            / "v1"
            / "fixtures"
            / "python-minimal"
            / "artifacts"
            / "project-map.json"
        ).resolve()
        original = mod._read_json

        def tampered_read(path: str) -> dict:
            value = original(path)
            if Path(path).resolve() == expected_path:
                value = dict(value)
                value["version"] = value["version"] + 1
            return value

        errors = StringIO()
        with patch.object(mod, "_read_json", side_effect=tampered_read):
            with redirect_stderr(errors):
                code = mod.cmd_check()
        self.assertEqual(code, 1)
        self.assertIn("golden fixture drift", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
