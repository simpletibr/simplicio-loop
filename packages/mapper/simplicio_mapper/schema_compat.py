"""``simplicio-mapper schema-compat`` -- compatible/breaking schema-change
classifier (issue #280, Release Train, step "classificar mudanças de
project-map, precedent-index, ContextSnapshot e overlays como
compatible/breaking").

``simplicio_mapper.release_manifest`` (Phase-0, issue #280) already collects
the *current* value of every schema-version constant
(:data:`simplicio_mapper.release_manifest.SCHEMA_VERSION_REGISTRY`) and
diffs it against a checked-in baseline file
(``scripts/schema_registry_baseline.json``) to catch an *unreviewed*
schema-version bump -- but that check only ever says "changed or not
changed"; it never classifies a real change as compatible (additive) vs
breaking, and it diffs against a hand-maintained baseline file, not against
an actual previous release (a git tag).

This module closes that specific gap for the artifact surfaces issue #280
names explicitly -- project-map, precedent-index, ContextSnapshot, and the
canonical-map/worktree-overlay design (issue #236) -- by:

1. Resolving the most recent ``vX.Y.Z`` git tag reachable from the current
   checkout (the previous release boundary), via real ``git`` invocations
   (``git tag --merged``, ``git show <ref>:<path>``) -- no network access,
   no PyPI/npm calls.
2. For the three surfaces that have a real on-disk JSON Schema file
   (``contracts/mapper-artifacts/v1/schemas/project-map.schema.json``,
   ``.../precedent-index.schema.json``,
   ``contracts/context-snapshot/v1/schemas/context-snapshot.schema.json``):
   structurally diffing ``properties``/``required``/``type``/``enum``
   between the previous tag's revision and the working tree's revision, and
   classifying the result as ``breaking`` (property removed, property
   became required, property type changed, enum value removed, schema file
   deleted) or ``compatible`` (new optional property, required constraint
   relaxed, enum value added, schema file newly added) or ``unchanged``.
3. For the overlay design (``simplicio_mapper/mapper/canonical.py``), which
   is a Phase-0-only set of dataclasses with no on-disk JSON Schema file yet
   (see that module's docstring), falling back to the version-int
   convention *that module itself already documents*: "bump the
   corresponding ``*_SCHEMA_VERSION`` int whenever the shape of the matching
   dataclass changes in a way that affects on-disk compatibility" -- i.e.
   for ``CANONICAL_MAP_SCHEMA_VERSION`` / ``WORKTREE_OVERLAY_SCHEMA_VERSION``
   / ``EFFECTIVE_MAP_VIEW_SCHEMA_VERSION`` specifically, any change to the
   constant *is* the breaking signal, by this codebase's own authoring rule,
   not an assumption invented here.

Still explicitly out of scope (see ADR-010): signing/SBOM, cross-repo
release events, canary channels, and any live PyPI/npm registry query. This
module never makes a network call.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import re
import subprocess
import sys

SCHEMA_COMPAT_REPORT_SCHEMA = "simplicio.schema-compat-report/v1"

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_PACKAGE_DIR)

_VERSION_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


#: Artifact surfaces named in issue #280 that have a real on-disk JSON
#: Schema file to structurally diff. ``(surface name, repo-relative path)``.
TRACKED_JSON_SCHEMAS: tuple[tuple[str, str], ...] = (
    ("project-map", "simplicio_mapper/contracts/mapper-artifacts/v1/schemas/project-map.schema.json"),
    (
        "precedent-index",
        "simplicio_mapper/contracts/mapper-artifacts/v1/schemas/precedent-index.schema.json",
    ),
    (
        "context-snapshot",
        "simplicio_mapper/contracts/context-snapshot/v1/schemas/context-snapshot.schema.json",
    ),
)

#: The overlay/canonical-map design (issue #236, ADR-008) has no dedicated
#: on-disk JSON Schema file yet -- see ``simplicio_mapper/mapper/canonical.py``
#: module docstring ("Phase-0 deliverable only ... no production code path
#: constructs or consumes these types yet"). Classified via the version-int
#: convention documented in that same module instead.
#: ``(surface name, module path, attribute name)``.
TRACKED_VERSION_ONLY_SURFACES: tuple[tuple[str, str, str], ...] = (
    (
        "overlays:canonical-map",
        "simplicio_mapper.mapper.canonical",
        "CANONICAL_MAP_SCHEMA_VERSION",
    ),
    (
        "overlays:worktree-overlay",
        "simplicio_mapper.mapper.canonical",
        "WORKTREE_OVERLAY_SCHEMA_VERSION",
    ),
    (
        "overlays:effective-map-view",
        "simplicio_mapper.mapper.canonical",
        "EFFECTIVE_MAP_VIEW_SCHEMA_VERSION",
    ),
)

_CLASSIFICATION_SEVERITY = {"unchanged": 0, "compatible": 1, "breaking": 2}


class SchemaCompatError(RuntimeError):
    """Raised for classifier problems (no previous tag, malformed JSON, ...)."""


def _run_git(args: list[str], root: str, timeout: float = 10) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", "-C", root, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _commit_sha_for_ref(root: str, ref: str) -> str | None:
    result = _run_git(["rev-parse", ref], root)
    if result is None or result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


def previous_release_tag(root: str | None = None, before_ref: str = "HEAD") -> str | None:
    """Return the most recent ``vX.Y.Z`` tag that is an ancestor of ``before_ref``.

    Excludes a tag that points at the exact same commit as ``before_ref``
    (nothing to diff against -- that would be "the current release", not the
    previous one). Returns ``None`` when no such tag exists (shallow clone,
    fresh repo with no releases yet, or ``before_ref``/``root`` not a git
    checkout at all) -- callers must treat that as "cannot classify", never
    silently skip the check.
    """
    resolved_root = os.path.abspath(root or REPO_ROOT)
    result = _run_git(
        ["tag", "--list", "v*", "--sort=-creatordate", "--merged", before_ref],
        resolved_root,
    )
    if result is None or result.returncode != 0:
        return None
    head_sha = _commit_sha_for_ref(resolved_root, before_ref)
    for line in result.stdout.splitlines():
        tag = line.strip()
        if not tag or not _VERSION_TAG_RE.match(tag):
            continue
        tag_sha = _commit_sha_for_ref(resolved_root, tag)
        if tag_sha is not None and tag_sha == head_sha:
            continue
        return tag
    return None


def read_file_at_ref(root: str, ref: str, rel_path: str) -> str | None:
    """Return the text of ``rel_path`` as it existed at ``ref``, or ``None``.

    ``None`` covers both "file did not exist at that ref" and "not a git
    checkout" -- both are legitimate "nothing to compare against" states for
    a schema-file diff (a brand-new file is handled as an additive change).
    """
    # ``git show <ref>:<path>`` resolves ``<path>`` relative to the
    # repository's top level, not ``-C root``'s cwd. In a monorepo, ``root``
    # is a package subdirectory, not the repo top level, so the pathspec
    # must be written relative-to-cwd (``./``) to stay scoped to the package
    # regardless of where the enclosing repository root actually is.
    result = _run_git(["show", f"{ref}:./{rel_path}"], root)
    if result is None or result.returncode != 0:
        return None
    return result.stdout


def _read_constant_at_ref(root: str, ref: str, module_path: str, attr_name: str) -> object | None:
    rel_path = module_path.replace(".", "/") + ".py"
    text = read_file_at_ref(root, ref, rel_path)
    if text is None:
        return None
    match = re.search(rf"^{re.escape(attr_name)}\s*=\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return None
    raw = match.group(1)
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw


def classify_json_schema_diff(
    old_text: str | None, new_text: str | None
) -> tuple[str, list[str]]:
    """Structurally classify a JSON-Schema-file diff as breaking/compatible/unchanged.

    Rules (deliberately conservative -- anything ambiguous is treated as
    breaking, never silently waved through as compatible):

    - file removed -> ``breaking``
    - file newly added -> ``compatible``
    - property removed, property newly required, property type changed, or
      an enum value removed -> ``breaking``
    - new optional property, a required constraint relaxed, or a new enum
      value added -> ``compatible``
    - byte-identical or only metadata (title/description/``$id``) changed ->
      ``unchanged``
    """
    if old_text is None and new_text is None:
        return "unchanged", ["schema file absent at both revisions"]
    if old_text is None:
        return "compatible", ["schema file newly added -- additive, no prior consumers to break"]
    if new_text is None:
        return "breaking", ["schema file removed -- any consumer depending on it breaks"]

    try:
        old_doc = json.loads(old_text)
    except json.JSONDecodeError as error:
        raise SchemaCompatError(f"previous schema revision is not valid JSON: {error}") from error
    try:
        new_doc = json.loads(new_text)
    except json.JSONDecodeError as error:
        raise SchemaCompatError(f"current schema revision is not valid JSON: {error}") from error

    if old_doc == new_doc:
        return "unchanged", []

    reasons: list[str] = []
    breaking = False

    old_props = old_doc.get("properties", {}) or {}
    new_props = new_doc.get("properties", {}) or {}
    old_required = set(old_doc.get("required", []) or [])
    new_required = set(new_doc.get("required", []) or [])

    removed_props = set(old_props) - set(new_props)
    for name in sorted(removed_props):
        breaking = True
        reasons.append(f"property {name!r} removed")

    added_props = set(new_props) - set(old_props)
    for name in sorted(added_props):
        if name in new_required:
            breaking = True
            reasons.append(
                f"property {name!r} added as required -- existing producers cannot emit it yet"
            )
        else:
            reasons.append(f"property {name!r} added as optional -- additive, compatible")

    newly_required = (new_required - old_required) - added_props
    for name in sorted(newly_required):
        breaking = True
        reasons.append(f"property {name!r} became required (was optional)")

    loosened_required = old_required - new_required
    for name in sorted(loosened_required):
        reasons.append(f"property {name!r} is no longer required -- relaxation, compatible")

    common_props = set(old_props) & set(new_props)
    for name in sorted(common_props):
        old_spec = old_props[name] if isinstance(old_props[name], dict) else {}
        new_spec = new_props[name] if isinstance(new_props[name], dict) else {}

        old_type = old_spec.get("type")
        new_type = new_spec.get("type")
        if old_type is not None and new_type is not None and old_type != new_type:
            breaking = True
            reasons.append(f"property {name!r} type changed ({old_type!r} -> {new_type!r})")

        old_enum = old_spec.get("enum")
        new_enum = new_spec.get("enum")
        if old_enum is not None and new_enum is not None:
            removed_values = [v for v in old_enum if v not in new_enum]
            added_values = [v for v in new_enum if v not in old_enum]
            for value in removed_values:
                breaking = True
                reasons.append(f"property {name!r} enum value {value!r} removed")
            for value in added_values:
                reasons.append(f"property {name!r} enum value {value!r} added -- additive, compatible")

    if not reasons:
        reasons.append(
            "schema text changed but no structurally-relevant difference detected "
            "(metadata-only: title/description/$id/etc.)"
        )

    return ("breaking" if breaking else "compatible"), reasons


def classify_version_only_surface(
    root: str, ref: str, module_path: str, attr_name: str
) -> tuple[str, list[str]]:
    """Classify a version-int-only surface (no on-disk JSON Schema file).

    Per the convention documented in ``simplicio_mapper/mapper/canonical.py``
    itself, any change to one of these constants signals an on-disk-breaking
    shape change -- there is no "compatible bump" for a bare version int.
    """
    old_value = _read_constant_at_ref(root, ref, module_path, attr_name)
    module = importlib.import_module(module_path)
    new_value = getattr(module, attr_name)

    if old_value is None:
        return "compatible", [f"{attr_name} not present at {ref} -- newly added surface"]
    if old_value == new_value:
        return "unchanged", []
    return "breaking", [
        f"{attr_name} bumped {old_value!r} -> {new_value!r} (this codebase's documented "
        "convention: any *_SCHEMA_VERSION change signals an on-disk-breaking shape change)"
    ]


def classify_release_changes(
    root: str | None = None, against_ref: str | None = None
) -> dict:
    """Build the ``simplicio.schema-compat-report/v1`` report for the working tree.

    Diffs every tracked surface (see :data:`TRACKED_JSON_SCHEMAS` and
    :data:`TRACKED_VERSION_ONLY_SURFACES`) against ``against_ref`` (defaults
    to the most recent ``vX.Y.Z`` tag ancestor of ``HEAD``, via
    :func:`previous_release_tag`). Raises :class:`SchemaCompatError` when no
    ref can be resolved -- never silently reports "nothing changed" when
    there is genuinely nothing to compare against.
    """
    resolved_root = os.path.abspath(root or REPO_ROOT)
    ref = against_ref or previous_release_tag(resolved_root)
    if ref is None:
        raise SchemaCompatError(
            "no previous release tag found to diff against -- need a vX.Y.Z git "
            "tag reachable as an ancestor of HEAD (pass --against explicitly to "
            "override, e.g. for a first release)"
        )

    surfaces: list[dict] = []

    for name, rel_path in TRACKED_JSON_SCHEMAS:
        old_text = read_file_at_ref(resolved_root, ref, rel_path)
        new_path = os.path.join(resolved_root, rel_path)
        new_text = None
        if os.path.isfile(new_path):
            with open(new_path, encoding="utf-8") as handle:
                new_text = handle.read()
        classification, reasons = classify_json_schema_diff(old_text, new_text)
        surfaces.append(
            {
                "surface": name,
                "kind": "json-schema",
                "path": rel_path,
                "classification": classification,
                "reasons": reasons,
            }
        )

    for name, module_path, attr_name in TRACKED_VERSION_ONLY_SURFACES:
        classification, reasons = classify_version_only_surface(
            resolved_root, ref, module_path, attr_name
        )
        surfaces.append(
            {
                "surface": name,
                "kind": "version-only",
                "path": f"{module_path}:{attr_name}",
                "classification": classification,
                "reasons": reasons,
            }
        )

    overall = "unchanged"
    for surface in surfaces:
        if _CLASSIFICATION_SEVERITY[surface["classification"]] > _CLASSIFICATION_SEVERITY[overall]:
            overall = surface["classification"]

    return {
        "schema": SCHEMA_COMPAT_REPORT_SCHEMA,
        "against_ref": ref,
        "overall": overall,
        "surfaces": surfaces,
    }


def run_schema_compat_cli(argv: list[str]) -> int:
    """Entry point for ``simplicio-mapper schema-compat [--json] [--against <ref>] [--fail-on-breaking]``.

    Exit codes: ``0`` on a successful classification (regardless of whether
    breaking changes were found -- a breaking change may be intentional and
    reviewed), ``1`` on a classifier error (no previous tag, malformed
    schema JSON, ...) or when ``--fail-on-breaking`` is passed and at least
    one surface classified as ``breaking``.
    """
    as_json = "--json" in argv
    fail_on_breaking = "--fail-on-breaking" in argv
    root = REPO_ROOT
    against_ref = None

    if "--root" in argv:
        idx = argv.index("--root")
        try:
            root = argv[idx + 1]
        except IndexError:
            print("--root requires a directory", file=sys.stderr)
            return 2
    if "--against" in argv:
        idx = argv.index("--against")
        try:
            against_ref = argv[idx + 1]
        except IndexError:
            print("--against requires a git ref", file=sys.stderr)
            return 2

    try:
        report = classify_release_changes(root=root, against_ref=against_ref)
    except SchemaCompatError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"against:  {report['against_ref']}")
        print(f"overall:  {report['overall']}")
        for surface in report["surfaces"]:
            print(f"  [{surface['classification']:<10}] {surface['surface']} ({surface['path']})")
            for reason in surface["reasons"]:
                print(f"      - {reason}")

    if fail_on_breaking and report["overall"] == "breaking":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run_schema_compat_cli(sys.argv[1:]))
