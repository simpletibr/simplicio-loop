"""component_manifest.py — parse/validate ``simplicio.component-release/v1``
manifests and check them against this repo's own declared compatibility
range (issue #232).

Context (verified in the issue): `simplicio-cli` declares
`simplicio-mapper>=0.23.1` in `pyproject.toml`, while the Mapper already
publishes 0.24.0/0.24.1. That range lets a *clean* install resolve to the
newer Mapper, but it never proves the combination was actually exercised,
and it never updates an *existing* environment/lock (this repo's own
`uv.lock` still pins `simplicio-mapper==0.23.1` — see
:func:`tested_mapper_version`). Issue #280 on the Mapper side (built by a
parallel agent, not visible from here) is expected to add a
``simplicio.component-release/v1`` manifest and a `simplicio-mapper version
--json` command on its side. This module is the Dev CLI's *consuming* half:

- :func:`parse_component_manifest` — turn a raw ``dict`` (however it
  arrives — file, stdin, a future event-bus payload) into a validated
  :class:`ComponentManifest`, raising :class:`ComponentManifestError` with a
  clear message on anything malformed.
- :func:`check_component_compatibility` — real semver-range logic deciding
  whether a candidate manifest's version is COMPATIBLE, INCOMPATIBLE, or
  NEEDS_REVIEW against a declared range (e.g. this repo's own
  ``simplicio-mapper>=0.23.1``), parsed for real out of `pyproject.toml`.
- :func:`build_own_manifest` — the reverse direction: build *this* repo's
  own ``simplicio.component-release/v1`` manifest (name=`simplicio-cli`,
  version from `pyproject.toml`/`__version__`, commit from
  ``git rev-parse HEAD``, schema_versions gathered from this repo's own
  ``*_SCHEMA`` constants) — the payload this component would publish on its
  own release (issue #232 item 9).
- :func:`detect_drift` — compare an installed version against a declared
  range plus (when available) the version this repo's lockfile last
  verified, and return a structured result a caller (`doctor`, `versions
  --json`) can act on without ever raising/blocking.

No network access, no event-bus client, and no PyPI/npm registry query live
here — see `simplicio/commands/versions.py` and the issue report for what
is explicitly out of scope and why.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

COMPONENT_MANIFEST_SCHEMA = "simplicio.component-release/v1"

# ---------------------------------------------------------------------------#
# Manifest parsing/validation
# ---------------------------------------------------------------------------#


class ComponentManifestError(ValueError):
    """Raised by :func:`parse_component_manifest` on malformed input.

    Always carries a human-readable reason (`str(exc)`) naming the exact
    field/shape problem — callers should never need to re-inspect the raw
    payload to explain a failure to a human or a log line.
    """


@dataclass(frozen=True)
class ComponentManifest:
    """A parsed, validated ``simplicio.component-release/v1`` manifest."""

    schema: str
    name: str
    version: str
    commit: str | None = None
    schema_versions: dict[str, str] = field(default_factory=dict)
    compatibility_range: str | None = None
    compatibility_target: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "version": self.version,
            "commit": self.commit,
            "schema_versions": dict(self.schema_versions),
            "compatibility_range": self.compatibility_range,
            "compatibility_target": self.compatibility_target,
        }


def parse_component_manifest(raw: dict[str, Any]) -> ComponentManifest:
    """Parse and validate a raw ``simplicio.component-release/v1`` payload.

    Raises :class:`ComponentManifestError` with a specific, actionable
    message for any of: not a dict, missing/wrong-typed required field
    (``schema``/``name``/``version``), an unsupported ``schema`` value, or a
    wrong-typed optional field (``commit``, ``schema_versions``,
    ``compatibility_range``, ``compatibility_target``).
    """
    if not isinstance(raw, dict):
        raise ComponentManifestError(f"component manifest must be a dict, got {type(raw).__name__}")

    schema = raw.get("schema")
    if not isinstance(schema, str) or not schema:
        raise ComponentManifestError("component manifest missing required string field 'schema'")
    if schema != COMPONENT_MANIFEST_SCHEMA:
        raise ComponentManifestError(
            f"unsupported component manifest schema {schema!r} (expected {COMPONENT_MANIFEST_SCHEMA!r})"
        )

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ComponentManifestError("component manifest missing required non-empty string field 'name'")

    version = raw.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ComponentManifestError("component manifest missing required non-empty string field 'version'")

    commit = raw.get("commit")
    if commit is not None and not isinstance(commit, str):
        raise ComponentManifestError(
            f"component manifest field 'commit' must be a string or null, got {type(commit).__name__}"
        )

    schema_versions = raw.get("schema_versions", {})
    if schema_versions is None:
        schema_versions = {}
    if not isinstance(schema_versions, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in schema_versions.items()
    ):
        raise ComponentManifestError("component manifest field 'schema_versions' must be a dict[str, str]")

    compatibility_range = raw.get("compatibility_range")
    if compatibility_range is not None and not isinstance(compatibility_range, str):
        raise ComponentManifestError(
            f"component manifest field 'compatibility_range' must be a string or null, "
            f"got {type(compatibility_range).__name__}"
        )

    compatibility_target = raw.get("compatibility_target")
    if compatibility_target is not None and not isinstance(compatibility_target, str):
        raise ComponentManifestError(
            f"component manifest field 'compatibility_target' must be a string or null, "
            f"got {type(compatibility_target).__name__}"
        )

    return ComponentManifest(
        schema=schema,
        name=name,
        version=version,
        commit=commit,
        schema_versions=dict(schema_versions),
        compatibility_range=compatibility_range,
        compatibility_target=compatibility_target,
        raw=dict(raw),
    )


# ---------------------------------------------------------------------------#
# Minimal PEP-440-lite version compare (mirrors simplicio.ecosystem's
# `_version_lt` parser so this module doesn't need the `packaging` PyPI
# package — `packaging` is only ever present here transitively, via
# dev-tool extras like pytest/ruff/mypy in `uv.lock`; it is NOT a declared
# base dependency of `simplicio-cli` in `pyproject.toml`, so a real `pip
# install simplicio-cli` end user would not have it. Adding it as a real
# dependency needs a human "yes" per this repo's own AGENTS.md rule, so
# this module stays self-contained instead.
# ---------------------------------------------------------------------------#

_STAGE_ORDER = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "rc": 3, "c": 3, "": 4}
_VERSION_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*([A-Za-z]+)?\s*(\d+)?\s*$")


def parse_version(version: str) -> tuple[tuple[int, ...], tuple[int, int]]:
    """Parse a version string into a comparable ``(release, stage)`` tuple.

    Supports plain releases (``1.2.3``) plus a trailing dev/a/alpha/b/beta/
    rc/c pre-release marker (``1.2.3rc1``). Raises ``ValueError`` on
    anything else — callers decide whether that means NEEDS_REVIEW.
    """
    match = _VERSION_RE.match(version)
    if not match:
        raise ValueError(f"unparseable version: {version!r}")
    release = tuple(int(part) for part in match.group(1).split("."))
    stage_raw = (match.group(2) or "").lower()
    stage_num = int(match.group(3) or 0)
    return release, (_STAGE_ORDER.get(stage_raw, 4), stage_num)


def compare_versions(a: str, b: str) -> int:
    """-1 / 0 / 1 comparator over :func:`parse_version` output."""
    pa, pb = parse_version(a), parse_version(b)
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


_OPERATORS = ("==", "!=", ">=", "<=", ">", "<", "~=")
_CLAUSE_RE = re.compile(r"^\s*(==|!=|>=|<=|>|<|~=)\s*([0-9][0-9.a-zA-Z-]*)\s*$")


def _split_clauses(range_spec: str) -> list[str]:
    return [c for c in (part.strip() for part in range_spec.split(",")) if c]


def parse_range(range_spec: str) -> list[tuple[str, str]]:
    """Parse a comma-separated PEP-440-lite range like ``>=0.23.1,<1.0.0``
    into a list of ``(operator, version)`` clauses.

    Raises ``ValueError`` on a clause that doesn't match a known operator +
    version shape.
    """
    clauses: list[tuple[str, str]] = []
    for raw_clause in _split_clauses(range_spec):
        m = _CLAUSE_RE.match(raw_clause)
        if not m:
            raise ValueError(f"unparseable range clause: {raw_clause!r} (in {range_spec!r})")
        clauses.append((m.group(1), m.group(2)))
    if not clauses:
        raise ValueError(f"empty range spec: {range_spec!r}")
    return clauses


def version_satisfies(version: str, range_spec: str) -> bool:
    """True when *version* satisfies every clause of *range_spec*.

    ``~=`` (compatible release, PEP 440 "compatible release clause") is
    approximated as ``>= version`` and ``< next-major-of-version`` (bumping
    the leading release component), which matches its practical intent for
    the two/three-component ranges this repo actually declares.
    """
    clauses = parse_range(range_spec)
    for op, clause_version in clauses:
        cmp = compare_versions(version, clause_version)
        if op == "==" and cmp != 0:
            return False
        if op == "!=" and cmp == 0:
            return False
        if op == ">=" and cmp < 0:
            return False
        if op == "<=" and cmp > 0:
            return False
        if op == ">" and cmp <= 0:
            return False
        if op == "<" and cmp >= 0:
            return False
        if op == "~=":
            release, _ = parse_version(clause_version)
            if len(release) < 2:
                raise ValueError(f"~= requires at least two release segments: {clause_version!r}")
            next_major = (release[0] + 1,)
            if compare_versions(version, clause_version) < 0:
                return False
            if compare_versions(version, ".".join(str(p) for p in next_major)) >= 0:
                return False
    return True


# ---------------------------------------------------------------------------#
# pyproject.toml introspection (this repo's OWN declared dependency range)
# ---------------------------------------------------------------------------#


def _pyproject_path(root: str | os.PathLike[str] | None = None) -> Path | None:
    if root is not None:
        candidate = Path(root).resolve() / "pyproject.toml"
        return candidate if candidate.is_file() else None
    for candidate in (
        Path.cwd() / "pyproject.toml",
        Path(__file__).resolve().parent.parent / "pyproject.toml",
    ):
        if candidate.is_file():
            return candidate
    return None


def _load_pyproject(root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    p = _pyproject_path(root)
    if not p:
        return {}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ModuleNotFoundError:
            return {}
    try:
        return tomllib.loads(text)
    except Exception:
        return {}


def declared_dependency_range(name: str, root: str | os.PathLike[str] | None = None) -> str | None:
    """Return the raw specifier (e.g. ``">=0.23.1"``) this repo's own
    `pyproject.toml` declares for dependency *name*, or ``None`` if it isn't
    a base dependency there."""
    data = _load_pyproject(root)
    deps = data.get("project", {}).get("dependencies", []) if data else []
    for req in deps:
        m = re.match(rf"^\s*{re.escape(name)}\s*([<>=!~].*)$", req)
        if m:
            return m.group(1).strip()
    return None


def declared_own_version(root: str | os.PathLike[str] | None = None) -> str | None:
    """This repo's own version, from `pyproject.toml` (falls back to the
    installed distribution's `importlib.metadata` version)."""
    data = _load_pyproject(root)
    version = data.get("project", {}).get("version") if data else None
    if isinstance(version, str) and version:
        return version
    try:
        return metadata.version("simplicio-cli")
    except metadata.PackageNotFoundError:
        return None


# ---------------------------------------------------------------------------#
# uv.lock introspection (the version this repo's lockfile last verified —
# "tested_against", closing the "não prova a combinação" gap from the issue)
# ---------------------------------------------------------------------------#


def tested_dependency_version(
    name: str, root: str | os.PathLike[str] | None = None
) -> tuple[str | None, str]:
    """Return ``(version, reason)`` for the version *name* is pinned to in
    this repo's `uv.lock`, honestly reporting when that isn't available.

    ``uv.lock`` is a real, already-committed artifact recording exactly
    what this repo's own resolver last locked to — the closest thing to
    "the combination we actually tested" without a live CI run record.
    Never fabricates a version: if the lockfile is missing, unparseable, or
    doesn't mention *name*, returns ``(None, "<reason>")``.
    """
    if root is not None:
        candidates = [Path(root).resolve() / "uv.lock"]
    else:
        candidates = [
            Path.cwd() / "uv.lock",
            Path(__file__).resolve().parent.parent / "uv.lock",
        ]
    lock_path = next((p for p in candidates if p.is_file()), None)
    if lock_path is None:
        return None, "no_lockfile_found"
    try:
        text = lock_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"lockfile_unreadable: {exc}"
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]
        except ModuleNotFoundError:
            return None, "tomllib_unavailable"
    try:
        data = tomllib.loads(text)
    except Exception as exc:
        return None, f"lockfile_unparseable: {exc}"
    for package in data.get("package", []) or []:
        if isinstance(package, dict) and package.get("name") == name:
            version = package.get("version")
            if isinstance(version, str) and version:
                return version, "locked_in_uv.lock"
            return None, "lockfile_entry_missing_version"
    return None, "not_present_in_lockfile"


# ---------------------------------------------------------------------------#
# Compatibility check
# ---------------------------------------------------------------------------#

COMPATIBLE = "compatible"
INCOMPATIBLE = "incompatible"
NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class CompatibilityResult:
    status: str  # one of COMPATIBLE / INCOMPATIBLE / NEEDS_REVIEW
    reason: str
    candidate_version: str | None
    declared_range: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "candidate_version": self.candidate_version,
            "declared_range": self.declared_range,
        }


def check_component_compatibility(
    candidate: ComponentManifest, declared_range: str | None
) -> CompatibilityResult:
    """Decide COMPATIBLE / INCOMPATIBLE / NEEDS_REVIEW for *candidate*
    against *declared_range* (this repo's own declared dependency range,
    e.g. from :func:`declared_dependency_range`).

    NEEDS_REVIEW (never silently treated as either extreme) covers: no
    declared range known, or a version/range string this parser cannot
    make sense of — both real "a human should look at this" situations,
    not a pass/fail this module can safely decide on its own.
    """
    if declared_range is None:
        return CompatibilityResult(
            NEEDS_REVIEW,
            f"no declared compatibility range known for {candidate.name!r}",
            candidate.version,
            None,
        )
    try:
        ok = version_satisfies(candidate.version, declared_range)
    except ValueError as exc:
        return CompatibilityResult(
            NEEDS_REVIEW,
            f"could not evaluate {candidate.version!r} against {declared_range!r}: {exc}",
            candidate.version,
            declared_range,
        )
    if ok:
        return CompatibilityResult(
            COMPATIBLE,
            f"{candidate.version} satisfies declared range {declared_range}",
            candidate.version,
            declared_range,
        )
    return CompatibilityResult(
        INCOMPATIBLE,
        f"{candidate.version} does not satisfy declared range {declared_range}",
        candidate.version,
        declared_range,
    )


def check_version_against_range(
    version: str, declared_range: str | None, *, name: str
) -> CompatibilityResult:
    """Same decision as :func:`check_component_compatibility` but for a bare
    version string (no full manifest available) — used by `versions --json`
    to grade the currently *installed* package against this repo's own
    declared range."""
    manifest = ComponentManifest(
        schema=COMPONENT_MANIFEST_SCHEMA,
        name=name,
        version=version,
    )
    return check_component_compatibility(manifest, declared_range)


# ---------------------------------------------------------------------------#
# Drift detection (read-only, never raises/blocks — issue #232 item 13)
# ---------------------------------------------------------------------------#


@dataclass(frozen=True)
class DriftResult:
    """Structured drift report. `has_drift=False` is the common case and
    carries no severity; `has_drift=True` always names `kind`+`reason`.

    This is a pure read/report value object: producing one never touches
    any lock/state a running task holds, and nothing in this module ever
    raises out of `detect_drift` — a caller (`doctor`, `versions --json`)
    can therefore call it freely, including while a task is mid-flight,
    without any risk of interrupting that task.
    """

    has_drift: bool
    kind: str | None  # "out_of_range" | "stale_vs_tested" | "not_installed" | None
    reason: str
    installed: str | None
    declared_range: str | None
    tested_against: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_drift": self.has_drift,
            "kind": self.kind,
            "reason": self.reason,
            "installed": self.installed,
            "declared_range": self.declared_range,
            "tested_against": self.tested_against,
        }


def detect_drift(
    *,
    name: str,
    installed: str | None,
    declared_range: str | None,
    tested_against: str | None,
) -> DriftResult:
    """Compare an installed version against the declared range and the
    last-tested (locked) version, purely by reading the values passed in —
    no I/O, no subprocess, no lock acquisition. Two independent drift
    signals, either one is sufficient to report drift:

    1. ``out_of_range`` — installed version does not satisfy the declared
       range (or is missing entirely: ``not_installed``).
    2. ``stale_vs_tested`` — installed version differs from the version
       this repo's lockfile last verified (`tested_against`), even though
       it still satisfies the declared range. This is exactly the gap the
       issue calls out: the range permits a newer resolution, but nothing
       proved that specific combination was ever exercised.
    """
    if installed is None:
        return DriftResult(
            True,
            "not_installed",
            f"{name} is not installed",
            None,
            declared_range,
            tested_against,
        )

    if declared_range is not None:
        try:
            ok = version_satisfies(installed, declared_range)
        except ValueError as exc:
            return DriftResult(
                True,
                "unparseable_range",
                f"could not evaluate {installed!r} against {declared_range!r}: {exc}",
                installed,
                declared_range,
                tested_against,
            )
        if not ok:
            return DriftResult(
                True,
                "out_of_range",
                f"installed {installed} does not satisfy declared range {declared_range}",
                installed,
                declared_range,
                tested_against,
            )

    if tested_against is not None and installed != tested_against:
        return DriftResult(
            True,
            "stale_vs_tested",
            (
                f"installed {installed} differs from {tested_against}, the version this "
                "repo's lockfile last verified — the declared range permits this, but the "
                "combination has not been proven"
            ),
            installed,
            declared_range,
            tested_against,
        )

    return DriftResult(
        False,
        None,
        "installed matches declared range and last-tested version",
        installed,
        declared_range,
        tested_against,
    )


# ---------------------------------------------------------------------------#
# Own manifest (this repo publishing its OWN component-release/v1 — item 9)
# ---------------------------------------------------------------------------#

_SCHEMA_CONST_RE = re.compile(r'^([A-Z][A-Z0-9_]*)\s*=\s*"(simplicio\.[a-z0-9._-]+/v\d+)"', re.MULTILINE)


def own_schema_versions(root: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """Scan this repo's own `simplicio/*.py` (recursively, excluding
    `tests/`/`templates/`) for ``SOME_NAME = "simplicio.foo-bar/vN"``
    constants and return them as ``{CONST_NAME: schema_id}``.

    This is a real, mechanical scan (not a hand-maintained list) so it
    can't drift silently from the schema constants actually defined in the
    package — the same anti-drift intent as
    `scripts/gen_package_interdependence.py --check`.
    """
    base = Path(root).resolve() if root else Path(__file__).resolve().parent
    package_dir = base if base.name == "simplicio" and (base / "cli.py").is_file() else base / "simplicio"
    if not package_dir.is_dir():
        package_dir = Path(__file__).resolve().parent

    found: dict[str, str] = {}
    for path in sorted(package_dir.rglob("*.py")):
        if "templates" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in _SCHEMA_CONST_RE.finditer(text):
            const_name, schema_id = match.group(1), match.group(2)
            found.setdefault(const_name, schema_id)
    return found


def own_commit(root: str | os.PathLike[str] | None = None) -> str | None:
    """``git rev-parse HEAD`` for *root* (default: this package's repo).
    Fails open to ``None`` — no git binary, not a git repo, detached
    worktree edge cases, etc. never raise."""
    cwd = Path(root).resolve() if root else Path(__file__).resolve().parent.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def build_own_manifest(root: str | os.PathLike[str] | None = ".") -> ComponentManifest:
    """Build this repo's own ``simplicio.component-release/v1`` manifest —
    the payload `simplicio-cli` would publish on its own release (issue
    #232 item 9: "Publicar Dev CLI com component-release/v1..."; SBOM/
    signing/provenance are explicitly out of scope here, see
    `simplicio/commands/versions.py` docstring).
    """
    version = declared_own_version(root) or "0.0.0"
    mapper_range = declared_dependency_range("simplicio-mapper", root)
    return ComponentManifest(
        schema=COMPONENT_MANIFEST_SCHEMA,
        name="simplicio-cli",
        version=version,
        commit=own_commit(root),
        schema_versions=own_schema_versions(root),
        compatibility_range=mapper_range,
        compatibility_target="simplicio-mapper",
    )


__all__ = [
    "COMPONENT_MANIFEST_SCHEMA",
    "ComponentManifestError",
    "ComponentManifest",
    "parse_component_manifest",
    "parse_version",
    "compare_versions",
    "parse_range",
    "version_satisfies",
    "declared_dependency_range",
    "declared_own_version",
    "tested_dependency_version",
    "COMPATIBLE",
    "INCOMPATIBLE",
    "NEEDS_REVIEW",
    "CompatibilityResult",
    "check_component_compatibility",
    "check_version_against_range",
    "DriftResult",
    "detect_drift",
    "own_schema_versions",
    "own_commit",
    "build_own_manifest",
]
