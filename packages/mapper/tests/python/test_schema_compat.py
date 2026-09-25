"""Tests for simplicio_mapper/schema_compat.py + the
`simplicio-mapper schema-compat` CLI subcommand (issue #280, Release Train:
compatible/breaking classifier for project-map, precedent-index,
ContextSnapshot, and canonical-map/worktree-overlay surfaces).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper import schema_compat as schema_compat_module  # noqa: E402
from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.schema_compat import (  # noqa: E402
    SCHEMA_COMPAT_REPORT_SCHEMA,
    TRACKED_JSON_SCHEMAS,
    TRACKED_VERSION_ONLY_SURFACES,
    SchemaCompatError,
    classify_json_schema_diff,
    classify_release_changes,
    classify_version_only_surface,
    previous_release_tag,
    read_file_at_ref,
    run_schema_compat_cli,
)


class ClassifyJsonSchemaDiffTest(unittest.TestCase):
    """Unit: structural JSON-Schema diff classification."""

    OLD = json.dumps(
        {
            "required": ["a"],
            "properties": {"a": {"type": "string"}, "e": {"enum": ["x", "y"]}},
        }
    )

    def test_both_absent_is_unchanged(self) -> None:
        classification, reasons = classify_json_schema_diff(None, None)
        self.assertEqual(classification, "unchanged")
        self.assertTrue(reasons)

    def test_identical_text_is_unchanged(self) -> None:
        classification, reasons = classify_json_schema_diff(self.OLD, self.OLD)
        self.assertEqual(classification, "unchanged")
        self.assertEqual(reasons, [])

    def test_new_file_is_compatible(self) -> None:
        classification, reasons = classify_json_schema_diff(None, self.OLD)
        self.assertEqual(classification, "compatible")
        self.assertTrue(any("newly added" in r for r in reasons))

    def test_removed_file_is_breaking(self) -> None:
        classification, reasons = classify_json_schema_diff(self.OLD, None)
        self.assertEqual(classification, "breaking")
        self.assertTrue(any("removed" in r for r in reasons))

    def test_new_optional_property_is_compatible(self) -> None:
        new = json.dumps(
            {
                "required": ["a"],
                "properties": {
                    "a": {"type": "string"},
                    "e": {"enum": ["x", "y"]},
                    "b": {"type": "string"},
                },
            }
        )
        classification, reasons = classify_json_schema_diff(self.OLD, new)
        self.assertEqual(classification, "compatible")
        self.assertTrue(any("'b' added as optional" in r for r in reasons))

    def test_new_enum_value_is_compatible(self) -> None:
        new = json.dumps(
            {
                "required": ["a"],
                "properties": {"a": {"type": "string"}, "e": {"enum": ["x", "y", "z"]}},
            }
        )
        classification, reasons = classify_json_schema_diff(self.OLD, new)
        self.assertEqual(classification, "compatible")
        self.assertTrue(any("enum value 'z' added" in r for r in reasons))

    def test_relaxed_required_is_compatible(self) -> None:
        new = json.dumps(
            {
                "required": [],
                "properties": {"a": {"type": "string"}, "e": {"enum": ["x", "y"]}},
            }
        )
        classification, reasons = classify_json_schema_diff(self.OLD, new)
        self.assertEqual(classification, "compatible")
        self.assertTrue(any("no longer required" in r for r in reasons))

    def test_new_required_property_is_breaking(self) -> None:
        new = json.dumps(
            {
                "required": ["a", "b"],
                "properties": {
                    "a": {"type": "string"},
                    "e": {"enum": ["x", "y"]},
                    "b": {"type": "string"},
                },
            }
        )
        classification, reasons = classify_json_schema_diff(self.OLD, new)
        self.assertEqual(classification, "breaking")
        self.assertTrue(any("added as required" in r for r in reasons))

    def test_existing_property_becoming_required_is_breaking(self) -> None:
        old = json.dumps(
            {
                "required": [],
                "properties": {"a": {"type": "string"}},
            }
        )
        new = json.dumps(
            {
                "required": ["a"],
                "properties": {"a": {"type": "string"}},
            }
        )
        classification, reasons = classify_json_schema_diff(old, new)
        self.assertEqual(classification, "breaking")
        self.assertTrue(any("became required" in r for r in reasons))

    def test_removed_property_is_breaking(self) -> None:
        new = json.dumps({"required": [], "properties": {"e": {"enum": ["x", "y"]}}})
        classification, reasons = classify_json_schema_diff(self.OLD, new)
        self.assertEqual(classification, "breaking")
        self.assertTrue(any("'a' removed" in r for r in reasons))

    def test_type_change_is_breaking(self) -> None:
        new = json.dumps(
            {
                "required": ["a"],
                "properties": {"a": {"type": "integer"}, "e": {"enum": ["x", "y"]}},
            }
        )
        classification, reasons = classify_json_schema_diff(self.OLD, new)
        self.assertEqual(classification, "breaking")
        self.assertTrue(any("type changed" in r for r in reasons))

    def test_removed_enum_value_is_breaking(self) -> None:
        new = json.dumps(
            {
                "required": ["a"],
                "properties": {"a": {"type": "string"}, "e": {"enum": ["x"]}},
            }
        )
        classification, reasons = classify_json_schema_diff(self.OLD, new)
        self.assertEqual(classification, "breaking")
        self.assertTrue(any("enum value 'y' removed" in r for r in reasons))

    def test_metadata_only_change_is_compatible_with_explicit_reason(self) -> None:
        old = json.dumps({"title": "Old title", "properties": {}, "required": []})
        new = json.dumps({"title": "New title", "properties": {}, "required": []})
        classification, reasons = classify_json_schema_diff(old, new)
        self.assertEqual(classification, "compatible")
        self.assertTrue(any("metadata-only" in r for r in reasons))

    def test_malformed_old_json_raises(self) -> None:
        with self.assertRaises(SchemaCompatError):
            classify_json_schema_diff("{not json", self.OLD)

    def test_malformed_new_json_raises(self) -> None:
        with self.assertRaises(SchemaCompatError):
            classify_json_schema_diff(self.OLD, "{not json")


class PreviousReleaseTagTest(unittest.TestCase):
    """Integration: real git-tag resolution against this actual checkout."""

    def test_resolves_a_real_semver_tag_ancestor_of_head(self) -> None:
        tag = previous_release_tag(str(ROOT))
        self.assertIsNotNone(tag)
        self.assertRegex(tag, r"^(?:[a-z0-9-]+-)?v\d+\.\d+\.\d+$")

    def test_returns_none_outside_a_git_repo(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(previous_release_tag(tmp))

    def test_returns_none_when_no_previous_tag_exists_yet(self) -> None:
        """Contract: a package with no tagged release yet (monorepo import
        day one, before its first per-package tag is cut) must resolve to
        ``None`` -- "cannot classify" -- never fabricate or fall back to an
        unrelated tag. Built as a throwaway local fixture repo so this does
        not depend on which tags happen to exist in this clone."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(
                ["git", "-C", tmp, "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", tmp, "config", "user.name", "test"], check=True
            )
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "simplicio-widget"\n', encoding="utf-8"
            )
            subprocess.run(["git", "-C", tmp, "add", "."], check=True)
            subprocess.run(
                ["git", "-C", tmp, "commit", "-q", "-m", "init"], check=True
            )
            self.assertIsNone(previous_release_tag(tmp))

    def test_resolves_prefixed_tag_from_package_name(self) -> None:
        """A package tags its own releases as ``<short-name>-vX.Y.Z``; the
        prefix is derived from this package's own ``pyproject.toml`` name,
        never from the enclosing monorepo's tags or dirname."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(
                ["git", "-C", tmp, "config", "user.email", "test@example.com"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", tmp, "config", "user.name", "test"], check=True
            )
            (Path(tmp) / "pyproject.toml").write_text(
                '[project]\nname = "simplicio-widget"\n', encoding="utf-8"
            )
            subprocess.run(["git", "-C", tmp, "add", "."], check=True)
            subprocess.run(
                ["git", "-C", tmp, "commit", "-q", "-m", "init"], check=True
            )
            subprocess.run(
                ["git", "-C", tmp, "tag", "widget-v1.0.0"], check=True
            )
            (Path(tmp) / "README.md").write_text("later\n", encoding="utf-8")
            subprocess.run(["git", "-C", tmp, "add", "."], check=True)
            subprocess.run(
                ["git", "-C", tmp, "commit", "-q", "-m", "second"], check=True
            )
            tag = previous_release_tag(tmp)
            self.assertEqual(tag, "widget-v1.0.0")

    def test_read_file_at_ref_returns_none_for_missing_ref(self) -> None:
        self.assertIsNone(
            read_file_at_ref(str(ROOT), "not-a-real-ref-xyz", "package.json")
        )

    def test_read_file_at_ref_reads_real_content(self) -> None:
        tag = previous_release_tag(str(ROOT))
        content = read_file_at_ref(str(ROOT), tag, "package.json")
        self.assertIsNotNone(content)
        json.loads(content)  # must be valid JSON


class ClassifyVersionOnlySurfaceTest(unittest.TestCase):
    """Unit: version-int-only surfaces (overlays, no on-disk JSON Schema)."""

    def test_unchanged_when_constant_matches_previous_tag(self) -> None:
        tag = previous_release_tag(str(ROOT))
        with mock.patch.object(
            schema_compat_module, "_read_constant_at_ref", return_value=1
        ):
            classification, reasons = classify_version_only_surface(
                str(ROOT), tag, "simplicio_mapper.mapper.canonical", "CANONICAL_MAP_SCHEMA_VERSION"
            )
        self.assertEqual(classification, "unchanged")
        self.assertEqual(reasons, [])

    def test_breaking_when_constant_bumped(self) -> None:
        tag = previous_release_tag(str(ROOT))
        with mock.patch.object(
            schema_compat_module, "_read_constant_at_ref", return_value=0
        ):
            classification, reasons = classify_version_only_surface(
                str(ROOT), tag, "simplicio_mapper.mapper.canonical", "CANONICAL_MAP_SCHEMA_VERSION"
            )
        self.assertEqual(classification, "breaking")
        self.assertTrue(any("bumped" in r for r in reasons))

    def test_compatible_when_surface_newly_added(self) -> None:
        tag = previous_release_tag(str(ROOT))
        with mock.patch.object(
            schema_compat_module, "_read_constant_at_ref", return_value=None
        ):
            classification, reasons = classify_version_only_surface(
                str(ROOT), tag, "simplicio_mapper.mapper.canonical", "CANONICAL_MAP_SCHEMA_VERSION"
            )
        self.assertEqual(classification, "compatible")
        self.assertTrue(any("newly added surface" in r for r in reasons))


class ClassifyReleaseChangesTest(unittest.TestCase):
    """Integration + system: full report against the real repo checkout."""

    def test_report_against_real_previous_tag(self) -> None:
        report = classify_release_changes(root=str(ROOT))
        self.assertEqual(report["schema"], SCHEMA_COMPAT_REPORT_SCHEMA)
        self.assertRegex(report["against_ref"], r"^(?:[a-z0-9-]+-)?v\d+\.\d+\.\d+$")
        self.assertIn(report["overall"], {"unchanged", "compatible", "breaking"})
        surface_names = {s["surface"] for s in report["surfaces"]}
        expected = {name for name, _ in TRACKED_JSON_SCHEMAS} | {
            name for name, _, _ in TRACKED_VERSION_ONLY_SURFACES
        }
        self.assertEqual(surface_names, expected)

    def test_overall_is_the_max_severity_of_its_surfaces(self) -> None:
        report = classify_release_changes(root=str(ROOT))
        severities = {"unchanged": 0, "compatible": 1, "breaking": 2}
        expected_overall = max(
            (s["classification"] for s in report["surfaces"]), key=lambda c: severities[c]
        )
        self.assertEqual(report["overall"], expected_overall)

    def test_raises_when_no_previous_tag_resolvable(self) -> None:
        with mock.patch.object(schema_compat_module, "previous_release_tag", return_value=None):
            with self.assertRaises(SchemaCompatError):
                classify_release_changes(root=str(ROOT))

    def test_explicit_against_ref_is_honored(self) -> None:
        # Regression: passing --against/ against_ref explicitly must be used
        # verbatim, never silently overridden by previous_release_tag().
        with mock.patch.object(schema_compat_module, "previous_release_tag") as mocked:
            report = classify_release_changes(root=str(ROOT), against_ref="v0.18.0")
            mocked.assert_not_called()
        self.assertEqual(report["against_ref"], "v0.18.0")

    def test_report_is_json_serializable(self) -> None:
        report = classify_release_changes(root=str(ROOT))
        json.dumps(report)


class SchemaCompatCliTest(unittest.TestCase):
    """System: real CLI invocation via `simplicio_mapper.cli.main`."""

    def test_json_flag_emits_valid_report(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["schema-compat", "--json", "--root", str(ROOT)])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["schema"], SCHEMA_COMPAT_REPORT_SCHEMA)

    def test_human_readable_output(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["schema-compat", "--root", str(ROOT)])
        self.assertEqual(exit_code, 0)
        output = buffer.getvalue()
        self.assertIn("against:", output)
        self.assertIn("overall:", output)
        self.assertIn("project-map", output)

    def test_against_flag_is_forwarded(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(
                ["schema-compat", "--json", "--root", str(ROOT), "--against", "v0.18.0"]
            )
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["against_ref"], "v0.18.0")

    def test_root_flag_without_value_exits_with_usage_error(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["schema-compat", "--root"])
        self.assertEqual(exit_code, 2)

    def test_against_flag_without_value_exits_with_usage_error(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["schema-compat", "--against"])
        self.assertEqual(exit_code, 2)

    def test_classifier_error_is_reported_not_raised(self) -> None:
        with mock.patch.object(
            schema_compat_module,
            "classify_release_changes",
            side_effect=SchemaCompatError("boom"),
        ):
            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = run_schema_compat_cli([])
        self.assertEqual(exit_code, 1)

    def test_fail_on_breaking_exits_nonzero_when_breaking_found(self) -> None:
        fake_report = {
            "schema": SCHEMA_COMPAT_REPORT_SCHEMA,
            "against_ref": "v0.0.0",
            "overall": "breaking",
            "surfaces": [],
        }
        with mock.patch.object(
            schema_compat_module, "classify_release_changes", return_value=fake_report
        ):
            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = run_schema_compat_cli(["--fail-on-breaking"])
        self.assertEqual(exit_code, 1)

    def test_fail_on_breaking_exits_zero_when_only_compatible(self) -> None:
        fake_report = {
            "schema": SCHEMA_COMPAT_REPORT_SCHEMA,
            "against_ref": "v0.0.0",
            "overall": "compatible",
            "surfaces": [],
        }
        with mock.patch.object(
            schema_compat_module, "classify_release_changes", return_value=fake_report
        ):
            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = run_schema_compat_cli(["--fail-on-breaking"])
        self.assertEqual(exit_code, 0)

    def test_without_fail_on_breaking_exits_zero_even_with_breaking(self) -> None:
        # A breaking change may be intentional/reviewed -- the default CLI
        # behavior must report, not gate, unless explicitly asked to.
        fake_report = {
            "schema": SCHEMA_COMPAT_REPORT_SCHEMA,
            "against_ref": "v0.0.0",
            "overall": "breaking",
            "surfaces": [],
        }
        with mock.patch.object(
            schema_compat_module, "classify_release_changes", return_value=fake_report
        ):
            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = run_schema_compat_cli([])
        self.assertEqual(exit_code, 0)

    def test_module_entrypoint_runs_via_real_subprocess(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.schema_compat", "--json"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], SCHEMA_COMPAT_REPORT_SCHEMA)


if __name__ == "__main__":
    unittest.main()
