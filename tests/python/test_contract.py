"""Tests for simplicio_mapper/contract.py + the `contract validate` CLI
subcommand (issue #157, mapper-artifacts contract).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.contract import (  # noqa: E402
    ContractError,
    find_contract_root,
    iter_json_files,
    load_schema,
    validate_file,
    validate_instance,
    validate_payload,
)

CONTRACT_ROOT = str(ROOT / "contracts" / "mapper-artifacts" / "v1")
FIXTURES_ROOT = os.path.join(CONTRACT_ROOT, "fixtures")


class ValidatorSubsetTest(unittest.TestCase):
    """Unit tests for the hand-rolled JSON-Schema-subset validator itself,
    independent of any real mapper fixture."""

    def test_missing_required_property_is_an_error(self) -> None:
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
        errors = validate_instance({}, schema)
        self.assertTrue(any("a" in e and "required" in e for e in errors))

    def test_wrong_type_is_an_error(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
        errors = validate_instance({"a": "not-an-int"}, schema)
        self.assertTrue(errors)

    def test_bool_is_not_accepted_as_integer(self) -> None:
        # bool is an int subclass in Python; the validator must not conflate them.
        schema = {"type": "integer"}
        self.assertTrue(validate_instance(True, schema))

    def test_nullable_union_accepts_both(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": ["string", "null"]}}}
        self.assertEqual(validate_instance({"a": None}, schema), [])
        self.assertEqual(validate_instance({"a": "x"}, schema), [])
        self.assertTrue(validate_instance({"a": 5}, schema))

    def test_enum_rejects_unknown_value(self) -> None:
        schema = {"type": "string", "enum": ["a", "b"]}
        self.assertEqual(validate_instance("a", schema), [])
        self.assertTrue(validate_instance("z", schema))

    def test_array_items_are_validated_recursively(self) -> None:
        schema = {"type": "array", "items": {"type": "object", "required": ["id"]}}
        self.assertEqual(validate_instance([{"id": 1}], schema), [])
        self.assertTrue(validate_instance([{"nope": 1}], schema))

    def test_additional_properties_are_never_flagged(self) -> None:
        # No `additionalProperties: false` support by design (see contracts/
        # mapper-artifacts/v1/README.md) — purely additive fields must pass.
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
        self.assertEqual(validate_instance({"a": "x", "brand_new_field": 123}, schema), [])


class ContractRootAndSchemaLoadingTest(unittest.TestCase):
    def test_find_contract_root_from_repo_root(self) -> None:
        found = find_contract_root(str(ROOT))
        self.assertEqual(os.path.normpath(found), os.path.normpath(CONTRACT_ROOT))

    def test_find_contract_root_from_nested_cwd(self) -> None:
        nested = ROOT / "simplicio_mapper"
        found = find_contract_root(str(nested))
        self.assertEqual(os.path.normpath(found), os.path.normpath(CONTRACT_ROOT))

    def test_find_contract_root_falls_back_to_package_dir_from_unrelated_cwd(self) -> None:
        # Even when `start` has no `contracts/` ancestor of its own, the
        # package-relative fallback (this repo's checkout, via the editable
        # install) still resolves it — this is what makes `contract validate`
        # work regardless of the caller's cwd.
        with tempfile.TemporaryDirectory() as tmp:
            found = find_contract_root(tmp)
            self.assertEqual(os.path.normpath(found), os.path.normpath(CONTRACT_ROOT))

    def test_load_schema_unknown_id_raises(self) -> None:
        with self.assertRaises(ContractError):
            load_schema("simplicio.does-not-exist/v1", CONTRACT_ROOT)

    def test_mapper_and_visualization_schemas_load(self) -> None:
        for schema_id in [
            "simplicio.project-map/v1",
            "simplicio.precedent-index/v1",
            "simplicio.architecture-inventory/v1",
            "simplicio.symbol-index/v1",
            "simplicio.call-graph/v1",
            "simplicio.mapper-index/v1",
            "simplicio.visualization-bundle/v1",
            "simplicio.visualization-preview/v1",
        ]:
            schema = load_schema(schema_id, CONTRACT_ROOT)
            self.assertEqual(schema.get("$id"), schema_id)


class RealFixtureValidationTest(unittest.TestCase):
    """Every committed fixture must validate cleanly — this is the fast,
    subprocess-free counterpart to `scripts/regen_contract_fixtures.py check`
    (which re-runs the mapper fresh; this test just re-checks the committed
    JSON against the committed schemas so schema/fixture drift is caught even
    without invoking the mapper)."""

    def test_all_committed_artifact_fixtures_validate(self) -> None:
        for fixture_name in (
            "python-minimal",
            "node-minimal",
            "mixed-workspace",
            "canonical-matrix",
        ):
            artifacts_dir = os.path.join(FIXTURES_ROOT, fixture_name, "artifacts")
            self.assertTrue(os.path.isdir(artifacts_dir), artifacts_dir)
            for filename in os.listdir(artifacts_dir):
                path = os.path.join(artifacts_dir, filename)
                with self.subTest(fixture=fixture_name, file=filename):
                    schema_id, errors = validate_file(path, CONTRACT_ROOT)
                    self.assertEqual(errors, [], f"{path} ({schema_id}): {errors}")

    def test_mapper_index_result_fixture_validates(self) -> None:
        path = os.path.join(FIXTURES_ROOT, "python-minimal", "mapper-index-result.json")
        schema_id, errors = validate_file(path, CONTRACT_ROOT)
        self.assertEqual(schema_id, "simplicio.mapper-index/v1")
        self.assertEqual(errors, [])

    def test_all_fixtures_cover_project_map(self) -> None:
        # Issue #157 AC plus #614's mixed-language matrix fixture.
        for fixture_name in (
            "python-minimal",
            "node-minimal",
            "mixed-workspace",
            "canonical-matrix",
        ):
            path = os.path.join(FIXTURES_ROOT, fixture_name, "artifacts", "project-map.json")
            self.assertTrue(os.path.isfile(path), path)


class TamperedFixtureDetectionTest(unittest.TestCase):
    """Proves the validator actually fails on real drift, not just passes by
    construction — mirrors the drift caught during development (mapper's
    `dependencies.manifest` is `string | null`, not `object | null`)."""

    def test_wrong_type_in_a_copy_of_a_real_fixture_is_rejected(self) -> None:
        path = os.path.join(FIXTURES_ROOT, "python-minimal", "artifacts", "project-map.json")
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["files"] = "not-a-list"
        _, errors = validate_payload(payload, CONTRACT_ROOT)
        self.assertTrue(errors)
        self.assertTrue(any("files" in e for e in errors))

    def test_missing_required_top_level_key_is_rejected(self) -> None:
        path = os.path.join(FIXTURES_ROOT, "python-minimal", "artifacts", "call-graph.json")
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        del payload["counts"]
        _, errors = validate_payload(payload, CONTRACT_ROOT)
        self.assertTrue(any("counts" in e for e in errors))


class IterJsonFilesTest(unittest.TestCase):
    def test_expands_directory_recursively(self) -> None:
        found = iter_json_files([os.path.join(FIXTURES_ROOT, "python-minimal", "artifacts")])
        self.assertEqual(len(found), 5)
        self.assertTrue(all(f.endswith(".json") for f in found))

    def test_missing_path_raises(self) -> None:
        with self.assertRaises(ContractError):
            iter_json_files(["/does/not/exist/at/all"])


class ContractCliSubcommandTest(unittest.TestCase):
    """`simplicio-mapper contract validate ...` end to end via cli.main."""

    def test_validate_real_fixtures_exits_zero(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main([
                "contract", "validate",
                os.path.join(FIXTURES_ROOT, "python-minimal", "artifacts"),
            ])
        self.assertEqual(code, 0)
        self.assertIn("simplicio.project-map/v1", buffer.getvalue())

    def test_validate_missing_path_exits_nonzero(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(["contract", "validate", "/definitely/not/a/real/path"])
        self.assertEqual(code, 1)

    def test_validate_with_no_paths_prints_usage(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(["contract", "validate"])
        self.assertEqual(code, 2)
        self.assertIn("usage", buffer.getvalue())

    def test_bogus_subcommand_prints_usage(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(["contract", "bogus"])
        self.assertEqual(code, 2)

    def test_validate_a_broken_json_file_reports_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken_path = os.path.join(tmp, "broken-project-map.json")
            with open(
                os.path.join(FIXTURES_ROOT, "python-minimal", "artifacts", "project-map.json"),
                encoding="utf-8",
            ) as handle:
                payload = json.load(handle)
            payload["files"] = "not-a-list"
            with open(broken_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = main(["contract", "validate", broken_path])
            self.assertEqual(code, 1)
            self.assertIn("fail", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
