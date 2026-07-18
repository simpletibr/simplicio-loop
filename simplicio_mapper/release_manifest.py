"""``simplicio-mapper release-manifest`` -- Phase-0 local release manifest (issue #280).

Parent (cross-repo release train epic): wesleysimplicio/simplicio-loop#558.
Related: #236, #263, #279, wesleysimplicio/simplicio-dev-cli#231.
Design record: ``.specs/architecture/ADR-010-release-manifest-phase0.md``.

Issue #280 asks for a large, cross-repo release-train: signed manifests,
SBOM, cross-repo authenticated release events, canary channels, automatic
downstream consumer bumps within 15 minutes, digest/signature verification,
rollback tooling. Almost all of that depends on infrastructure this repo
alone does not own (a signing authority, a cross-repo event bus/webhook
receiver on the Dev CLI side, a canary distribution channel) -- building any
of it here would be speculation about systems that do not exist yet. See the
ADR for the full scoping rationale.

This module implements only the slice that is genuinely buildable and
verifiable from within this repo today: a **local, deterministic, offline**
generator for the ``simplicio.component-release/v1`` manifest shape --
version (single source: :data:`simplicio_mapper.__version__`), commit SHA
(``git rev-parse HEAD``), and every schema-version constant this package
currently publishes (:data:`SCHEMA_VERSION_REGISTRY`, hand-maintained --
Phase-0, see ADR). No signing, no SBOM, no network calls: the ``signing``
block is a structured placeholder that says exactly that, so nothing
downstream can mistake it for a real attestation.

Also implements the schema-version-registry half of issue #280 step 8
("impedir tag se ... schema version divergirem", to the extent verifiable
locally, without inventing PyPI/npm registry-divergence detection): the
registry values above are compared against a checked-in baseline
(``scripts/schema_registry_baseline.json``) via :func:`check_registry_baseline`,
so an *unintentional* schema-version bump is caught the same way
``scripts/check-version-sync.js`` catches a partial package-version bump --
see ``scripts/check_schema_registry_sync.py`` for the CLI wrapper.
"""

from __future__ import annotations

import datetime
import importlib
import json
import os
import subprocess
import sys

from . import __version__

RELEASE_MANIFEST_SCHEMA = "simplicio.component-release/v1"

PYPI_PACKAGE = "simplicio-mapper"
NPM_PACKAGE = "@wesleysimplicio/llm-project-mapper"

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_PACKAGE_DIR)

DEFAULT_REGISTRY_BASELINE_PATH = os.path.join(
    REPO_ROOT, "scripts", "schema_registry_baseline.json"
)


class ReleaseManifestError(RuntimeError):
    """Raised for manifest-generation/registry-collection problems."""


# Hand-maintained inventory of every schema-version constant this package
# currently publishes (Phase-0, see module docstring + ADR-010). Each entry
# is (module path, attribute name); the *value* is never hardcoded here --
# it is imported live at collection time, so this registry can never itself
# drift from the source of truth. Key format is ``"<module>:<attr>"`` so two
# modules that happen to define a same-named constant (e.g. `CONTRACT_VERSION`
# in both `contract.py` and `ecosystem_contract.py`, which are deliberately
# independent namespaces) never collide.
SCHEMA_VERSION_REGISTRY: tuple[tuple[str, str], ...] = (
    ("simplicio_mapper.business", "BUSINESS_RULES_VERSION"),
    ("simplicio_mapper.cli._shared", "CANONICAL_BUILD_SCHEMA_VERSION"),
    ("simplicio_mapper.cli._shared", "CANONICAL_STATUS_SCHEMA_VERSION"),
    ("simplicio_mapper.clustering", "CLUSTERING_VERSION"),
    ("simplicio_mapper.context_cache", "CONTEXT_CACHE_STRUCTURED_VERSION"),
    ("simplicio_mapper.context_dag", "SCHEMA_VERSION"),
    ("simplicio_mapper.context_snapshot", "SCHEMA_VERSION"),
    ("simplicio_mapper.contract", "CONTRACT_VERSION"),
    ("simplicio_mapper.docsync", "DOCS_SYNC_VERSION"),
    ("simplicio_mapper.drift", "SPEC_DRIFT_VERSION"),
    ("simplicio_mapper.ecosystem_contract", "CONTRACT_VERSION"),
    ("simplicio_mapper.flows", "FLOW_ARTIFACT_VERSION"),
    ("simplicio_mapper.history", "DOC_HISTORY_VERSION"),
    ("simplicio_mapper.incremental", "CONTRACT_VERSION"),
    ("simplicio_mapper.mapper.canonical", "CANONICAL_MAP_SCHEMA_VERSION"),
    ("simplicio_mapper.mapper.canonical", "WORKTREE_OVERLAY_SCHEMA_VERSION"),
    ("simplicio_mapper.mapper.canonical", "EFFECTIVE_MAP_VIEW_SCHEMA_VERSION"),
    ("simplicio_mapper.mapper.canonical_gc", "CANONICAL_GC_SCHEMA_VERSION"),
    ("simplicio_mapper.mapper.canonical_reuse", "RECEIPT_SCHEMA_VERSION"),
    ("simplicio_mapper.mapper.canonical_verify", "CANONICAL_VERIFY_SCHEMA_VERSION"),
    ("simplicio_mapper.mapper.parse", "ARTIFACT_VERSION"),
    ("simplicio_mapper.retrieval_index", "RETRIEVAL_INDEX_VERSION"),
    ("simplicio_mapper.survey", "ONBOARDING_VERSION"),
    ("simplicio_mapper.visualization", "VISUALIZATION_VERSION"),
    ("simplicio_mapper.visualization", "PREVIEW_VERSION"),
)


def collect_schema_versions(
    registry: tuple[tuple[str, str], ...] = SCHEMA_VERSION_REGISTRY,
) -> dict[str, int | str]:
    """Import every registered ``(module, attr)`` pair and return their live values.

    Keyed by ``"<module>:<attr>"``. Raises :class:`ReleaseManifestError` if a
    registered module/attribute cannot be imported/found -- a stale registry
    entry (renamed/removed constant) must fail loudly, never silently drop.
    """
    collected: dict[str, int | str] = {}
    for module_path, attr_name in registry:
        key = f"{module_path}:{attr_name}"
        try:
            module = importlib.import_module(module_path)
        except ImportError as error:
            raise ReleaseManifestError(
                f"schema-version registry entry {key!r} references a module "
                f"that cannot be imported: {error}"
            ) from error
        if not hasattr(module, attr_name):
            raise ReleaseManifestError(
                f"schema-version registry entry {key!r} references an "
                f"attribute that no longer exists on {module_path}"
            )
        value = getattr(module, attr_name)
        if not isinstance(value, (int, str)):
            raise ReleaseManifestError(
                f"schema-version registry entry {key!r} is not an int/str "
                f"(got {type(value).__name__}) -- refusing to publish a "
                "manifest with a malformed schema-version constant"
            )
        collected[key] = value
    return collected


def _git_commit_sha(root: str) -> tuple[str | None, str]:
    """Return ``(commit_sha, source)``; ``commit_sha`` is ``None`` on any failure."""
    try:
        result = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"unavailable: git invocation failed ({error})"
    if result.returncode != 0 or not result.stdout.strip():
        stderr = (result.stderr or "").strip() or "git rev-parse HEAD failed"
        return None, f"unavailable: not a git checkout or no commits yet ({stderr})"
    return result.stdout.strip(), "git rev-parse HEAD"


def build_release_manifest(root: str | None = None) -> dict:
    """Build the ``simplicio.component-release/v1`` manifest for the current checkout.

    Purely local and deterministic given (checkout state, package version):
    no signing, no SBOM, no network calls -- see the module docstring and
    ADR-010 for why those remain explicitly out of scope for this repo alone.
    """
    resolved_root = os.path.abspath(root or REPO_ROOT)
    commit_sha, commit_sha_source = _git_commit_sha(resolved_root)
    schema_versions = collect_schema_versions()
    return {
        "schema": RELEASE_MANIFEST_SCHEMA,
        "component": "simplicio-mapper",
        "version": __version__,
        "commit_sha": commit_sha,
        "commit_sha_source": commit_sha_source,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "distribution": {
            "pypi_package": PYPI_PACKAGE,
            "npm_package": NPM_PACKAGE,
        },
        "schema_versions": dict(sorted(schema_versions.items())),
        "signing": {
            "status": "not-implemented",
            "digest": None,
            "signature": None,
            "sbom": None,
            "note": (
                "Phase-0 local generator only (issue #280). Signing, digest "
                "computation and SBOM generation require a signing authority "
                "this repo does not unilaterally own -- see ADR-010 for the "
                "explicit scoping decision and follow-up plan."
            ),
        },
        "downstream_events": {
            "status": "not-implemented",
            "note": (
                "Cross-repo release events, canary channels and automatic "
                "downstream (simplicio-dev-cli/simplicio-loop) version bumps "
                "are out of scope for a mapper-repo-only change -- they "
                "require coordinated infrastructure on the consumer side. "
                "See ADR-010 and the parent epic wesleysimplicio/"
                "simplicio-loop#558."
            ),
        },
    }


def check_registry_baseline(
    baseline_path: str = DEFAULT_REGISTRY_BASELINE_PATH,
) -> tuple[bool, list[str]]:
    """Compare the live schema-version registry against the committed baseline.

    Returns ``(ok, messages)``. ``ok`` is ``False`` when the live registry
    disagrees with the baseline (missing baseline file counts as a failure
    too, distinct from an empty one, so a first-run without a baseline is
    never silently treated as "in sync").
    """
    live = collect_schema_versions()
    if not os.path.isfile(baseline_path):
        return False, [f"no baseline file at {baseline_path} -- run with --update-registry-baseline first"]

    with open(baseline_path, encoding="utf-8") as handle:
        baseline_doc = json.load(handle)
    baseline_entries = baseline_doc.get("entries", {})

    messages: list[str] = []
    ok = True

    live_keys = set(live)
    baseline_keys = set(baseline_entries)

    for key in sorted(live_keys - baseline_keys):
        ok = False
        messages.append(f"[new] {key} = {live[key]!r} is not in the committed baseline")
    for key in sorted(baseline_keys - live_keys):
        ok = False
        messages.append(f"[removed] {key} was in the baseline but no longer exists in the registry")
    for key in sorted(live_keys & baseline_keys):
        if live[key] != baseline_entries[key]:
            ok = False
            messages.append(
                f"[changed] {key} = {live[key]!r} (baseline: {baseline_entries[key]!r})"
            )

    if ok:
        messages.append(f"[ok] {len(live)} schema-version constants match the committed baseline")
    else:
        messages.append(
            "Schema-version drift detected. If this is a deliberate, reviewed "
            "bump, regenerate the baseline with --update-registry-baseline "
            "and commit it in the same change."
        )
    return ok, messages


def write_registry_baseline(baseline_path: str = DEFAULT_REGISTRY_BASELINE_PATH) -> dict:
    """Regenerate the committed schema-version-registry baseline file."""
    live = collect_schema_versions()
    doc = {
        "schema": "simplicio.schema-registry-baseline/v1",
        "note": (
            "Committed snapshot of SCHEMA_VERSION_REGISTRY in "
            "simplicio_mapper/release_manifest.py. Regenerate with "
            "`python -m simplicio_mapper.release_manifest --update-registry-baseline` "
            "after a deliberate, reviewed schema-version bump; never hand-edit."
        ),
        "entries": dict(sorted(live.items())),
    }
    os.makedirs(os.path.dirname(baseline_path), exist_ok=True)
    with open(baseline_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(doc, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    return doc


def run_release_manifest_cli(argv: list[str]) -> int:
    """Entry point for ``simplicio-mapper release-manifest [--json] [--root <dir>]``.

    Also supports the registry-baseline maintenance flags documented in the
    module docstring: ``--check-registry`` / ``--update-registry-baseline``
    (issue #280 step 8, schema-version-divergence half only).
    """
    as_json = "--json" in argv
    root = REPO_ROOT
    if "--root" in argv:
        idx = argv.index("--root")
        try:
            root = argv[idx + 1]
        except IndexError:
            print("--root requires a directory", file=sys.stderr)
            return 2

    if "--check-registry" in argv:
        try:
            ok, messages = check_registry_baseline()
        except ReleaseManifestError as error:
            print(f"::error::{error}", file=sys.stderr)
            return 1
        for message in messages:
            print(message)
        return 0 if ok else 1

    if "--update-registry-baseline" in argv:
        try:
            doc = write_registry_baseline()
        except ReleaseManifestError as error:
            print(f"::error::{error}", file=sys.stderr)
            return 1
        print(f"[ok] wrote {len(doc['entries'])} entries to {DEFAULT_REGISTRY_BASELINE_PATH}")
        return 0

    try:
        manifest = build_release_manifest(root=root)
    except ReleaseManifestError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    else:
        print(f"component:     {manifest['component']}")
        print(f"version:       {manifest['version']}")
        print(f"commit_sha:    {manifest['commit_sha'] or '(unavailable)'} ({manifest['commit_sha_source']})")
        print(f"schema count:  {len(manifest['schema_versions'])}")
        print(f"signing:       {manifest['signing']['status']} -- {manifest['signing']['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(run_release_manifest_cli(sys.argv[1:]))
