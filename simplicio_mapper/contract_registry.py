"""Canonical cross-repository contract registry and drift scanner (#482).

The registry is a small metadata contract, not a mega-schema.  JSON schemas
remain authoritative in their existing versioned locations; this module binds
owner, consumers, canonical hashes and change policy to those locations.
Inventory and validation are read-only unless a caller explicitly asks the
CLI to write its JSON report.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .schema_compat import classify_json_schema_diff

CONTRACT_REGISTRY_SCHEMA = "simplicio.contract-registry/v1"
CONTRACT_ENTRY_SCHEMA = "simplicio.contract-registry-entry/v1"
_CONTRACT_RE = re.compile(r"\bsimplicio[.][A-Za-z0-9_.-]+/v[0-9]+(?:[.][0-9]+)*\b")
_SUFFIXES = {".c", ".cc", ".cpp", ".go", ".h", ".hpp", ".js", ".jsx", ".json", ".md", ".mjs", ".py", ".rs", ".sql", ".toml", ".ts", ".tsx", ".yml", ".yaml"}
_SKIP_DIRS = {".git", ".simplicio", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules", "target", "dist", "build"}

_CONTRACTS_HELP = """usage: simplicio-mapper contracts <inventory|validate|diff|impact> [options]

Inspect the cross-repository contract registry, validate its entries, compare
registry snapshots, or show which consumers are affected by a contract.

Options:
  --root NAME=PATH       add a repository root for inventory
  --registry PATH        use a registry JSON file
  --old PATH --new PATH  compare two registry snapshots (diff)
  --json                 emit the versioned machine-readable envelope
  -h, --help             show this help and exit
"""


class ContractRegistryError(ValueError):
    """Raised when registry input is malformed or drift is ambiguous."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractRegistryError(f"invalid JSON: {path}") from error
    if not isinstance(value, dict):
        raise ContractRegistryError(f"JSON root must be an object: {path}")
    return value


def load_registry(path: str | Path) -> dict[str, Any]:
    payload = _read_json(Path(path).expanduser().absolute())
    if payload.get("schema") != CONTRACT_REGISTRY_SCHEMA:
        raise ContractRegistryError(f"registry schema must be {CONTRACT_REGISTRY_SCHEMA}")
    return payload


def _relative_files(root: Path) -> Iterable[Path]:
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in _SKIP_DIRS and not (Path(directory) / name).is_symlink())
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if path.suffix.lower() in _SUFFIXES and not path.is_symlink():
                yield path


def _language(path: Path) -> str:
    if path.suffix.lower() == ".rs":
        return "rust"
    if path.suffix.lower() in {".py", ".pyi"}:
        return "python"
    if path.suffix.lower() in {".js", ".jsx", ".mjs", ".ts", ".tsx"}:
        return "javascript-typescript"
    return "data"


def _schema_ids(path: Path, text: str) -> set[str]:
    found = set(_CONTRACT_RE.findall(text))
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            for key in ("$id", "title", "schema"):
                value = payload.get(key)
                if isinstance(value, str) and _CONTRACT_RE.fullmatch(value):
                    found.add(value)
    return found


def inventory_contracts(
    roots: Iterable[tuple[str, str | Path]],
    *,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Scan source and schemas without importing consumer repositories."""

    roots = list(roots)
    observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    schema_files: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for repo_id, raw_root in roots:
        root = Path(raw_root).expanduser().absolute()
        if not root.is_dir():
            raise ContractRegistryError(f"repository root does not exist: {root}")
        for path in _relative_files(root):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            ids = _schema_ids(path, text)
            for contract_id in sorted(ids):
                relative = path.relative_to(root).as_posix()
                observations[contract_id].append(
                    {"repo": repo_id, "path": relative, "language": _language(path), "lines": [index for index, line in enumerate(text.splitlines(), 1) if contract_id in line][:20]}
                )
                if path.suffix.lower() == ".json" and ("schema" in path.name.lower() or "$schema" in text[:500]):
                    try:
                        shape = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    schema_files[contract_id].append(
                        {"repo": repo_id, "path": relative, "sha256": canonical_hash(shape), "shape": shape}
                    )
    entries = []
    for contract_id in sorted(observations):
        files = schema_files.get(contract_id, [])
        schema_hashes = sorted({item["sha256"] for item in files})
        entries.append(
            {
                "id": contract_id,
                "observations": observations[contract_id],
                "schema_files": [{key: value for key, value in item.items() if key != "shape"} for item in files],
                "schema_hashes": schema_hashes,
                "duplicate_incompatible": len(schema_hashes) > 1,
                "registry_entry": next((item for item in (registry or {}).get("contracts", []) if item.get("id") == contract_id), None),
            }
        )
    return {
        "schema": "simplicio.contract-registry-inventory/v1",
        "roots": [{"id": repo_id, "path": str(Path(root).expanduser().absolute())} for repo_id, root in roots],
        "contracts": entries,
        "duplicates": [item["id"] for item in entries if item["duplicate_incompatible"]],
        "unregistered": [item["id"] for item in entries if item["registry_entry"] is None],
    }


def validate_registry(registry: Mapping[str, Any], *, root: str | Path | None = None) -> dict[str, Any]:
    if registry.get("schema") != CONTRACT_REGISTRY_SCHEMA:
        raise ContractRegistryError(f"registry schema must be {CONTRACT_REGISTRY_SCHEMA}")
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    seen: set[str] = set()
    base = Path(root or os.getcwd()).expanduser().absolute()
    for entry in registry.get("contracts", []):
        if not isinstance(entry, Mapping):
            errors.append({"code": "ENTRY_INVALID", "detail": "contract entry is not an object"})
            continue
        contract_id = str(entry.get("id", ""))
        if contract_id in seen:
            errors.append({"code": "DUPLICATE_IDENTIFIER", "id": contract_id})
        seen.add(contract_id)
        required = {"id", "kind", "owner", "maintainers", "producers", "consumers", "versions", "canonical", "compatibility", "change_policy"}
        for field in sorted(required - set(entry)):
            errors.append({"code": "ENTRY_FIELD_MISSING", "id": contract_id, "field": field})
        if not re.fullmatch(r"simplicio[.][A-Za-z0-9_.-]+/v[0-9]+(?:[.][0-9]+)*", contract_id):
            errors.append({"code": "IDENTIFIER_INVALID", "id": contract_id})
        if entry.get("owner") != "mapper":
            errors.append({"code": "OWNER_INVALID", "id": contract_id})
        if not isinstance(entry.get("consumers"), list) or not entry.get("consumers"):
            errors.append({"code": "CONSUMERS_MISSING", "id": contract_id})
        canonical = entry.get("canonical") if isinstance(entry.get("canonical"), Mapping) else {}
        schema_path = canonical.get("schema_path")
        declared_hash = canonical.get("sha256")
        if schema_path:
            path = (base / str(schema_path)).resolve()
            if not path.is_file():
                errors.append({"code": "CANONICAL_SCHEMA_MISSING", "id": contract_id, "path": str(schema_path)})
            elif declared_hash not in {None, "", "auto"}:
                try:
                    actual = canonical_hash(_read_json(path))
                except ContractRegistryError:
                    errors.append({"code": "CANONICAL_SCHEMA_INVALID", "id": contract_id})
                else:
                    if str(declared_hash).removeprefix("sha256:") != actual:
                        errors.append({"code": "CANONICAL_HASH_MISMATCH", "id": contract_id})
            else:
                warnings.append({"code": "CANONICAL_HASH_UNVERIFIED", "id": contract_id})
        else:
            warnings.append({"code": "CANONICAL_SCHEMA_EXTERNAL", "id": contract_id})
        versions = entry.get("versions") if isinstance(entry.get("versions"), Mapping) else {}
        if not isinstance(versions.get("current"), str) or not re.fullmatch(r"v\d+(?:\.\d+)*", versions.get("current", "")):
            errors.append({"code": "VERSION_INVALID", "id": contract_id})
    return {"schema": "simplicio.contract-registry-validation/v1", "valid": not errors, "errors": errors, "warnings": warnings, "contracts": len(seen)}


def diff_contracts(old: Mapping[str, Any] | str, new: Mapping[str, Any] | str) -> dict[str, Any]:
    def load(value: Mapping[str, Any] | str) -> Any:
        if isinstance(value, Mapping):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ContractRegistryError("diff input is not valid JSON") from error

    old_value = load(old)
    new_value = load(new)
    if old_value == new_value:
        return {"schema": "simplicio.contract-registry-diff/v1", "classification": "unchanged", "reasons": []}
    old_version = old_value.get("versions", {}).get("current") if isinstance(old_value, Mapping) else None
    new_version = new_value.get("versions", {}).get("current") if isinstance(new_value, Mapping) else None
    if old_version != new_version and (old_version is not None or new_version is not None):
        return {"schema": "simplicio.contract-registry-diff/v1", "classification": "breaking", "reasons": ["contract version changed; require ADR and migration fixture"]}
    old_shape = old_value.get("canonical_schema", old_value) if isinstance(old_value, Mapping) else old_value
    new_shape = new_value.get("canonical_schema", new_value) if isinstance(new_value, Mapping) else new_value
    if isinstance(old_shape, Mapping) and isinstance(new_shape, Mapping) and ("properties" in old_shape or "type" in old_shape):
        classification, reasons = classify_json_schema_diff(canonical_json(old_shape), canonical_json(new_shape))
        if classification == "compatible" and any("added as optional" in reason for reason in reasons):
            classification = "additive"
        return {"schema": "simplicio.contract-registry-diff/v1", "classification": classification, "reasons": reasons}
    return {"schema": "simplicio.contract-registry-diff/v1", "classification": "ambiguous", "reasons": ["shape is not a JSON Schema and no explicit version change was supplied"]}


def impact_contract(registry: Mapping[str, Any], contract_id: str) -> dict[str, Any]:
    entry = next((item for item in registry.get("contracts", []) if item.get("id") == contract_id), None)
    if entry is None:
        raise ContractRegistryError(f"contract is not registered: {contract_id}")
    return {"schema": "simplicio.contract-registry-impact/v1", "id": contract_id, "owner": entry.get("owner"), "maintainers": entry.get("maintainers", []), "producers": entry.get("producers", []), "consumers": entry.get("consumers", []), "gates": ["schema validation", "canonical hash", "compatibility diff", "consumer conformance"]}


def _parse_roots(values: list[str], base: Path) -> list[tuple[str, Path]]:
    if not values:
        values = ["mapper=."]
    result = []
    for value in values:
        if "=" not in value:
            raise ContractRegistryError("--root requires name=path")
        repo_id, raw = value.split("=", 1)
        path = (base / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
        result.append((repo_id, path))
    return result


def run_contracts_cli(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(_CONTRACTS_HELP, end="")
        return 0
    verb = argv[0] if argv else ""
    if verb not in {"inventory", "validate", "diff", "impact"}:
        print("usage: simplicio-mapper contracts <inventory|validate|diff|impact> ...", file=sys.stderr)
        return 2
    as_json = "--json" in argv
    root = Path.cwd()
    registry_path = root / "contracts/contract-registry/v1/registry.json"
    values: list[str] = []
    positional: list[str] = []
    option_paths: dict[str, Path] = {}
    i = 1
    while i < len(argv):
        if argv[i] in {"--root", "--registry", "--old", "--new"} and i + 1 < len(argv):
            if argv[i] == "--root":
                values.append(argv[i + 1])
            elif argv[i] == "--registry":
                registry_path = Path(argv[i + 1])
            else:
                option_paths[argv[i]] = Path(argv[i + 1])
            i += 2
        elif argv[i] == "--json":
            i += 1
        else:
            positional.append(argv[i])
            i += 1
    try:
        if verb == "inventory":
            registry = load_registry(registry_path) if registry_path.is_file() else None
            payload = inventory_contracts(_parse_roots(values, root), registry=registry)
        elif verb == "validate":
            payload = validate_registry(load_registry(registry_path), root=root)
        elif verb == "impact":
            if not positional:
                raise ContractRegistryError("impact requires a contract id")
            payload = impact_contract(load_registry(registry_path), positional[0])
        else:
            if "--old" not in option_paths or "--new" not in option_paths:
                raise ContractRegistryError("diff requires --old and --new")
            old_path = option_paths["--old"]
            new_path = option_paths["--new"]
            payload = diff_contracts(old_path.read_text(encoding="utf-8"), new_path.read_text(encoding="utf-8"))
    except (ContractRegistryError, OSError, ValueError) as error:
        payload = {"schema": "simplicio.contract-registry-error/v1", "valid": False, "reason_code": type(error).__name__, "reason": str(error)}
        if not as_json:
            print(payload["reason"], file=sys.stderr)
        else:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True) if as_json else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("valid", True) else 1


__all__ = ["CONTRACT_ENTRY_SCHEMA", "CONTRACT_REGISTRY_SCHEMA", "ContractRegistryError", "canonical_hash", "canonical_json", "diff_contracts", "impact_contract", "inventory_contracts", "load_registry", "run_contracts_cli", "validate_registry"]
