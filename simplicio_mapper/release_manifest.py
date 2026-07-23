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

**Artifact digests (this change, still issue #280 step 3, honest sub-slice
only)**: a cryptographic *signature* needs a signing authority this repo
does not own (still deferred, see ``signing.status`` above, which stays
``"not-implemented"`` for the signature itself). A SHA256 *digest* of the
actual built ``dist/*.whl``/``dist/*.tar.gz`` files is different: it is a
plain checksum of bytes already on disk, computable unilaterally, with zero
external dependency and zero new infrastructure. :func:`compute_artifact_digests`
and the manifest's new ``artifact_digests`` field carry that honest data;
:func:`verify_artifact_digests` (and ``--verify-digests`` on the CLI) check a
previously generated manifest against a ``dist/`` directory, matching the
"impedir tag se ... divergirem" spirit of step 8 for the one thing checkable
purely locally: artifact-vs-manifest integrity, not PyPI/npm-registry
divergence (still out of scope, see ADR-010).
"""

from __future__ import annotations

import datetime
import hashlib
import importlib
import json
import os
import subprocess
import sys

from . import __version__

RELEASE_MANIFEST_SCHEMA = "simplicio.component-release/v1"

PYPI_PACKAGE = "simplicio-mapper"
NPM_PACKAGE = "@wesleysimplicio/llm-project-mapper"

RELEASE_PROTOCOLS = (
    RELEASE_MANIFEST_SCHEMA,
    "simplicio.mapper-artifacts/v1",
    "simplicio.precedent-index/v1",
    "simplicio.context-snapshot/v1",
    "simplicio.execution-context/v1",
    "simplicio.canonical-map/v1",
    "simplicio.worktree-overlay/v1",
)

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
    ("simplicio_mapper.execution_context", "SCHEMA_VERSION"),
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


_DIGEST_CHUNK_SIZE = 1024 * 1024

DEFAULT_DIST_DIR = os.path.join(REPO_ROOT, "dist")


def _sha256_file(path: str) -> str:
    """Return ``sha256:<hex>`` for the real bytes at ``path``."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_DIGEST_CHUNK_SIZE), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _find_dist_artifact(dist_dir: str, suffix: str) -> str | None:
    """Return the path of the single file in ``dist_dir`` ending in ``suffix``.

    Returns ``None`` if the directory does not exist, has no matching file,
    or has more than one match (ambiguous -- refuse to guess which build is
    "the" release artifact rather than silently picking one).
    """
    if not os.path.isdir(dist_dir):
        return None
    matches = sorted(
        name for name in os.listdir(dist_dir) if name.endswith(suffix)
    )
    if len(matches) != 1:
        return None
    return os.path.join(dist_dir, matches[0])


def compute_artifact_digests(dist_dir: str | None = None) -> dict:
    """Return real SHA256 digests of the built ``dist/*.whl``/``dist/*.tar.gz``.

    This is a plain checksum of bytes that already exist on disk after a real
    ``python -m build`` -- not a stand-in for cryptographic signing (see
    module docstring / ADR-010: signing itself stays ``"not-implemented"``).
    When ``dist_dir`` (or the individual artifact) does not exist, the
    corresponding entry is ``None`` with an honest ``note`` -- never a
    fabricated placeholder digest.
    """
    resolved_dist_dir = os.path.abspath(dist_dir or DEFAULT_DIST_DIR)
    whl_path = _find_dist_artifact(resolved_dist_dir, ".whl")
    sdist_path = _find_dist_artifact(resolved_dist_dir, ".tar.gz")

    result: dict = {
        "dist_dir": resolved_dist_dir,
        "whl": None,
        "sdist": None,
        "note": None,
    }
    if whl_path is None and sdist_path is None:
        result["note"] = (
            f"no dist/*.whl or dist/*.tar.gz found under {resolved_dist_dir} "
            "-- run `python -m build` first if you want real artifact "
            "digests in the manifest; this field stays absent rather than "
            "a fabricated placeholder."
        )
        return result

    if whl_path is not None:
        result["whl"] = {
            "filename": os.path.basename(whl_path),
            "digest": _sha256_file(whl_path),
        }
    if sdist_path is not None:
        result["sdist"] = {
            "filename": os.path.basename(sdist_path),
            "digest": _sha256_file(sdist_path),
        }
    missing = []
    if whl_path is None:
        missing.append(".whl")
    if sdist_path is None:
        missing.append(".tar.gz")
    if missing:
        result["note"] = (
            f"no {' or '.join(missing)} found under {resolved_dist_dir} -- "
            "digest(s) for the missing artifact type stay absent rather "
            "than fabricated."
        )
    return result


def build_release_manifest(root: str | None = None, dist_dir: str | None = None) -> dict:
    """Build the ``simplicio.component-release/v1`` manifest for the current checkout.

    Purely local and deterministic given (checkout state, package version,
    dist/ contents): no signing, no SBOM, no network calls -- see the module
    docstring and ADR-010 for why those remain explicitly out of scope for
    this repo alone. ``dist_dir`` (default ``dist/`` at the repo root) is
    scanned for real built artifacts to compute honest SHA256 digests for
    (see :func:`compute_artifact_digests`); when absent, ``artifact_digests``
    stays a structured "not found" note, never a fake value.
    """
    resolved_root = os.path.abspath(root or REPO_ROOT)
    commit_sha, commit_sha_source = _git_commit_sha(resolved_root)
    schema_versions = collect_schema_versions()
    artifact_digests = compute_artifact_digests(dist_dir=dist_dir)
    manifest = {
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
        "protocols": list(RELEASE_PROTOCOLS),
        "artifact_digest": None,
        "artifact_digests": artifact_digests,
        "signing": {
            "status": "not-implemented",
            "digest": None,
            "signature": None,
            "sbom": None,
            "note": (
                "Phase-0 local generator only (issue #280). Cryptographic "
                "signing and SBOM generation require a signing authority "
                "this repo does not unilaterally own -- see ADR-010 for the "
                "explicit scoping decision and follow-up plan. Real SHA256 "
                "digests of built dist/ artifacts, when available, live in "
                "the separate `artifact_digests` field -- a checksum is not "
                "a signature."
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
    manifest["artifact_digest"] = build_release_artifact_digest(manifest)
    return manifest


def build_release_artifact_digest(manifest: dict) -> str:
    """Return a stable sha256 digest for the release identity payload.

    The digest intentionally excludes volatile presentation fields
    (``generated_at``) and the ``signing`` block that will eventually carry
    attestations *about* this payload, avoiding a self-referential digest.
    """
    payload = {
        "schema": manifest["schema"],
        "component": manifest["component"],
        "version": manifest["version"],
        "commit_sha": manifest["commit_sha"],
        "distribution": manifest["distribution"],
        "schema_versions": manifest["schema_versions"],
        "protocols": manifest["protocols"],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_version_payload(root: str | None = None) -> dict:
    """Build the machine-readable ``simplicio-mapper version --json`` payload."""
    manifest = build_release_manifest(root=root)
    return {
        "schema": "simplicio.mapper-version/v1",
        "component": manifest["component"],
        "version": manifest["version"],
        "commit_sha": manifest["commit_sha"],
        "artifact_digest": manifest["artifact_digest"],
        "protocols": manifest["protocols"],
        "release_manifest_schema": manifest["schema"],
        "schema_versions": manifest["schema_versions"],
        "distribution": manifest["distribution"],
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



def verify_artifact_digests(manifest: dict, dist_dir: str | None = None) -> tuple[bool, list[str]]:
    """Check a previously generated manifest's ``artifact_digests`` against real files.

    Scoped, honest sibling of :func:`check_registry_baseline`: this is the
    "impedir tag se ... divergirem" spirit of issue #280 step 8 for the one
    thing checkable purely locally -- does the artifact on disk in
    ``dist_dir`` still hash to what the manifest recorded. It is *not* the
    PyPI/npm live-registry divergence check described in the issue (that
    needs real network calls to a registry API and stays out of scope, see
    ADR-010).

    Returns ``(ok, messages)``. A manifest with no recorded digests (both
    ``whl``/``sdist`` ``None``) is treated as "nothing to verify" -- ``ok``
    is ``True`` with an explanatory message, not a silent pass mistaken for
    a real check.
    """
    recorded = manifest.get("artifact_digests") or {}
    fresh = compute_artifact_digests(dist_dir=dist_dir)

    messages: list[str] = []
    ok = True
    checked_any = False

    for key, label in (("whl", ".whl"), ("sdist", ".tar.gz")):
        recorded_entry = recorded.get(key)
        fresh_entry = fresh.get(key)
        if recorded_entry is None and fresh_entry is None:
            continue
        checked_any = True
        if recorded_entry is None:
            ok = False
            messages.append(
                f"[missing-in-manifest] {label} artifact found in "
                f"{fresh['dist_dir']} ({fresh_entry['filename']}) but the "
                "manifest has no recorded digest for it"
            )
            continue
        if fresh_entry is None:
            ok = False
            messages.append(
                f"[missing-on-disk] manifest records a {label} digest for "
                f"{recorded_entry['filename']} but no matching file was "
                f"found in {fresh['dist_dir']}"
            )
            continue
        if recorded_entry["digest"] != fresh_entry["digest"]:
            ok = False
            messages.append(
                f"[mismatch] {label} artifact {fresh_entry['filename']} "
                f"digest {fresh_entry['digest']} does not match manifest-"
                f"recorded digest {recorded_entry['digest']} for "
                f"{recorded_entry['filename']}"
            )
        else:
            messages.append(f"[ok] {label} artifact digest matches: {fresh_entry['filename']}")

    if not checked_any:
        messages.append(
            "[skip] manifest has no recorded artifact digests and no "
            f"dist/*.whl or dist/*.tar.gz found in {fresh['dist_dir']} -- "
            "nothing to verify"
        )

    return ok, messages


def run_version_cli(argv: list[str]) -> int:
    """Entry point for ``simplicio-mapper version [--json] [--root <dir>]``."""
    as_json = "--json" in argv
    root = REPO_ROOT
    if "--root" in argv:
        idx = argv.index("--root")
        try:
            root = argv[idx + 1]
        except IndexError:
            print("--root requires a directory", file=sys.stderr)
            return 2
    try:
        payload = build_version_payload(root=root)
    except ReleaseManifestError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(payload["version"])
    return 0

def run_release_manifest_cli(argv: list[str]) -> int:
    """Entry point for ``simplicio-mapper release-manifest [--json] [--root <dir>] [--dist-dir <dir>]``.

    Also supports the registry-baseline maintenance flags documented in the
    module docstring: ``--check-registry`` / ``--update-registry-baseline``
    (issue #280 step 8, schema-version-divergence half only), and
    ``--verify-digests <manifest.json> [--dist-dir <dir>]`` to check a
    previously generated manifest's ``artifact_digests`` against real files
    on disk (issue #280 step 8, artifact-vs-manifest integrity half).
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

    dist_dir = None
    if "--dist-dir" in argv:
        idx = argv.index("--dist-dir")
        try:
            dist_dir = argv[idx + 1]
        except IndexError:
            print("--dist-dir requires a directory", file=sys.stderr)
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

    if "--verify-digests" in argv:
        idx = argv.index("--verify-digests")
        try:
            manifest_path = argv[idx + 1]
        except IndexError:
            print("--verify-digests requires a manifest file path", file=sys.stderr)
            return 2
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
        except OSError as error:
            print(f"::error::could not read manifest at {manifest_path}: {error}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as error:
            print(f"::error::{manifest_path} is not valid JSON: {error}", file=sys.stderr)
            return 1
        ok, messages = verify_artifact_digests(manifest, dist_dir=dist_dir)
        for message in messages:
            print(message)
        return 0 if ok else 1

    try:
        manifest = build_release_manifest(root=root, dist_dir=dist_dir)
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
        digests = manifest["artifact_digests"]
        if digests.get("whl") or digests.get("sdist"):
            whl_note = digests["whl"]["digest"] if digests.get("whl") else "(not found)"
            sdist_note = digests["sdist"]["digest"] if digests.get("sdist") else "(not found)"
            print(f"artifact whl:  {whl_note}")
            print(f"artifact sdist:{sdist_note}")
        else:
            print(f"artifacts:     {digests.get('note') or '(none found)'}")
    return 0


if __name__ == "__main__":
    sys.exit(run_release_manifest_cli(sys.argv[1:]))
