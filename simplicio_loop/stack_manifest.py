"""Single installed-stack manifest for Mapper, Fast, Dev CLI and Loop.

Release-train floors (#558) are derived from this package's ``pyproject.toml``
lower bounds when available so stack health does not drift from dependency pins.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

STACK_SCHEMA = "simplicio.loop-stack/v1"

# Role labels are fixed; expected floors come from pyproject (see _train_components).
# Issue #1284: public stack is mapper + fast + cli + loop. simplicio-prompt is
# not a required component and must not appear here.
_COMPONENT_ROLES = (
    ("simplicio-mapper", "understand"),
    ("simplicio-fast", "search"),
    ("simplicio-cli", "change,verify"),
    ("simplicio-loop", "run"),
)

# Fallback floors when pyproject cannot be read (offline wheel / missing checkout).
# simplicio-cli train target is 0.18.13; floor stays 0.18.12 for the local wheel.
_FALLBACK_FLOORS = {
    "simplicio-mapper": "0.26.31",
    "simplicio-fast": "2.0.32",
    "simplicio-cli": "0.18.12",
    "simplicio-loop": "3.43.12",
}

# These are operator identities, not distribution names.  ``simplicio-dev-cli``
# is the required mutation entrypoint exported by the ``simplicio-cli``
# distribution; it is intentionally checked separately from the distribution
# so a partial or transitive install cannot look like a complete Loop stack.
REQUIRED_OPERATOR_BINDINGS = (
    ("simplicio-mapper", "simplicio-mapper", "simplicio-mapper"),
    ("simplicio-dev-cli", "simplicio-cli", "simplicio-dev-cli"),
)

MAPPER_VERSION_SCHEMA = "simplicio.mapper-version/v1"
REQUIRED_MAPPER_CAPABILITIES = (
    "simplicio.mapper-artifacts/v1",
    "simplicio.precedent-index/v1",
    "simplicio.context-snapshot/v1",
    "simplicio.plugin.context-handle/v2",
)
REQUIRED_MAPPER_PROTOCOLS = (
    "simplicio.component-release/v1",
    "simplicio.execution-context/v1",
    "simplicio.canonical-map/v1",
)
MAX_MAPPER_VERSION_OUTPUT_BYTES = 131_072

_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


def _normalize_distribution_name(name: str) -> str:
    """Normalize a Python distribution name according to PEP 503."""
    return re.sub(r"[-_.]+", "-", str(name).strip()).lower()


def _requirement_name(spec: str) -> str | None:
    match = _REQUIREMENT_NAME.match(str(spec))
    return _normalize_distribution_name(match.group(1)) if match else None


def _dependency_specs_from_pyproject(pyproject_text: str) -> dict[str, str]:
    """Return direct project dependencies keyed by normalized distribution name."""
    try:
        import tomllib

        project = tomllib.loads(pyproject_text).get("project", {})
        dependencies = project.get("dependencies", []) if isinstance(project, dict) else []
    except (ImportError, TypeError, ValueError):
        dependencies = []
    if not isinstance(dependencies, list):
        return {}
    result: dict[str, str] = {}
    for spec in dependencies:
        name = _requirement_name(str(spec))
        if name:
            result[name] = str(spec)
    return result


def _declared_dependency_specs() -> dict[str, str]:
    """Read Loop's direct dependencies from checkout or installed metadata.

    A wheel does not contain the repository's ``pyproject.toml``.  Falling back
    to ``Requires-Dist`` keeps the same validation available to users who run
    ``simplicio-loop-stack`` after a normal PyPI installation.
    """
    path = _pyproject_path()
    if path.is_file():
        try:
            return _dependency_specs_from_pyproject(path.read_text(encoding="utf-8"))
        except OSError:
            pass
    try:
        requirements = metadata.requires("simplicio-loop") or []
    except metadata.PackageNotFoundError:
        requirements = []
    return {
        name: str(spec)
        for spec in requirements
        if (name := _requirement_name(str(spec)))
        and "; extra ==" not in str(spec).lower()
    }


def _console_entrypoint_owners() -> dict[str, set[str]]:
    """Return console-script names grouped by their owning distribution."""
    owners: dict[str, set[str]] = {}
    try:
        entrypoints = metadata.entry_points(group="console_scripts")
    except TypeError:  # pragma: no cover - compatibility with older metadata APIs.
        entrypoints = metadata.entry_points().get("console_scripts", ())
    for entrypoint in entrypoints:
        distribution = getattr(entrypoint, "dist", None)
        distribution_name = getattr(distribution, "name", None)
        if not distribution_name:
            continue
        owners.setdefault(_normalize_distribution_name(distribution_name), set()).add(
            str(entrypoint.name)
        )
    return owners


def operator_bindings() -> list[dict[str, Any]]:
    """Verify the two mandatory Loop operators and their real entrypoints."""
    declared = _declared_dependency_specs()
    owners = _console_entrypoint_owners()
    bindings: list[dict[str, Any]] = []
    for operator, distribution, entrypoint in REQUIRED_OPERATOR_BINDINGS:
        normalized_distribution = _normalize_distribution_name(distribution)
        dependency_declared = normalized_distribution in declared
        installed = _installed_version(distribution)
        entrypoint_declared = entrypoint in owners.get(normalized_distribution, set())
        resolved = shutil.which(entrypoint) or ""
        if not dependency_declared:
            status = "dependency-not-declared"
        elif installed is None:
            status = "dependency-missing"
        elif not entrypoint_declared:
            status = "entrypoint-not-declared"
        elif not resolved:
            status = "entrypoint-not-on-path"
        else:
            status = "ok"
        bindings.append({
            "operator": operator,
            "distribution": distribution,
            "entrypoint": entrypoint,
            "dependency_declared": dependency_declared,
            "dependency_spec": declared.get(normalized_distribution, ""),
            "installed": installed,
            "entrypoint_declared": entrypoint_declared,
            "resolved": resolved,
            "status": status,
        })
    return bindings


def _sha256_file(path: str | Path) -> str | None:
    candidate = Path(path)
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return "sha256:" + digest.hexdigest()


def _mapper_identity(binding: dict[str, Any], *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "blocked",
        "reason_code": "mapper-entrypoint-not-ready",
        "requested": binding.get("dependency_spec", ""),
        "selected": binding.get("installed"),
        "distribution": binding.get("distribution", "simplicio-mapper"),
        "entrypoint": binding.get("entrypoint", "simplicio-mapper"),
        "entrypoint_owner_verified": bool(binding.get("entrypoint_declared")),
        "executable": binding.get("resolved", ""),
        "executable_sha256": None,
        "artifact_digest": None,
        "version_receipt_schema": None,
        "capabilities": [],
        "protocols": [],
        "capability_result": "unverified",
        "source": "installed distribution metadata plus simplicio-mapper version --json",
    }
    if binding.get("status") != "ok":
        result["reason_code"] = "mapper-" + str(binding.get("status") or "entrypoint-not-ready")
        return result

    executable = str(binding.get("resolved") or "")
    expected_executable = Path(sys.argv[0]).absolute().parent / str(result["entrypoint"])
    result["expected_executable"] = str(expected_executable) if expected_executable.is_file() else None
    if expected_executable.is_file() and Path(executable).resolve() != expected_executable.resolve():
        result["reason_code"] = "mapper-entrypoint-stale-path"
        return result
    result["executable_sha256"] = _sha256_file(executable)
    if result["executable_sha256"] is None:
        result["reason_code"] = "mapper-executable-unreadable"
        return result

    try:
        completed = subprocess.run(
            [executable, "version", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result["reason_code"] = "mapper-version-timeout"
        return result
    except OSError:
        result["reason_code"] = "mapper-version-exec-failed"
        return result

    stdout = completed.stdout or ""
    if len(stdout.encode("utf-8")) > MAX_MAPPER_VERSION_OUTPUT_BYTES:
        result["reason_code"] = "mapper-version-output-too-large"
        return result
    if completed.returncode != 0:
        result["reason_code"] = "mapper-version-nonzero-exit"
        return result
    try:
        receipt = json.loads(stdout)
    except (TypeError, ValueError):
        result["reason_code"] = "mapper-version-invalid-json"
        return result
    if not isinstance(receipt, dict) or receipt.get("schema") != MAPPER_VERSION_SCHEMA:
        result["reason_code"] = "mapper-version-schema-invalid"
        return result

    result["version_receipt_schema"] = receipt.get("schema")
    result["artifact_digest"] = receipt.get("artifact_digest")
    result["capabilities"] = sorted(str(item) for item in receipt.get("capabilities", []) if item)
    result["protocols"] = sorted(str(item) for item in receipt.get("protocols", []) if item)
    if receipt.get("component") != "simplicio-mapper":
        result["reason_code"] = "mapper-component-mismatch"
        return result
    if receipt.get("version") != binding.get("installed"):
        result["reason_code"] = "mapper-version-mismatch"
        return result
    if not isinstance(result["artifact_digest"], str) or not result["artifact_digest"].startswith("sha256:"):
        result["reason_code"] = "mapper-artifact-digest-missing"
        return result
    missing = sorted(set(REQUIRED_MAPPER_CAPABILITIES) - set(result["capabilities"]))
    if missing:
        result["missing_capabilities"] = missing
        result["reason_code"] = "mapper-capabilities-missing"
        return result
    missing_protocols = sorted(set(REQUIRED_MAPPER_PROTOCOLS) - set(result["protocols"]))
    if missing_protocols:
        result["missing_protocols"] = missing_protocols
        result["reason_code"] = "mapper-protocols-missing"
        return result

    result["status"] = "ok"
    result["reason_code"] = "mapper-identity-verified"
    result["capability_result"] = "compatible"
    return result


def _installed_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _version_tuple(version: str) -> tuple[int, int, int] | None:
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", version.strip())
    if not match:
        return None
    return (
        int(match.group(1)),
        int(match.group(2) or 0),
        int(match.group(3) or 0),
    )


def _pyproject_path() -> Path:
    return Path(__file__).resolve().parent.parent / "pyproject.toml"


def _parse_train_floors(pyproject_text: str) -> dict[str, str]:
    """Extract lower-bound floors for train packages + package version for loop."""
    floors = dict(_FALLBACK_FLOORS)
    version_match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject_text)
    if version_match:
        floors["simplicio-loop"] = version_match.group(1)
    for name, spec in _dependency_specs_from_pyproject(pyproject_text).items():
        if name not in floors or name == "simplicio-loop":
            continue
        # Prefer >= / == / ~= lower bound as the train floor.
        floor_match = re.search(r"(?:>=|==|~=)\s*([0-9A-Za-z.\-+]+)", spec)
        if floor_match:
            floors[name] = floor_match.group(1)
    return floors


def _train_components() -> list[tuple[str, str, str]]:
    floors = dict(_FALLBACK_FLOORS)
    path = _pyproject_path()
    if path.is_file():
        try:
            floors = _parse_train_floors(path.read_text(encoding="utf-8"))
        except OSError:
            pass
    else:
        # Installed wheels carry dependency metadata, but not the checkout's
        # pyproject.  Use that metadata instead of retaining stale fallback
        # floors from an older release.
        for name, spec in _declared_dependency_specs().items():
            if name not in floors or name == "simplicio-loop":
                continue
            floor_match = re.search(r"(?:>=|==|~=)\s*([0-9A-Za-z.\-+]+)", spec)
            if floor_match:
                floors[name] = floor_match.group(1)
        installed_loop = _installed_version("simplicio-loop")
        if installed_loop:
            floors["simplicio-loop"] = installed_loop
    return [(name, role, floors[name]) for name, role in _COMPONENT_ROLES]


# Back-compat for tests/imports that still read COMPONENTS as a static tuple.
COMPONENTS = tuple(_train_components())


def stack_manifest() -> dict[str, Any]:
    components = []
    drifted = []
    for distribution, role, expected in _train_components():
        installed = _installed_version(distribution)
        status = "ok"
        reason_code = "component-version-compatible"
        if installed is None:
            status = "missing-or-drifted"
            reason_code = "component-distribution-missing"
        elif installed != expected:
            inst_t = _version_tuple(installed)
            exp_t = _version_tuple(expected)
            if inst_t is None or exp_t is None or inst_t < exp_t:
                status = "missing-or-drifted"
                reason_code = "component-version-below-floor"
        components.append({
            "distribution": distribution,
            "role": role,
            "expected": expected,
            "installed": installed,
            "status": status,
            "reason_code": reason_code,
        })
        if status != "ok":
            drifted.append(distribution)
    bindings = operator_bindings()
    binding_drift = [item["operator"] for item in bindings if item["status"] != "ok"]
    mapper_binding = next(
        (item for item in bindings if item["operator"] == "simplicio-mapper"),
        {"operator": "simplicio-mapper", "status": "entrypoint-not-declared"},
    )
    mapper_identity = _mapper_identity(mapper_binding)
    identity_drift = (
        ["simplicio-mapper-identity"]
        if mapper_binding.get("status") == "ok" and mapper_identity["status"] != "ok"
        else []
    )
    missing_or_drifted = list(dict.fromkeys([*drifted, *binding_drift, *identity_drift]))
    return {
        "schema": STACK_SCHEMA,
        "version": 1,
        "package": "simplicio-loop",
        "components": components,
        "operator_bindings": bindings,
        "mapper_identity": mapper_identity,
        "operator_contract_healthy": not binding_drift and not identity_drift,
        "healthy": not missing_or_drifted,
        "missing_or_drifted": missing_or_drifted,
        "source": "pyproject.toml or installed Requires-Dist metadata",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the installed Simplicio Loop stack")
    parser.add_argument("--json", action="store_true", help="emit the machine-readable manifest")
    parser.add_argument("--check", action="store_true", help="exit non-zero when the stack drifts")
    args = parser.parse_args(argv)
    document = stack_manifest()
    if args.json or args.check:
        print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    else:
        print("simplicio-loop stack: " + ("healthy" if document["healthy"] else "drifted"))
        for component in document["components"]:
            print(f"- {component['distribution']}: {component['installed'] or 'missing'} ({component['role']})")
        for binding in document["operator_bindings"]:
            print(
                f"- operator {binding['operator']}: {binding['status']} "
                f"({binding['distribution']} -> {binding['entrypoint']})"
            )
    return 0 if document["healthy"] or not args.check else 1


if __name__ == "__main__":
    sys.exit(main())
