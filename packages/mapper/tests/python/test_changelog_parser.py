"""Tests for simplicio_mapper/changelog_parser.py + the
`simplicio-mapper changelog` CLI subcommand (issue #280, Release Train,
step 9: machine-readable changelog with migration/rollback).

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

from simplicio_mapper import changelog_parser as changelog_parser_module  # noqa: E402
from simplicio_mapper.changelog_parser import (  # noqa: E402
    CHANGELOG_REPORT_SCHEMA,
    ChangelogParseError,
    build_changelog_report,
    build_migration_signal,
    build_rollback_hint,
    find_entry_by_version,
    find_latest_entry,
    load_changelog_entries,
    parse_changelog,
    run_changelog_cli,
)
from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.schema_compat import SchemaCompatError  # noqa: E402

# Real excerpts copied verbatim from this repo's own CHANGELOG.md (not
# synthetic fixtures) -- proves the parser against actual content this repo
# already has, per the task's DoD requirement.

REAL_EXCERPT_0_24_1_AND_0_24_0 = """\
## [0.24.1] - 2026-07-18

### Fixed

- Cut an actual tagged/published release containing the `0.24.0` timeout
  fix (bounded synchronous scans, terminal `phase=timeout` receipts with
  `failure_reason=scan_timeout`, `exit_code=1`, and dead-owner lock
  recovery — `simplicio_mapper/cli/_status_engine.py`,
  `simplicio_mapper/cli/_background.py`) and the additional canonical-map
  and async-pipeline work merged since (issues #235, #236) that had piled
  up on top of the untagged `0.24.0` version bump (issue #233).

### Release process notes (issue #233)

- **Root cause of the drift**: the `0.24.0` version bump (commit
  `caa54aa`, "release: simplicio-mapper v0.24.0 (#253)") updated
  `package.json`/`pyproject.toml`/`simplicio_mapper/__init__.py` and the
  changelog, but **no `v0.24.0` git tag was ever created and no PyPI
  publish ran** for it — `git tag -l` on this repo stops at `v0.23.1`.
- **Rollback**: `pip install simplicio-mapper==0.23.1` restores the prior
  published release if `0.24.1` regresses in the field; there is no
  `0.24.0` PyPI artifact to roll back to, since it was never published.

## [0.24.0] - 2026-07-17

### Fixed

- Make synchronous scans run in a bounded worker with terminal timeout
  receipts and safe dead-owner lock recovery (issues #201 and #230).
- Prevent Windows background/index workers from inheriting invalid stdin
  handles under pytest and non-interactive hosts (issue #231).

## [0.23.1] - 2026-07-13

### Fixed

- Harden ContextSnapshot fidelity abstention and broader-context signaling.
- Publish measured installed-consumer and historical closure audit receipts.
"""

REAL_EXCERPT_0_22_0 = """\
## [0.22.0] - 2026-07-12

### Added

- Persistent, token-budgeted retrieval indexing for task context selection (issue #199).
- Stable retrieval-index receipts for downstream dev-cli consumers.

### Fixed

- Safe recovery of orphaned mapper index locks.
"""

REAL_EXCERPT_0_14_0_PREAMBLE = """\
## [0.14.0] - 2026-07-02

### Added

Flow Documentation Engine (epic [#131](https://github.com/wesleysimplicio/simplicio-mapper/issues/131),
spec `.specs/product/flow-documentation-spec.md`): ten commands that turn the
mapper's structural artifacts into technical + business flow documentation
that stays in sync with the code and keeps history.

- `simplicio-mapper flows` — stack-neutral end-to-end flow inventory derived
  from the call graph (`simplicio.flow-inventory/v1`), generalizing the
  web-only `flowchart` command. [#133]
- `simplicio-mapper sync` — diff-driven docs sync. [#136]

### Changed

- `.specs/sprints/BACKLOG.md` now tracks this product's real backlog
  (rastreável via GitHub Issues) instead of generic template placeholder
  content.
"""

REAL_EXCERPT_0_11_0_NESTED_BULLETS = """\
## [0.11.0] - 2026-06-29

### Added
- Tier 3 niche/basic language support in the mapper (Python + Node mirror):
  - **Elixir, Erlang, Lua, R, Julia, Perl, MATLAB** — language detection,
    lightweight symbol extraction, dedicated import parsing, and inclusion in
    the heuristic call graph.
  - **HTML templates / basic web text** — `.heex/.leex/.eex/.erb`,
    `.html/.htm/.xhtml`, and `.css/.scss/.sass/.less` are now inventoried.
"""

REAL_EXCERPT_LINK_REFS = """\
## [0.1.6] - 2026-05-15

### Added
- Rock backing track on the Why explainer video. ([#14](https://github.com/wesleysimplicio/llm-project-mapper/pull/14))

[Unreleased]: https://github.com/wesleysimplicio/simplicio-mapper/compare/v0.19.0...HEAD
[0.19.0]: https://github.com/wesleysimplicio/simplicio-mapper/compare/v0.18.0...v0.19.0

## Unreleased / In Progress (EVT Alignment Work)

### Improvements to mapper for real enterprise monorepos
- Enhanced C# symbol extraction to detect ASP.NET controllers.
"""

# The *actual*, currently-committed garbled line 518 of this repo's own
# CHANGELOG.md (see the module docstring's "known, documented limitation").
# Copied verbatim, literal backtick-n sequences and all -- this is real,
# already-existing content, not a synthetic edge case invented for the test.
REAL_EXCERPT_KNOWN_GARBLED_UNRELEASED_LINE = (
    "## [Unreleased]`n`n## [0.21.0] - 2026-07-11`n`n### Added`n`n"
    "- Incremental graph deltas, clustering metrics, and "
    "Mapper-to-Canvas compatibility fixtures.`n"
)


class ParseChangelogUnitTest(unittest.TestCase):
    """Unit: parser correctness against real, existing CHANGELOG.md entries."""

    def test_parses_version_and_date(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_0_22_0)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["version"], "0.22.0")
        self.assertEqual(entries[0]["date"], "2026-07-12")

    def test_parses_multiple_sections_faithfully(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_0_22_0)
        sections = entries[0]["sections"]
        self.assertIn("Added", sections)
        self.assertIn("Fixed", sections)
        self.assertEqual(
            sections["Added"],
            [
                "Persistent, token-budgeted retrieval indexing for task context selection (issue #199).",
                "Stable retrieval-index receipts for downstream dev-cli consumers.",
            ],
        )
        self.assertEqual(
            sections["Fixed"], ["Safe recovery of orphaned mapper index locks."]
        )

    def test_parses_multiple_entries_in_file_order(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_0_24_1_AND_0_24_0)
        versions = [entry["version"] for entry in entries]
        self.assertEqual(versions, ["0.24.1", "0.24.0", "0.23.1"])

    def test_ad_hoc_section_heading_is_preserved_verbatim(self) -> None:
        # "Release process notes (issue #233)" is not one of the four Keep
        # a Changelog categories -- the parser must not restrict to a fixed
        # section-name set.
        entries = parse_changelog(REAL_EXCERPT_0_24_1_AND_0_24_0)
        entry_0_24_1 = entries[0]
        self.assertIn("Release process notes (issue #233)", entry_0_24_1["sections"])
        items = entry_0_24_1["sections"]["Release process notes (issue #233)"]
        self.assertEqual(len(items), 2)
        self.assertIn("Root cause of the drift", items[0])
        self.assertIn("0.23.1", items[1])

    def test_wrapped_bullet_lines_join_into_one_item(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_0_24_1_AND_0_24_0)
        fixed_items = entries[0]["sections"]["Fixed"]
        self.assertEqual(len(fixed_items), 1)
        # No literal newline/double-space artifacts from the wrapped source.
        self.assertNotIn("\n", fixed_items[0])
        self.assertIn("simplicio_mapper/cli/_status_engine.py", fixed_items[0])
        self.assertIn("issue #233", fixed_items[0])

    def test_preamble_prose_before_first_bullet_is_captured(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_0_14_0_PREAMBLE)
        added = entries[0]["sections"]["Added"]
        # First item is the prose paragraph, not a bullet.
        self.assertTrue(added[0].startswith("Flow Documentation Engine"))
        self.assertIn("`simplicio-mapper flows`", added[1])
        self.assertIn("`simplicio-mapper sync`", added[2])
        self.assertEqual(
            entries[0]["sections"]["Changed"],
            [
                "`.specs/sprints/BACKLOG.md` now tracks this product's real backlog "
                "(rastreável via GitHub Issues) instead of generic template placeholder "
                "content."
            ],
        )

    def test_nested_bullets_are_folded_into_parent_item_text(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_0_11_0_NESTED_BULLETS)
        items = entries[0]["sections"]["Added"]
        self.assertEqual(len(items), 1)
        self.assertIn("Elixir, Erlang, Lua, R, Julia, Perl, MATLAB", items[0])
        self.assertIn("HTML templates / basic web text", items[0])

    def test_link_reference_definitions_are_skipped_not_attached(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_LINK_REFS)
        self.assertEqual(len(entries), 1)
        added = entries[0]["sections"]["Added"]
        self.assertEqual(len(added), 1)
        self.assertNotIn("compare/v0.19.0", " ".join(added))

    def test_non_bracketed_level2_heading_ends_entry_without_becoming_one(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_LINK_REFS)
        # "## Unreleased / In Progress (EVT Alignment Work)" must not appear
        # as a parsed entry, and its content must not leak into 0.1.6.
        versions = [entry["version"] for entry in entries]
        self.assertEqual(versions, ["0.1.6"])
        self.assertNotIn(
            "Enhanced C# symbol extraction",
            " ".join(entries[0]["sections"].get("Added", [])),
        )

    def test_empty_text_yields_no_entries(self) -> None:
        self.assertEqual(parse_changelog(""), [])

    def test_known_garbled_unreleased_line_does_not_crash_and_is_faithful(self) -> None:
        # Regression test pinned to this repo's own real, currently-existing
        # formatting bug (see module docstring). The parser must degrade
        # safely -- one "Unreleased" entry whose preamble contains the
        # garbled literal text -- rather than crash or silently drop it.
        entries = parse_changelog(REAL_EXCERPT_KNOWN_GARBLED_UNRELEASED_LINE)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["version"], "Unreleased")
        self.assertIsNone(entries[0]["date"])
        preamble = " ".join(entries[0]["sections"].get("_preamble", []))
        self.assertIn("0.21.0", preamble)
        self.assertIn("Incremental graph deltas", preamble)


class FindLatestEntryUnitTest(unittest.TestCase):
    def test_returns_leading_unreleased_entry_when_present(self) -> None:
        entries = [
            {"version": "Unreleased", "date": None, "sections": {}},
            {"version": "0.24.1", "date": "2026-07-18", "sections": {}},
        ]
        latest = find_latest_entry(entries)
        self.assertEqual(latest["version"], "Unreleased")

    def test_returns_first_entry_in_file_order(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_0_24_1_AND_0_24_0)
        latest = find_latest_entry(entries)
        self.assertEqual(latest["version"], "0.24.1")

    def test_does_not_hijack_on_a_mid_file_unreleased_entry(self) -> None:
        # Regression: this repo's own CHANGELOG.md has a stray, pre-existing
        # `## [Unreleased]` heading mid-file (see module docstring). Latest
        # must stay the true first/newest entry, not that stray heading.
        entries = [
            {"version": "0.24.1", "date": "2026-07-18", "sections": {}},
            {"version": "Unreleased", "date": None, "sections": {}},
        ]
        latest = find_latest_entry(entries)
        self.assertEqual(latest["version"], "0.24.1")

    def test_returns_none_for_empty_list(self) -> None:
        self.assertIsNone(find_latest_entry([]))


class RollbackHintUnitTest(unittest.TestCase):
    def test_points_to_the_next_real_previous_version(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_0_24_1_AND_0_24_0)
        hint = build_rollback_hint(entries, 0)
        self.assertEqual(hint["previous_version"], "0.24.0")
        self.assertEqual(hint["pattern"], "pip install simplicio-mapper==0.24.0")
        self.assertIn("ADR-010", hint["note"])

    def test_skips_over_an_unreleased_sibling(self) -> None:
        entries = [
            {"version": "Unreleased", "date": None, "sections": {}},
            {"version": "0.24.1", "date": "2026-07-18", "sections": {}},
        ]
        hint = build_rollback_hint(entries, 0)
        self.assertEqual(hint["previous_version"], "0.24.1")

    def test_oldest_entry_has_no_previous_version(self) -> None:
        entries = parse_changelog(REAL_EXCERPT_0_22_0)
        hint = build_rollback_hint(entries, 0)
        self.assertIsNone(hint["pattern"])
        self.assertIsNone(hint["previous_version"])


class MigrationSignalUnitTest(unittest.TestCase):
    """Unit: the schema-compat cross-reference, isolated from git state."""

    def test_reports_classifier_error_as_structured_field_not_raised(self) -> None:
        with mock.patch(
            "simplicio_mapper.schema_compat.classify_release_changes",
            side_effect=SchemaCompatError("no previous release tag found"),
        ):
            signal = build_migration_signal(root=str(ROOT))
        self.assertIsNone(signal["overall"])
        self.assertIn("no previous release tag", signal["error"])

    def test_passes_through_a_real_classification_shape(self) -> None:
        fake_report = {
            "schema": "simplicio.schema-compat-report/v1",
            "against_ref": "v0.24.0",
            "overall": "compatible",
            "surfaces": [{"surface": "project-map", "classification": "compatible", "reasons": [], "kind": "json-schema", "path": "x"}],
        }
        with mock.patch(
            "simplicio_mapper.schema_compat.classify_release_changes",
            return_value=fake_report,
        ):
            signal = build_migration_signal(root=str(ROOT))
        self.assertIsNone(signal["error"])
        self.assertEqual(signal["overall"], "compatible")
        self.assertEqual(signal["against_ref"], "v0.24.0")
        self.assertEqual(len(signal["surfaces"]), 1)


class LoadChangelogEntriesIntegrationTest(unittest.TestCase):
    """Integration: parse the actual committed CHANGELOG.md end to end."""

    def test_loads_real_changelog_and_finds_known_versions(self) -> None:
        entries, resolved_path = load_changelog_entries(root=str(ROOT))
        self.assertTrue(resolved_path.endswith("CHANGELOG.md"))
        versions = {entry["version"] for entry in entries}
        for known_version in ("0.24.1", "0.24.0", "0.23.1", "0.22.0", "0.14.0"):
            self.assertIn(known_version, versions)

    def test_missing_changelog_file_raises_parse_error(self) -> None:
        with self.assertRaises(ChangelogParseError):
            load_changelog_entries(path=str(ROOT / "does-not-exist-CHANGELOG.md"))

    def test_real_0_24_1_entry_matches_committed_content(self) -> None:
        entries, _ = load_changelog_entries(root=str(ROOT))
        entry = find_entry_by_version({"entries": entries}, "0.24.1")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["date"], "2026-07-18")
        self.assertIn("Fixed", entry["sections"])


class BuildChangelogReportSystemTest(unittest.TestCase):
    """System: build_changelog_report() against the real repo checkout."""

    def test_report_shape_and_latest_gets_migration(self) -> None:
        report = build_changelog_report(root=str(ROOT))
        self.assertEqual(report["schema"], CHANGELOG_REPORT_SCHEMA)
        self.assertGreater(report["entry_count"], 0)
        self.assertEqual(len(report["entries"]), report["entry_count"])
        latest = report["entries"][0]
        self.assertEqual(latest["version"], report["latest_version"])
        self.assertIn("migration", latest)
        self.assertIn("rollback_hint", latest)
        # A non-latest entry never gets a "migration" key -- that
        # cross-reference is only meaningful for the current version.
        self.assertNotIn("migration", report["entries"][-1])
        self.assertIn("rollback_hint", report["entries"][-1])

    def test_include_migration_false_skips_the_classifier_call(self) -> None:
        with mock.patch.object(
            changelog_parser_module, "build_migration_signal"
        ) as mocked:
            report = build_changelog_report(root=str(ROOT), include_migration=False)
        mocked.assert_not_called()
        self.assertNotIn("migration", report["entries"][0])

    def test_find_entry_by_version_is_case_insensitive(self) -> None:
        report = build_changelog_report(root=str(ROOT), include_migration=False)
        entry = find_entry_by_version(report, "0.24.1")
        self.assertIsNotNone(entry)
        entry_upper = find_entry_by_version(report, "0.24.1".upper())
        self.assertIsNotNone(entry_upper)

    def test_find_entry_by_version_returns_none_for_unknown_version(self) -> None:
        report = build_changelog_report(root=str(ROOT), include_migration=False)
        self.assertIsNone(find_entry_by_version(report, "999.999.999"))


class RunChangelogCliTest(unittest.TestCase):
    """System: real CLI invocation via simplicio_mapper.cli.main()."""

    def test_json_output_is_valid_and_matches_schema(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["changelog", "--json", "--root", str(ROOT), "--no-migration"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["schema"], CHANGELOG_REPORT_SCHEMA)
        self.assertGreater(len(payload["entries"]), 5)

    def test_version_filter_returns_single_entry(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = main(
                ["changelog", "--json", "--root", str(ROOT), "--version", "0.22.0", "--no-migration"]
            )
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(payload["entries"][0]["version"], "0.22.0")

    def test_unknown_version_filter_exits_nonzero(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = run_changelog_cli(
                ["--root", str(ROOT), "--version", "999.999.999", "--no-migration"]
            )
        self.assertEqual(exit_code, 1)

    def test_root_flag_without_value_exits_with_usage_error(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = run_changelog_cli(["--root"])
        self.assertEqual(exit_code, 2)

    def test_version_flag_without_value_exits_with_usage_error(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            exit_code = run_changelog_cli(["--version"])
        self.assertEqual(exit_code, 2)

    def test_parse_error_is_reported_not_raised(self) -> None:
        with mock.patch.object(
            changelog_parser_module,
            "build_changelog_report",
            side_effect=ChangelogParseError("boom"),
        ):
            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = run_changelog_cli([])
        self.assertEqual(exit_code, 1)

    def test_human_readable_output_includes_rollback_and_migration_lines(self) -> None:
        fake_report = {
            "schema": CHANGELOG_REPORT_SCHEMA,
            "source_path": "CHANGELOG.md",
            "generated_at": "2026-07-18T00:00:00Z",
            "entry_count": 1,
            "latest_version": "1.2.3",
            "entries": [
                {
                    "version": "1.2.3",
                    "date": "2026-07-18",
                    "sections": {"Fixed": ["Something."]},
                    "rollback_hint": {
                        "pattern": "pip install simplicio-mapper==1.2.2",
                        "previous_version": "1.2.2",
                        "note": "x",
                    },
                    "migration": {"overall": "compatible", "against_ref": "v1.2.2", "error": None},
                }
            ],
        }
        with mock.patch.object(
            changelog_parser_module, "build_changelog_report", return_value=fake_report
        ):
            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = run_changelog_cli([])
        self.assertEqual(exit_code, 0)
        output = buffer.getvalue()
        self.assertIn("[1.2.3]", output)
        self.assertIn("rollback: pip install simplicio-mapper==1.2.2", output)
        self.assertIn("migration: compatible (against v1.2.2)", output)

    def test_module_entrypoint_runs_via_real_subprocess(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.changelog_parser", "--json", "--no-migration"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], CHANGELOG_REPORT_SCHEMA)


if __name__ == "__main__":
    unittest.main()
