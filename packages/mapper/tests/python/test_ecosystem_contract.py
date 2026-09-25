"""Tests for simplicio_mapper/ecosystem_contract.py + the `doctor --contracts`
CLI subcommand (issue #164, ecosystem contract harness), plus the standalone
scripts/validate_ecosystem_contracts.py.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.contract import ContractError  # noqa: E402
from simplicio_mapper.ecosystem_contract import (  # noqa: E402
    find_ecosystem_contract_root,
    load_schema,
    validate_file,
    validate_payload,
)

ECOSYSTEM_ROOT = str(ROOT / "simplicio_mapper" / "contracts" / "ecosystem" / "v1")
FIXTURES_ROOT = os.path.join(ECOSYSTEM_ROOT, "fixtures")
STANDALONE_SCRIPT = ROOT / "scripts" / "validate_ecosystem_contracts.py"


class EcosystemContractRootAndSchemaTest(unittest.TestCase):
    def test_find_ecosystem_contract_root_from_repo_root(self) -> None:
        found = find_ecosystem_contract_root(str(ROOT))
        self.assertEqual(os.path.normpath(found), os.path.normpath(ECOSYSTEM_ROOT))

    def test_find_ecosystem_contract_root_from_nested_cwd(self) -> None:
        found = find_ecosystem_contract_root(str(ROOT / "simplicio_mapper"))
        self.assertEqual(os.path.normpath(found), os.path.normpath(ECOSYSTEM_ROOT))

    def test_load_schema_unknown_id_raises(self) -> None:
        with self.assertRaises(ContractError):
            load_schema("simplicio.does-not-exist/v1", ECOSYSTEM_ROOT)

    def test_both_schemas_load(self) -> None:
        for schema_id in ("simplicio.loop-execution/v1", "simplicio.executor-contract/v1"):
            schema = load_schema(schema_id, ECOSYSTEM_ROOT)
            self.assertEqual(schema.get("title"), schema_id)


class RealFixtureValidationTest(unittest.TestCase):
    """Every committed ecosystem fixture must validate cleanly against its
    own schema -- mirrors test_contract.py's RealFixtureValidationTest."""

    def test_all_task_fixtures_validate(self) -> None:
        for fixture_name in ("python-task", "node-task", "mixed-task"):
            fixture_dir = os.path.join(FIXTURES_ROOT, fixture_name)
            self.assertTrue(os.path.isdir(fixture_dir), fixture_dir)
            for filename in ("execution.json", "executor.json"):
                path = os.path.join(fixture_dir, filename)
                with self.subTest(fixture=fixture_name, file=filename):
                    schema_id, errors = validate_file(path, ECOSYSTEM_ROOT)
                    self.assertEqual(errors, [], f"{path} ({schema_id}): {errors}")

    def test_at_least_three_fixtures_cover_python_node_mixed(self) -> None:
        # Issue #164 AC: ">=3 minimal fixtures (Python, Node, mixed)".
        for fixture_name in ("python-task", "node-task", "mixed-task"):
            path = os.path.join(FIXTURES_ROOT, fixture_name, "execution.json")
            self.assertTrue(os.path.isfile(path), path)


class TamperedFixtureDetectionTest(unittest.TestCase):
    """Proves the ecosystem validator actually fails on real drift with an
    actionable message, not just passes by construction."""

    def test_missing_required_property_is_rejected_with_actionable_message(self) -> None:
        path = os.path.join(FIXTURES_ROOT, "python-task", "executor.json")
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        del payload["verified"]
        _, errors = validate_payload(payload, ECOSYSTEM_ROOT)
        self.assertTrue(errors)
        self.assertTrue(any("verified" in e and "required" in e for e in errors))

    def test_wrong_enum_value_is_rejected(self) -> None:
        path = os.path.join(FIXTURES_ROOT, "node-task", "execution.json")
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["status"] = "not-a-real-status"
        _, errors = validate_payload(payload, ECOSYSTEM_ROOT)
        self.assertTrue(any("status" in e for e in errors))


class DoctorContractsCliTest(unittest.TestCase):
    """`simplicio-mapper doctor --contracts` end to end via cli.main."""

    def test_doctor_contracts_exits_zero_on_clean_checkout(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(["doctor", "--contracts"])
        self.assertEqual(code, 0)
        out = buffer.getvalue()
        self.assertIn("mapper-artifacts/v1", out)
        self.assertIn("ecosystem/v1", out)

    def test_doctor_without_contracts_flag_prints_usage(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(["doctor"])
        self.assertEqual(code, 2)
        self.assertIn("usage", buffer.getvalue())

    def test_doctor_contracts_fails_on_a_broken_extra_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken_path = os.path.join(tmp, "broken-executor.json")
            with open(
                os.path.join(FIXTURES_ROOT, "python-task", "executor.json"), encoding="utf-8"
            ) as handle:
                payload = json.load(handle)
            del payload["layers"]
            with open(broken_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = main(["doctor", "--contracts", broken_path])
            self.assertEqual(code, 1)
            out = buffer.getvalue()
            self.assertIn("fail", out)
            self.assertIn("layers", out)


class StandaloneVendorableScriptTest(unittest.TestCase):
    """scripts/validate_ecosystem_contracts.py must work standalone (no
    simplicio_mapper import) since it is meant to be copy-pasted into
    simplicio-loop/simplicio-dev-cli."""

    def test_script_has_no_simplicio_mapper_import(self) -> None:
        # Prose mentions of "simplicio_mapper" in the module docstring are
        # fine (they explain *why* there is no import) -- only an actual
        # `import`/`from ... import` statement would defeat the point of
        # this file being vendorable without the package installed.
        text = STANDALONE_SCRIPT.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("import simplicio_mapper") or stripped.startswith(
                "from simplicio_mapper"
            ):
                self.fail(f"found a real simplicio_mapper import: {line!r}")

    def test_script_loads_as_a_standalone_module(self) -> None:
        spec = importlib.util.spec_from_file_location("validate_ecosystem_contracts", STANDALONE_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, "main"))

    def test_script_exits_zero_against_committed_fixtures(self) -> None:
        result = subprocess.run(
            [sys.executable, str(STANDALONE_SCRIPT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("simplicio.loop-execution/v1", result.stdout)

    def test_script_fails_actionably_on_a_broken_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken_path = os.path.join(tmp, "broken.json")
            with open(
                os.path.join(FIXTURES_ROOT, "mixed-task", "execution.json"), encoding="utf-8"
            ) as handle:
                payload = json.load(handle)
            del payload["goal"]
            with open(broken_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

            result = subprocess.run(
                [sys.executable, str(STANDALONE_SCRIPT), broken_path],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("goal", result.stdout)
            self.assertIn("fail", result.stdout)

    def test_script_schema_root_override_works_from_outside_repo(self) -> None:
        # Simulates a vendored copy running from a repo that is NOT this one
        # (e.g. simplicio-loop) by pointing --schema-root at a temp copy.
        with tempfile.TemporaryDirectory() as tmp:
            schema_dir = os.path.join(tmp, "schemas")
            os.makedirs(schema_dir)
            for name in ("loop-execution.schema.json", "executor-contract.schema.json"):
                src = os.path.join(ECOSYSTEM_ROOT, "schemas", name)
                with open(src, encoding="utf-8") as handle:
                    content = handle.read()
                with open(os.path.join(schema_dir, name), "w", encoding="utf-8") as handle:
                    handle.write(content)

            fixture_path = os.path.join(FIXTURES_ROOT, "python-task", "execution.json")
            result = subprocess.run(
                [sys.executable, str(STANDALONE_SCRIPT), "--schema-root", schema_dir, fixture_path],
                cwd=tmp,  # deliberately not this repo's root
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
