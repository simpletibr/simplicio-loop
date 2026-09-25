import unittest

from simplicio_fast.engine import (
    EngineSelection,
    PythonManifestError,
    python_manifest,
    select_engine,
    validate_python_manifest,
)


class EngineSelectionTest(unittest.TestCase):
    def test_python_is_the_only_selectable_engine(self) -> None:
        selection = select_engine("python")
        self.assertEqual("python", selection.selected)
        self.assertEqual("explicitly_selected", selection.reason)
        self.assertTrue(selection.manifest["reference"])

    def test_default_selection_is_python(self) -> None:
        selection = select_engine()
        self.assertEqual("python", selection.selected)

    def test_off_disables_the_engine(self) -> None:
        selection = select_engine("off")
        self.assertEqual("off", selection.selected)
        self.assertEqual("explicitly_disabled", selection.reason)
        self.assertEqual({}, selection.manifest)

    def test_unsupported_choice_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            select_engine("rust")

    def test_manifest_is_versioned_and_declares_reference_capabilities(self) -> None:
        manifest = python_manifest()
        self.assertEqual("simplicio.fast.engine-manifest/v1", manifest["schema"])
        self.assertIn("context", manifest["capabilities"])
        self.assertIn("apply", manifest["capabilities"])
        self.assertEqual(["python"], manifest["source_languages"])
        self.assertEqual("3.11", manifest["minimum_python"])
        self.assertEqual(512 * 1024 * 1024, manifest["limits"]["max_snapshot_bytes"])

    def test_python_manifest_validation_rejects_missing_capability_with_stable_code(
        self,
    ) -> None:
        manifest = python_manifest()
        manifest["capabilities"].remove("query")
        with self.assertRaises(PythonManifestError) as raised:
            validate_python_manifest(manifest)
        self.assertEqual("capability_missing", raised.exception.reason_code)

    def test_python_manifest_validation_rejects_identity_and_format_drift(self) -> None:
        manifest = python_manifest()
        manifest["engine"] = "not-python"
        with self.assertRaises(PythonManifestError) as raised:
            validate_python_manifest(manifest)
        self.assertEqual("manifest_field_invalid", raised.exception.reason_code)
        manifest = python_manifest()
        manifest["formats"] = ["SFAST001/v1"]
        with self.assertRaises(PythonManifestError) as raised:
            validate_python_manifest(manifest)
        self.assertEqual("formats_missing", raised.exception.reason_code)

    def test_receipt_exposes_python_selection_contract(self) -> None:
        receipt = select_engine(" Python ").receipt()
        self.assertEqual("simplicio.fast.engine-selection/v1", receipt["schema"])
        self.assertEqual("python", receipt["requested"])
        self.assertEqual("python", receipt["selected_engine"])
        self.assertEqual(python_manifest()["version"], receipt["version"])
        self.assertIn("context", receipt["capabilities"])

    def test_engine_selection_is_a_frozen_dataclass(self) -> None:
        selection = EngineSelection("python", "python", "explicitly_selected", {})
        with self.assertRaises(AttributeError):
            selection.selected = "off"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
