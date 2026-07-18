"""Tests for simplicio_mapper/release_manifest.py + the
`simplicio-mapper release-manifest` CLI subcommand (issue #280, Phase-0
local release manifest; see .specs/architecture/ADR-010-release-manifest-phase0.md).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
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

from simplicio_mapper import __version__ as PACKAGE_VERSION  # noqa: E402
from simplicio_mapper import release_manifest as release_manifest_module  # noqa: E402
from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.release_manifest import (  # noqa: E402
    RELEASE_MANIFEST_SCHEMA,
    SCHEMA_VERSION_REGISTRY,
    ReleaseManifestError,
    _git_commit_sha,
    build_release_manifest,
    check_registry_baseline,
    collect_schema_versions,
    run_release_manifest_cli,
    write_registry_baseline,
)

BASELINE_PATH = ROOT / "scripts" / "schema_registry_baseline.json"


class CollectSchemaVersionsTest(unittest.TestCase):
    """Unit: schema-version registry collection (issue #280, task step 1/3)."""

    def test_collects_every_registered_entry(self) -> None:
        collected = collect_schema_versions()
        self.assertEqual(len(collected), len(SCHEMA_VERSION_REGISTRY))
        for module_path, attr_name in SCHEMA_VERSION_REGISTRY:
            self.assertIn(f"{module_path}:{attr_name}", collected)

    def test_values_are_int_or_str(self) -> None:
        for value in collect_schema_versions().values():
            self.assertIsInstance(value, (int, str))

    def test_unknown_module_raises(self) -> None:
        with self.assertRaises(ReleaseManifestError):
            collect_schema_versions((("simplicio_mapper.does_not_exist", "X"),))

    def test_unknown_attribute_raises(self) -> None:
        with self.assertRaises(ReleaseManifestError):
            collect_schema_versions((("simplicio_mapper.contract", "NOT_A_REAL_ATTR"),))

    def test_non_int_str_value_raises(self) -> None:
        # simplicio_mapper.contract.SCHEMA_FILENAMES is a dict, not int/str.
        with self.assertRaises(ReleaseManifestError):
            collect_schema_versions((("simplicio_mapper.contract", "SCHEMA_FILENAMES"),))

    def test_known_constant_values_are_correct(self) -> None:
        # Regression pin: these are real, currently-committed values (issue
        # #280 inventory). If a future refactor bumps one, this test forces
        # a conscious update alongside the schema_registry_baseline.json
        # regeneration (--update-registry-baseline).
        collected = collect_schema_versions()
        self.assertEqual(collected["simplicio_mapper.mapper.parse:ARTIFACT_VERSION"], 1)
        self.assertEqual(collected["simplicio_mapper.contract:CONTRACT_VERSION"], "v1")
        self.assertEqual(collected["simplicio_mapper.context_snapshot:SCHEMA_VERSION"], "v1")


class BuildReleaseManifestTest(unittest.TestCase):
    """Unit + integration: manifest field correctness against a real git repo."""

    def test_schema_and_component_fields(self) -> None:
        manifest = build_release_manifest(root=str(ROOT))
        self.assertEqual(manifest["schema"], RELEASE_MANIFEST_SCHEMA)
        self.assertEqual(manifest["component"], "simplicio-mapper")

    def test_version_matches_single_source(self) -> None:
        manifest = build_release_manifest(root=str(ROOT))
        self.assertEqual(manifest["version"], PACKAGE_VERSION)

    def test_commit_sha_resolves_against_real_git_repo(self) -> None:
        # Integration: this repo checkout is a real git repo (see task
        # instructions), so `git rev-parse HEAD` must succeed for real.
        manifest = build_release_manifest(root=str(ROOT))
        self.assertIsNotNone(manifest["commit_sha"])
        self.assertEqual(manifest["commit_sha_source"], "git rev-parse HEAD")
        self.assertRegex(manifest["commit_sha"], r"^[0-9a-f]{40}$")

    def test_commit_sha_is_none_outside_a_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = build_release_manifest(root=tmp)
            self.assertIsNone(manifest["commit_sha"])
            self.assertTrue(manifest["commit_sha_source"].startswith("unavailable"))

    def test_commit_sha_handles_git_invocation_failure(self) -> None:
        # Regression: a missing/broken git binary must degrade to `None`,
        # never raise out of build_release_manifest (a manifest generator
        # must always produce a receipt, even a partial one).
        with mock.patch(
            "simplicio_mapper.release_manifest.subprocess.run",
            side_effect=OSError("git not found"),
        ):
            sha, source = _git_commit_sha(str(ROOT))
        self.assertIsNone(sha)
        self.assertIn("git invocation failed", source)

    def test_distribution_channels(self) -> None:
        manifest = build_release_manifest(root=str(ROOT))
        self.assertEqual(manifest["distribution"]["pypi_package"], "simplicio-mapper")
        self.assertEqual(
            manifest["distribution"]["npm_package"], "@wesleysimplicio/llm-project-mapper"
        )

    def test_signing_block_is_an_explicit_placeholder_never_a_fake_value(self) -> None:
        manifest = build_release_manifest(root=str(ROOT))
        signing = manifest["signing"]
        self.assertEqual(signing["status"], "not-implemented")
        self.assertIsNone(signing["digest"])
        self.assertIsNone(signing["signature"])
        self.assertIsNone(signing["sbom"])
        self.assertIn("Phase-0", signing["note"])

    def test_downstream_events_block_is_an_explicit_placeholder(self) -> None:
        manifest = build_release_manifest(root=str(ROOT))
        self.assertEqual(manifest["downstream_events"]["status"], "not-implemented")

    def test_schema_versions_block_matches_registry(self) -> None:
        manifest = build_release_manifest(root=str(ROOT))
        self.assertEqual(len(manifest["schema_versions"]), len(SCHEMA_VERSION_REGISTRY))

    def test_manifest_is_json_serializable(self) -> None:
        manifest = build_release_manifest(root=str(ROOT))
        # Must round-trip without error -- this is what the CLI --json path relies on.
        json.dumps(manifest)

    def test_manifest_is_deterministic_given_same_checkout(self) -> None:
        first = build_release_manifest(root=str(ROOT))
        second = build_release_manifest(root=str(ROOT))
        first.pop("generated_at")
        second.pop("generated_at")
        self.assertEqual(first, second)


class RegistryBaselineTest(unittest.TestCase):
    """Unit: schema-version-registry baseline drift gate (issue #280 step 8,
    schema-version-divergence half, verifiable locally without any registry
    API call)."""

    def test_committed_baseline_matches_live_registry(self) -> None:
        # Regression: the checked-in scripts/schema_registry_baseline.json
        # must match SCHEMA_VERSION_REGISTRY exactly at all times -- this is
        # the same invariant `scripts/check_schema_registry_sync.py` enforces
        # in CI/local, proven here without shelling out.
        ok, messages = check_registry_baseline(baseline_path=str(BASELINE_PATH))
        self.assertTrue(ok, msg="\n".join(messages))

    def test_missing_baseline_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "does-not-exist.json")
            ok, messages = check_registry_baseline(baseline_path=missing)
            self.assertFalse(ok)
            self.assertTrue(any("no baseline file" in m for m in messages))

    def test_changed_value_is_detected_as_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = os.path.join(tmp, "baseline.json")
            write_registry_baseline(baseline_path=baseline_path)
            with open(baseline_path, encoding="utf-8") as handle:
                doc = json.load(handle)
            # Simulate an unreviewed drift: tamper with one committed value.
            key = "simplicio_mapper.mapper.parse:ARTIFACT_VERSION"
            doc["entries"][key] = 999
            with open(baseline_path, "w", encoding="utf-8") as handle:
                json.dump(doc, handle)
            ok, messages = check_registry_baseline(baseline_path=baseline_path)
            self.assertFalse(ok)
            self.assertTrue(any("[changed]" in m and key in m for m in messages))

    def test_new_entry_not_in_baseline_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = os.path.join(tmp, "baseline.json")
            write_registry_baseline(baseline_path=baseline_path)
            with open(baseline_path, encoding="utf-8") as handle:
                doc = json.load(handle)
            del doc["entries"]["simplicio_mapper.mapper.parse:ARTIFACT_VERSION"]
            with open(baseline_path, "w", encoding="utf-8") as handle:
                json.dump(doc, handle)
            ok, messages = check_registry_baseline(baseline_path=baseline_path)
            self.assertFalse(ok)
            self.assertTrue(any("[new]" in m for m in messages))

    def test_baseline_entry_no_longer_in_registry_is_detected_as_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = os.path.join(tmp, "baseline.json")
            write_registry_baseline(baseline_path=baseline_path)
            with open(baseline_path, encoding="utf-8") as handle:
                doc = json.load(handle)
            # Simulate a constant that used to exist in the registry but was
            # removed/renamed -- the baseline still references it.
            doc["entries"]["simplicio_mapper.does_not_exist:GHOST_VERSION"] = 1
            with open(baseline_path, "w", encoding="utf-8") as handle:
                json.dump(doc, handle)
            ok, messages = check_registry_baseline(baseline_path=baseline_path)
            self.assertFalse(ok)
            self.assertTrue(any("[removed]" in m for m in messages))

    def test_update_baseline_round_trips_to_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            baseline_path = os.path.join(tmp, "baseline.json")
            write_registry_baseline(baseline_path=baseline_path)
            ok, _messages = check_registry_baseline(baseline_path=baseline_path)
            self.assertTrue(ok)


class ReleaseManifestCliTest(unittest.TestCase):
    """System: real CLI invocation via `simplicio_mapper.cli.main` (dispatch
    before `_parse_args`, same shape as `contract`/`doctor`/`canonical`)."""

    def test_json_flag_emits_valid_manifest(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["release-manifest", "--json", "--root", str(ROOT)])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["schema"], RELEASE_MANIFEST_SCHEMA)
        self.assertEqual(payload["version"], PACKAGE_VERSION)

    def test_human_readable_output_without_json_flag(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["release-manifest", "--root", str(ROOT)])
        self.assertEqual(exit_code, 0)
        output = buffer.getvalue()
        self.assertIn("component:", output)
        self.assertIn("version:", output)
        self.assertIn("commit_sha:", output)

    def test_check_registry_exits_zero_against_committed_baseline(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["release-manifest", "--check-registry"])
        self.assertEqual(exit_code, 0)
        self.assertIn("[ok]", buffer.getvalue())

    def test_update_and_check_registry_baseline_round_trip(self) -> None:
        # Exercises the real CLI --update-registry-baseline / --check-registry
        # flags end to end against the real, currently-committed baseline
        # file, restoring it afterwards so the test suite leaves no diff.
        original = BASELINE_PATH.read_text(encoding="utf-8")
        try:
            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["release-manifest", "--update-registry-baseline"])
            self.assertEqual(exit_code, 0)
            self.assertIn("[ok]", buffer.getvalue())

            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["release-manifest", "--check-registry"])
            self.assertEqual(exit_code, 0)
        finally:
            BASELINE_PATH.write_text(original, encoding="utf-8")

    def test_root_flag_without_value_exits_with_usage_error(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["release-manifest", "--root"])
        self.assertEqual(exit_code, 2)

    def test_manifest_build_error_is_reported_not_raised(self) -> None:
        with mock.patch.object(
            release_manifest_module,
            "build_release_manifest",
            side_effect=ReleaseManifestError("boom"),
        ):
            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = run_release_manifest_cli([])
        self.assertEqual(exit_code, 1)

    def test_check_registry_error_is_reported_not_raised(self) -> None:
        with mock.patch.object(
            release_manifest_module,
            "check_registry_baseline",
            side_effect=ReleaseManifestError("boom"),
        ):
            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = run_release_manifest_cli(["--check-registry"])
        self.assertEqual(exit_code, 1)

    def test_update_registry_baseline_error_is_reported_not_raised(self) -> None:
        with mock.patch.object(
            release_manifest_module,
            "write_registry_baseline",
            side_effect=ReleaseManifestError("boom"),
        ):
            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = run_release_manifest_cli(["--update-registry-baseline"])
        self.assertEqual(exit_code, 1)

    def test_module_entrypoint_runs_via_real_subprocess(self) -> None:
        # System: `python -m simplicio_mapper.release_manifest --json` is the
        # exact form documented for a clean install without the `simplicio-mapper`
        # console script on PATH -- exercise the real `__main__` guard.
        result = subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.release_manifest", "--json"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], RELEASE_MANIFEST_SCHEMA)


if __name__ == "__main__":
    unittest.main()
