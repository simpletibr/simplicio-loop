"""Mapper-artifacts contract validator (issue #157).

The mapper produces six JSON artifacts (``.simplicio/project-map.json``,
``precedent-index.json``, ``architecture-inventory.json``,
``symbol-index.json``, ``call-graph.json``, and the ``index --json`` payload
``simplicio.mapper-index/v1``) that simplicio-dev-cli/simplicio-loop/
simplicio-runtime parse. This module is a small, dependency-free JSON Schema
*subset* validator (no ``jsonschema`` package pulled in, per the "ask before
adding a dependency" rule) used to check real mapper output against the
versioned schemas in ``contracts/mapper-artifacts/v1/schemas/``.

Supported schema keywords (deliberately a subset — enough to catch real
shape drift without becoming a general JSON Schema implementation):
``type`` (string or list of strings, including ``"null"``), ``required``,
``properties``, ``items``, ``enum``, ``minItems`` and local/external ``$ref``.
``additionalProperties``
is always allowed (unknown/added fields do not fail validation — only
missing/mistyped required fields do), so the contract catches breaking
changes without punishing purely additive ones.
"""

from __future__ import annotations

import json
import os
import re

CONTRACT_VERSION = "v1"

_CONTRACT_HELP = """usage: simplicio-mapper contract validate <path> [<path> ...]

Validate Mapper artifact JSON files or every JSON file below a directory
against the versioned contracts/mapper-artifacts/v1 schemas.

Options:
  -h, --help    show this help and exit
"""

# Maps a payload's own "schema" field to the schema file that describes it.
SCHEMA_FILENAMES = {
    "simplicio.project-map/v1": "project-map.schema.json",
    "simplicio.precedent-index/v1": "precedent-index.schema.json",
    "simplicio.architecture-inventory/v1": "architecture-inventory.schema.json",
    "simplicio.symbol-index/v1": "symbol-index.schema.json",
    "simplicio.call-graph/v1": "call-graph.schema.json",
    "simplicio.mapper-native/project-map/v1": "mapper-native-artifact.schema.json",
    "simplicio.mapper-native/precedent-index/v1": "mapper-native-artifact.schema.json",
    "simplicio.mapper-native/architecture-inventory/v1": "mapper-native-artifact.schema.json",
    "simplicio.mapper-native/symbol-index/v1": "mapper-native-artifact.schema.json",
    "simplicio.mapper-native/call-graph/v1": "mapper-native-artifact.schema.json",
    "simplicio.graph-delta/v1": "graph-delta.schema.json",
    "simplicio.graph-snapshot/v1": "graph-snapshot.schema.json",
    "simplicio.task-intent/v1": "task-intent.schema.json",
    "simplicio.task-context/v1": "task-context.schema.json",
    "simplicio.task-batch/v1": "task-batch.schema.json",
    "simplicio.task-traceability/v1": "task-traceability.schema.json",
    "simplicio.mapper-index/v1": "mapper-index.schema.json",
    "simplicio.visualization-bundle/v1": "visualization-bundle.schema.json",
    "simplicio.visualization-preview/v1": "visualization-preview.schema.json",
    "simplicio.mapper-canvas-compatibility/v1": "compatibility-matrix.schema.json",
    "simplicio.mapper-canvas-performance/v1": "performance-baseline.schema.json",
    "simplicio.clustering-metrics/v1": "clustering-metrics.schema.json",
    "simplicio.context-snapshot/v1": "context-snapshot.schema.json",
    "simplicio.context-graph/v1": "context-graph.schema.json",
}

_PY_TYPE_NAMES = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


class ContractError(RuntimeError):
    """Raised for validator/setup problems (missing schema, bad fixture path)."""


def find_contract_root(start: str | None = None) -> str:
    """Locate ``contracts/mapper-artifacts/v1`` by walking upward from ``start``.

    Checked in order: ``start`` (default cwd) and its ancestors, then the
    directory this package itself lives in (covers running from an
    installed/editable checkout whose cwd is not the repo root). Raises
    ``ContractError`` if none of those contain the contract directory —
    see ``contracts/mapper-artifacts/v1/README.md`` for why this is not
    currently packaged into the PyPI/npm distributions.
    """
    candidates = []
    here = os.path.abspath(start or os.getcwd())
    while True:
        candidates.append(here)
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    package_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.dirname(package_dir))

    for candidate in candidates:
        for contract_name in ("mapper-artifacts", "visualization", "mapper-canvas", "clustering"):
            root = os.path.join(candidate, "contracts", contract_name, CONTRACT_VERSION)
            if os.path.isdir(os.path.join(root, "schemas")):
                return root
    raise ContractError(
        "could not locate contracts/mapper-artifacts/v1/schemas/ from "
        f"{start or os.getcwd()} or its parents. Run this from within a "
        "simplicio-mapper checkout (the contract is not currently shipped "
        "in the published package — see contracts/mapper-artifacts/v1/README.md)."
    )


def load_schema(schema_id: str, contract_root: str) -> dict:
    filename = SCHEMA_FILENAMES.get(schema_id)
    if not filename:
        raise ContractError(f'unknown schema id "{schema_id}" (known: {sorted(SCHEMA_FILENAMES)})')
    schema_dir = os.path.join(contract_root, "schemas")
    if schema_id.startswith("simplicio.task-"):
        schema_dir = os.path.join(
            os.path.dirname(os.path.dirname(contract_root)),
            "task-orientation",
            CONTRACT_VERSION,
            "schemas",
        )
    if schema_id.startswith("simplicio.visualization-"):
        schema_dir = os.path.join(
            os.path.dirname(os.path.dirname(contract_root)),
            "visualization",
            CONTRACT_VERSION,
            "schemas",
        )
    if schema_id.startswith("simplicio.mapper-canvas-"):
        schema_dir = os.path.join(
            os.path.dirname(os.path.dirname(contract_root)),
            "mapper-canvas",
            CONTRACT_VERSION,
            "schemas",
        )
    if schema_id.startswith("simplicio.clustering"):
        schema_dir = os.path.join(
            os.path.dirname(os.path.dirname(contract_root)),
            "clustering",
            CONTRACT_VERSION,
            "schemas",
        )
    if schema_id.startswith("simplicio.context-"):
        # Shipped inside the installed package (issue #208): resolve from the
        # vendored contracts dir, which exists even on a clean pip install.
        package_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "contracts",
            "context-snapshot",
            CONTRACT_VERSION,
            "schemas",
        )
        if os.path.isfile(os.path.join(package_dir, filename)):
            schema_dir = package_dir
        else:
            # Running from a checkout before install: fall back to the repo's
            # source contracts dir (walked up from the package file).
            repo_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "contracts",
                "context-snapshot",
                CONTRACT_VERSION,
                "schemas",
            )
            schema_dir = repo_dir
    path = os.path.join(schema_dir, filename)
    if not os.path.isfile(path):
        raise ContractError(f"schema file missing: {path}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _type_matches(value: object, expected: str) -> bool:
    py_type = _PY_TYPE_NAMES.get(expected)
    if py_type is None:
        return True  # unknown type keyword: do not fail closed on a typo
    if expected == "integer" and isinstance(value, bool):
        return False  # bool is technically an int subclass in Python
    if expected == "number" and isinstance(value, bool):
        return False
    return isinstance(value, py_type)


def _load_ref_schema(ref: str, schema_base: str | None, root_schema: dict) -> dict | None:
    if ref.startswith("#/"):
        current: object = root_schema
        for component in ref[2:].split("/"):
            if not isinstance(current, dict) or component not in current:
                return None
            current = current[component]
        return current if isinstance(current, dict) else None
    if not schema_base:
        return None
    path = os.path.join(schema_base, ref)
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _validate_node(
    value: object,
    schema: dict,
    path: str,
    errors: list[str],
    schema_base: str | None = None,
    root_schema: dict | None = None,
) -> None:
    root_schema = root_schema or schema
    if "$ref" in schema:
        ref = schema.get("$ref")
        target = _load_ref_schema(ref, schema_base, root_schema) if isinstance(ref, str) else None
        if target is None:
            errors.append(f"{path}: unresolved schema reference {ref!r}")
            return
        _validate_node(value, target, path, errors, schema_base, target)
        return

    expected_types = schema.get("type")
    if expected_types:
        types = [expected_types] if isinstance(expected_types, str) else list(expected_types)
        if not any(_type_matches(value, t) for t in types):
            errors.append(f"{path}: expected type {types}, got {type(value).__name__}")
            return  # further checks would just be noise once the type is wrong

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in enum {schema['enum']}")

    if isinstance(value, dict):
        for required_key in schema.get("required", []):
            if required_key not in value:
                errors.append(f"{path}: missing required property '{required_key}'")
        properties = schema.get("properties", {})
        for key, sub_schema in properties.items():
            if key in value:
                _validate_node(value[key], sub_schema, f"{path}.{key}", errors, schema_base, root_schema)
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: additional property {key!r} is not allowed")
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            for key, child in value.items():
                if key not in properties:
                    _validate_node(child, additional, f"{path}.{key}", errors, schema_base, root_schema)

        min_properties = schema.get("minProperties")
        max_properties = schema.get("maxProperties")
        if min_properties is not None and len(value) < min_properties:
            errors.append(f"{path}: has {len(value)} properties, expected at least {min_properties}")
        if max_properties is not None and len(value) > max_properties:
            errors.append(f"{path}: has {len(value)} properties, expected at most {max_properties}")

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: has {len(value)} items, expected at least {min_items}")
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            errors.append(f"{path}: has {len(value)} items, expected at most {max_items}")
        if schema.get("uniqueItems"):
            seen = set()
            for item in value:
                try:
                    marker = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                except (TypeError, ValueError):
                    marker = repr(item)
                if marker in seen:
                    errors.append(f"{path}: array items must be unique")
                    break
                seen.add(marker)
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate_node(item, item_schema, f"{path}[{index}]", errors, schema_base, root_schema)

    if isinstance(value, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if min_length is not None and len(value) < min_length:
            errors.append(f"{path}: string shorter than {min_length}")
        if max_length is not None and len(value) > max_length:
            errors.append(f"{path}: string longer than {max_length}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                if re.search(pattern, value) is None:
                    errors.append(f"{path}: string does not match pattern {pattern!r}")
            except re.error:
                errors.append(f"{path}: invalid schema pattern {pattern!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: value {value} is less than minimum {minimum}")
        if maximum is not None and value > maximum:
            errors.append(f"{path}: value {value} is greater than maximum {maximum}")


def validate_instance(instance: dict, schema: dict, schema_base: str | None = None) -> list[str]:
    """Return a list of human-readable validation errors (empty = valid)."""
    errors: list[str] = []
    _validate_node(instance, schema, "$", errors, schema_base, schema)
    return errors


def validate_payload(payload: dict, contract_root: str) -> tuple[str, list[str]]:
    """Validate ``payload`` against the schema its own ``schema`` field names.

    Returns ``(schema_id, errors)``. Raises ``ContractError`` if the payload
    has no recognizable ``schema`` field. Context schemas delegate lazily to
    their canonical validator because they require cross-document invariants.
    """
    schema_id = payload.get("schema")
    if not schema_id:
        raise ContractError('payload has no "schema" field to look up a contract by')
    if schema_id in {"simplicio.context-snapshot/v1", "simplicio.context-graph/v1"}:
        from .context_contract import validate_context_payload

        report = validate_context_payload(payload)
        return schema_id, [f"{item['path']}: [{item['code']}] {item['message']}" for item in report["reason_codes"]]
    schema = load_schema(schema_id, contract_root)
    schema_base = os.path.join(contract_root, "schemas")
    return schema_id, validate_instance(payload, schema, schema_base)


def validate_file(path: str, contract_root: str) -> tuple[str, list[str]]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return validate_payload(payload, contract_root)


def iter_json_files(paths: list[str]) -> list[str]:
    """Expand a mix of file/directory paths into a sorted list of *.json files."""
    found: list[str] = []
    for raw_path in paths:
        if os.path.isdir(raw_path):
            for current, _dirs, files in os.walk(raw_path):
                for name in files:
                    if name.endswith(".json"):
                        found.append(os.path.join(current, name))
        elif os.path.isfile(raw_path):
            found.append(raw_path)
        else:
            raise ContractError(f"path not found: {raw_path}")
    return sorted(set(found))


def run_contract_cli(argv: list[str]) -> int:
    """Entry point for ``simplicio-mapper contract <subcommand> ...``."""
    if "--help" in argv or "-h" in argv:
        print(_CONTRACT_HELP, end="", flush=True)
        return 0
    if not argv or argv[0] != "validate":
        print(
            "usage: simplicio-mapper contract validate <path> [<path> ...]",
            flush=True,
        )
        return 2
    paths = argv[1:]
    if not paths:
        print("usage: simplicio-mapper contract validate <path> [<path> ...]", flush=True)
        return 2
    try:
        contract_root = find_contract_root()
        json_files = iter_json_files(paths)
    except ContractError as error:
        print(f"::error::{error}", flush=True)
        return 1
    if not json_files:
        print("::error::no *.json files found under the given path(s)", flush=True)
        return 1

    failed = False
    for file_path in json_files:
        try:
            schema_id, errors = validate_file(file_path, contract_root)
        except ContractError as error:
            print(f"[skip] {file_path}: {error}")
            continue
        if errors:
            failed = True
            print(f"[fail] {file_path} ({schema_id}):")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"[ok]   {file_path} ({schema_id})")
    return 1 if failed else 0
