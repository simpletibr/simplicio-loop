"""``simplicio-mapper changelog`` -- machine-readable changelog extractor
(issue #280, Release Train, step 9: "produzir changelog machine-readable
com migration/rollback").

This module is an **extractor**, not a generator: it parses the existing,
human-maintained ``CHANGELOG.md`` (Keep a Changelog 1.1.0 format, already
used consistently across this repo's whole history) into a structured list
of ``{"version", "date", "sections", ...}`` entries. It never fabricates or
infers changelog content -- every string in the output is copied verbatim
(modulo whitespace normalization of wrapped Markdown paragraphs) from
``CHANGELOG.md`` itself.

Two derived, non-fabricated fields close the rest of step 9:

- ``migration`` (computed only for the current/latest entry): a direct
  cross-reference into the already-merged
  :mod:`simplicio_mapper.schema_compat` classifier
  (``classify_release_changes()``), answering "does the current working
  tree contain a schema-breaking change relative to the previous release
  tag?" -- this *is* the migration signal step 9 asks for, derived from a
  module that already exists, not invented here.
- ``rollback_hint`` (computed for every entry that has an earlier sibling):
  a structured pointer to the standard, generically-true
  ``pip install simplicio-mapper==<previous-version>`` pattern. This repo
  has no release-train/canary/rollback orchestration infrastructure yet
  (see ``.specs/architecture/ADR-010-release-manifest-phase0.md``, "Fora de
  escopo" section) -- inventing fake rollback tooling here would misstate
  what actually exists. The hint is deliberately limited to the one fact
  that is true regardless of any orchestration: PyPI lets you pin an older
  version.

Known, documented limitation: a stray, pre-existing formatting bug on the
``## [Unreleased]`` line of this repo's own ``CHANGELOG.md`` (literal
backtick-escaped ``\\n`` sequences instead of real newlines, likely from a
shell/PowerShell heredoc mistake in an earlier session) means the
``0.21.0`` entry's real content is embedded as raw preamble text inside the
``Unreleased`` entry instead of being its own parsed entry. This parser
does not attempt to "fix" that -- reinterpreting garbled bytes as intended
structure would itself be a fabrication. It is called out explicitly here,
and a fix to ``CHANGELOG.md`` itself is left as a separate, out-of-scope
change (see the parser's own test suite for a regression test pinned to
this exact known-bad input, proving the parser degrades safely rather than
crashing or silently dropping the rest of the file).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys

CHANGELOG_REPORT_SCHEMA = "simplicio.changelog-report/v1"

PYPI_PACKAGE = "simplicio-mapper"

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_PACKAGE_DIR)

DEFAULT_CHANGELOG_PATH = os.path.join(REPO_ROOT, "CHANGELOG.md")

_UNRELEASED_NAMES = {"unreleased"}

# ``## [X.Y.Z] - YYYY-MM-DD`` or ``## [Unreleased]`` (date optional). Uses
# ``re.match`` (start-anchored, no end-anchor) rather than a fully anchored
# pattern so a malformed line that runs on past the heading (see module
# docstring's known-limitation note) is still recognized as *starting* a
# new entry instead of being missed entirely -- any trailing text on that
# same physical line is preserved verbatim as the entry's leading preamble
# content, never silently discarded.
_VERSION_HEADING_RE = re.compile(
    r"^## \[(?P<version>[^\]]+)\]\s*(?:-\s*(?P<date>\d{4}-\d{2}-\d{2}))?"
)

# ``### Added`` / ``### Fixed`` / ``### Release process notes (issue #233)``
# -- this repo uses ad hoc section names beyond the four Keep a Changelog
# categories (see CHANGELOG.md's "Release process notes (issue #233)" and
# "Notes" sections), so the parser does not restrict section names to a
# fixed set; it faithfully records whatever heading text is actually there.
_SECTION_HEADING_RE = re.compile(r"^### (?P<name>.+?)\s*$")

# A top-level bullet starts at column 0 with "- ". Anything indented
# (wrapped continuation text, or a nested sub-bullet like the Tier-3
# language list in the 0.11.0 entry) is treated as part of the same item's
# text rather than a new item -- this repo's changelog never nests two
# *independent* top-level facts under one bullet, only elaboration.
_TOP_BULLET_RE = re.compile(r"^-\s+(?P<text>.*)$")

# Markdown reference-style link definitions (`[X]: https://...`) that Keep
# a Changelog puts at the bottom of the file. These are not changelog
# content -- skipping them keeps them from being misattributed as a
# trailing bullet/paragraph of whatever entry precedes them in the file.
_LINK_REF_RE = re.compile(r"^\[[^\]]+\]:\s*\S+")

_PREAMBLE_KEY = "_preamble"


class ChangelogParseError(RuntimeError):
    """Raised when the changelog file cannot be read at all."""


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_changelog(text: str) -> list[dict]:
    """Parse ``CHANGELOG.md`` text into a list of structured entries.

    Each entry is ``{"version": str, "date": str | None, "sections": dict}``
    where ``sections`` maps a section heading (``"Added"``, ``"Fixed"``,
    or any ad hoc heading this repo actually uses) to a list of item
    strings, each one a whitespace-collapsed, faithfully-copied bullet or
    paragraph. A ``"_preamble"`` section key holds any content that
    appears directly under the version heading before the first ``### ``
    subheading (e.g. the prose intro in the 0.14.0/0.15.0 entries).

    Entries are returned in file order (this repo's ``CHANGELOG.md`` is
    newest-first, per Keep a Changelog convention). Any ``## `` heading
    that is *not* a ``## [version]`` heading (e.g. this repo's stray
    ``## Unreleased / In Progress (EVT Alignment Work)`` section near the
    end of the file, which predates the versioned-entries convention and
    is not itself inside a bracketed version) ends whatever entry was
    being collected and is not itself parsed as an entry.
    """
    entries: list[dict] = []
    current: dict | None = None
    current_section: str | None = None
    buffer: list[str] = []

    def flush_item() -> None:
        nonlocal buffer
        if current is not None and buffer:
            item = _collapse_whitespace(" ".join(buffer))
            if item:
                current["sections"].setdefault(current_section or _PREAMBLE_KEY, []).append(item)
        buffer = []

    for line in text.splitlines():
        version_match = _VERSION_HEADING_RE.match(line)
        if version_match:
            flush_item()
            if current is not None:
                entries.append(current)
            version = version_match.group("version").strip()
            date = version_match.group("date")
            current = {"version": version, "date": date, "sections": {}}
            current_section = _PREAMBLE_KEY
            remainder = line[version_match.end():].strip()
            if remainder:
                buffer = [remainder]
                flush_item()
            continue

        if line.startswith("## "):
            # Non-bracketed level-2 heading: ends the current entry (if
            # any) without becoming an entry itself.
            flush_item()
            if current is not None:
                entries.append(current)
            current = None
            current_section = None
            buffer = []
            continue

        if current is None:
            # Outside any version entry (before the first heading, or
            # after a non-version "## " heading) -- nothing to attach
            # this line to.
            continue

        if _LINK_REF_RE.match(line):
            # Reference-style link definitions are not changelog content.
            continue

        section_match = _SECTION_HEADING_RE.match(line)
        if section_match:
            flush_item()
            current_section = section_match.group("name").strip()
            current["sections"].setdefault(current_section, [])
            continue

        if not line.strip():
            flush_item()
            continue

        bullet_match = _TOP_BULLET_RE.match(line) if line == line.lstrip() else None
        if bullet_match:
            flush_item()
            buffer = [bullet_match.group("text")]
            continue

        buffer.append(line.strip())

    flush_item()
    if current is not None:
        entries.append(current)

    # Drop empty "_preamble" keys that were only ever created as a
    # placeholder (setdefault in the section-heading branch never adds to
    # "_preamble", only real headings do) -- keeps output clean without
    # ever hiding real content.
    for entry in entries:
        if _PREAMBLE_KEY in entry["sections"] and not entry["sections"][_PREAMBLE_KEY]:
            del entry["sections"][_PREAMBLE_KEY]

    return entries


def _is_unreleased(version: str) -> bool:
    return version.strip().lower() in _UNRELEASED_NAMES


def find_latest_entry(entries: list[dict]) -> dict | None:
    """Return the entry representing the current/latest release.

    Returns the first entry in file order, since this repo's
    ``CHANGELOG.md`` is maintained newest-first (every real release entry
    confirms this: 0.24.1 precedes 0.24.0 precedes 0.23.1, ...) and, per
    Keep a Changelog convention, an ``## [Unreleased]`` entry (when present
    and genuinely current) always leads the file rather than appearing
    mid-history.

    Deliberately does *not* search the whole list for an ``Unreleased``
    entry wherever it happens to appear: this repo's own ``CHANGELOG.md``
    currently has a stray, pre-existing ``## [Unreleased]`` heading buried
    mid-file (see the module docstring's known-limitation note) that is
    *not* the current release boundary -- treating any ``Unreleased``
    match as authoritative regardless of position would let that
    formatting bug silently hijack the migration/rollback cross-reference.
    """
    return entries[0] if entries else None


def build_rollback_hint(entries: list[dict], index: int) -> dict | None:
    """Build the ``pip install <pkg>==<previous>`` rollback hint for ``entries[index]``.

    Returns ``None`` when there is no earlier, real (non-"Unreleased")
    version in the list to roll back to -- never invents a version number.
    """
    for candidate in entries[index + 1:]:
        if _is_unreleased(candidate["version"]):
            continue
        previous_version = candidate["version"]
        return {
            "pattern": f"pip install {PYPI_PACKAGE}=={previous_version}",
            "previous_version": previous_version,
            "note": (
                "Generic PyPI version-pin rollback only -- this repo has no "
                "automated release-train/canary rollback orchestration yet "
                "(see .specs/architecture/ADR-010-release-manifest-phase0.md, "
                "'Fora de escopo' section). This is a real, generically-true "
                "fact about how PyPI installs work, not project-specific "
                "tooling."
            ),
        }
    return {
        "pattern": None,
        "previous_version": None,
        "note": "No earlier published version found in CHANGELOG.md to roll back to.",
    }


def build_migration_signal(root: str | None = None) -> dict:
    """Cross-reference the current working tree against
    :mod:`simplicio_mapper.schema_compat` to answer "is the current/latest
    changelog entry schema-breaking?" -- the migration signal for step 9.

    Never raises: a classifier failure (no previous release tag, malformed
    schema JSON, not a git checkout, ...) is reported as a structured
    ``error`` field rather than propagating and failing the whole
    ``changelog`` command, since a changelog listing should degrade
    gracefully, not crash, when the (optional) cross-reference is
    unavailable.
    """
    from . import schema_compat  # local import: avoid a hard dependency for callers that only need parsing

    try:
        report = schema_compat.classify_release_changes(root=root)
    except schema_compat.SchemaCompatError as error:
        return {
            "schema": schema_compat.SCHEMA_COMPAT_REPORT_SCHEMA,
            "overall": None,
            "against_ref": None,
            "surfaces": [],
            "error": str(error),
        }
    return {
        "schema": report["schema"],
        "overall": report["overall"],
        "against_ref": report["against_ref"],
        "surfaces": report["surfaces"],
        "error": None,
    }


def load_changelog_entries(root: str | None = None, path: str | None = None) -> tuple[list[dict], str]:
    """Read + parse ``CHANGELOG.md``. Returns ``(entries, resolved_path)``."""
    resolved_path = path or os.path.join(os.path.abspath(root or REPO_ROOT), "CHANGELOG.md")
    try:
        with open(resolved_path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        raise ChangelogParseError(f"cannot read changelog at {resolved_path!r}: {error}") from error
    return parse_changelog(text), resolved_path


def build_changelog_report(
    root: str | None = None, path: str | None = None, include_migration: bool = True
) -> dict:
    """Build the full ``simplicio.changelog-report/v1`` payload.

    Every entry gets a ``rollback_hint``; only the latest/current entry
    (see :func:`find_latest_entry`) additionally gets a ``migration``
    cross-reference against :mod:`simplicio_mapper.schema_compat` (set
    ``include_migration=False`` to skip the git-dependent classifier call,
    e.g. for fast unit tests that only care about parsing).
    """
    entries, resolved_path = load_changelog_entries(root=root, path=path)
    latest = find_latest_entry(entries)

    for index, entry in enumerate(entries):
        entry["rollback_hint"] = build_rollback_hint(entries, index)

    if latest is not None and include_migration:
        latest["migration"] = build_migration_signal(root=root)

    return {
        "schema": CHANGELOG_REPORT_SCHEMA,
        "source_path": resolved_path,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "entry_count": len(entries),
        "latest_version": latest["version"] if latest else None,
        "entries": entries,
    }


def find_entry_by_version(report: dict, version: str) -> dict | None:
    for entry in report["entries"]:
        if entry["version"].strip().lower() == version.strip().lower():
            return entry
    return None


def run_changelog_cli(argv: list[str]) -> int:
    """Entry point for ``simplicio-mapper changelog [--json] [--version X.Y.Z] [--root DIR] [--no-migration]``.

    ``--version`` filters the report down to a single entry (still carries
    its ``rollback_hint``; carries ``migration`` too only when that entry
    is also the current/latest one). ``--no-migration`` skips the
    schema-compat cross-reference entirely (useful when no git tags exist
    yet, e.g. a first checkout, to avoid a noisy but harmless error field).
    """
    as_json = "--json" in argv
    include_migration = "--no-migration" not in argv
    root = REPO_ROOT
    version_filter = None

    if "--root" in argv:
        idx = argv.index("--root")
        try:
            root = argv[idx + 1]
        except IndexError:
            print("--root requires a directory", file=sys.stderr)
            return 2
    if "--version" in argv:
        idx = argv.index("--version")
        try:
            version_filter = argv[idx + 1]
        except IndexError:
            print("--version requires a value (e.g. --version 0.24.1)", file=sys.stderr)
            return 2

    try:
        report = build_changelog_report(root=root, include_migration=include_migration)
    except ChangelogParseError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    if version_filter is not None:
        entry = find_entry_by_version(report, version_filter)
        if entry is None:
            print(f"::error::no changelog entry found for version {version_filter!r}", file=sys.stderr)
            return 1
        payload: dict = dict(report)
        payload["entries"] = [entry]
        report = payload

    if as_json:
        # ensure_ascii=True (unlike the other `simplicio-mapper` JSON CLIs):
        # this payload embeds free-form human-written changelog prose,
        # which can contain arbitrary Unicode (arrows, em dashes, curly
        # quotes) that a non-UTF-8 stdout codepage (e.g. Windows cp1252,
        # the default for a redirected/piped console) cannot encode --
        # escaping to \uXXXX keeps the JSON valid and the CLI portable
        # without requiring callers to reconfigure their terminal encoding.
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0

    for entry in report["entries"]:
        print(f"[{entry['version']}] - {entry['date'] or '(no date)'}")
        for section_name, items in entry["sections"].items():
            print(f"  {section_name}:")
            for item in items:
                print(f"    - {item}")
        hint = entry.get("rollback_hint") or {}
        if hint.get("pattern"):
            print(f"  rollback: {hint['pattern']}")
        migration = entry.get("migration")
        if migration is not None:
            if migration.get("error"):
                print(f"  migration: (unavailable) {migration['error']}")
            else:
                print(f"  migration: {migration['overall']} (against {migration['against_ref']})")
    return 0


if __name__ == "__main__":
    sys.exit(run_changelog_cli(sys.argv[1:]))
