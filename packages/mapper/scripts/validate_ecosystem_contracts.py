#!/usr/bin/env python3
"""Standalone validator for the ecosystem contract (issue #164).

INTENTIONALLY SELF-CONTAINED / VENDORABLE: this file has zero imports outside
the Python 3.8+ standard library and does NOT import ``simplicio_mapper``.
That is on purpose -- see ``contracts/ecosystem/v1/README.md``. The point of
this script is that separate ecosystem repositories can copy this single file
into their own trees and validate their own fixtures/output against a vendored
copy of the ecosystem schemas, without taking a dependency on
``simplicio_mapper`` being installed.

It duplicates (deliberately -- not a bug) the same small JSON-Schema subset
engine as ``simplicio_mapper/contract.py``: ``type`` (including
``["string", "null"]`` unions), ``required``, ``properties``, ``items``,
``enum``, ``minItems``. ``additionalProperties`` is always implicitly allowed.
For ``simplicio.ecosystem-graph/v1`` it also enforces semantic graph invariants
that the small schema subset cannot express: unique IDs, closed endpoints,
immutable revisions for available repositories, HTTPS evidence and non-empty
boundaries.

Usage
-----

    # validate every *.json fixture under contracts/ecosystem/v1/fixtures/
    python3 scripts/validate_ecosystem_contracts.py

    # validate specific file(s)/dir(s)
    python3 scripts/validate_ecosystem_contracts.py path/to/execution.json

    # point at a vendored copy of the schemas (for use from another repo)
    python3 scripts/validate_ecosystem_contracts.py --schema-root /path/to/schemas path/to/fixtures

Exit code 0 when every discovered/validated file matches its own ``"schema"``
field and semantic invariants; non-zero otherwise, with a per-file, per-field
actionable message.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

CONTRACT_VERSION = "v1"

SCHEMA_FILENAMES = {
    "simplicio.loop-execution/v1": "loop-execution.schema.json",
    "simplicio.executor-contract/v1": "executor-contract.schema.json",
    "simplicio.ecosystem-graph/v1": "ecosystem-graph.schema.json",
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

_PINNED_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class ContractError(RuntimeError):
    """Raised for validator/setup problems (missing schema, bad fixture path)."""


def find_default_schema_root(start: str | None = None) -> str:
    """Locate ``contracts/ecosystem/v1/schemas`` by walking upward from ``start``."""
    here = os.path.abspath(start or os.getcwd())
    while True:
        candidate = os.path.join(here, "simplicio_mapper", "contracts", "ecosystem", CONTRACT_VERSION, "schemas")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    raise ContractError(
        "could not locate contracts/ecosystem/v1/schemas from "
        f"{start or os.getcwd()} or its parents. Pass --schema-root explicitly "
        "when running this script outside a simplicio-mapper checkout "
        "(e.g. from a vendored copy in another ecosystem repository)."
    )


def find_default_fixtures_root(schema_root: str) -> str:
    return os.path.join(os.path.dirname(schema_root), "fixtures")


def load_schema(schema_id: str, schema_root: str) -> dict:
    filename = SCHEMA_FILENAMES.get(schema_id)
    if not filename:
        raise ContractError(
            f'unknown schema id "{schema_id}" (known: {sorted(SCHEMA_FILENAMES)})'
        )
    path = os.path.join(schema_root, filename)
    if not os.path.isfile(path):
        raise ContractError(f"schema file missing: {path}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _type_matches(value: object, expected: str) -> bool:
    py_type = _PY_TYPE_NAMES.get(expected)
    if py_type is None:
        return True
    if expected in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, py_type)


def _validate_node(value: object, schema: dict, path: str, errors: list[str]) -> None:
    expected_types = schema.get("type")
    if expected_types:
        types = [expected_types] if isinstance(expected_types, str) else list(expected_types)
        if not any(_type_matches(value, t) for t in types):
            errors.append(f"{path}: expected type {types}, got {type(value).__name__}")
            return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in enum {schema['enum']}")

    if isinstance(value, dict):
        for required_key in schema.get("required", []):
            if required_key not in value:
                errors.append(f"{path}: missing required property '{required_key}'")
        properties = schema.get("properties", {})
        for key, sub_schema in properties.items():
            if key in value:
                _validate_node(value[key], sub_schema, f"{path}.{key}", errors)

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: has {len(value)} items, expected at least {min_items}")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate_node(item, item_schema, f"{path}[{index}]", errors)


def validate_instance(instance: object, schema: dict) -> list[str]:
    errors: list[str] = []
    _validate_node(instance, schema, "$", errors)
    return errors


def _duplicate_ids(items: object, label: str) -> list[str]:
    if not isinstance(items, list):
        return []
    errors: list[str] = []
    seen: set[str] = set()
    singular = {
        "repositories": "repository",
        "edges": "edge",
        "references": "reference",
    }.get(label, label.rstrip("s"))
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        value = item.get("id")
        if not isinstance(value, str) or not value.strip():
            continue
        if value in seen:
            errors.append(f"$.{label}[{index}].id: duplicate {singular} id {value!r}")
        seen.add(value)
    return errors


def _valid_pinned_revision(value: object) -> bool:
    return isinstance(value, str) and bool(_PINNED_REVISION.fullmatch(value))


def _validate_evidence(items: object, path: str) -> list[str]:
    if not isinstance(items, list):
        return []
    errors: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str) and not url.startswith("https://"):
            errors.append(f"{path}[{index}].url: evidence URL must use https")
        revision = item.get("revision")
        if revision is not None and not _valid_pinned_revision(revision):
            errors.append(
                f"{path}[{index}].revision: expected a full 40- or 64-hex immutable revision"
            )
    return errors


def validate_ecosystem_graph_semantics(payload: dict) -> list[str]:
    errors: list[str] = []
    repositories = payload.get("repositories")
    edges = payload.get("edges")
    references = payload.get("references")

    errors.extend(_duplicate_ids(repositories, "repositories"))
    errors.extend(_duplicate_ids(edges, "edges"))
    errors.extend(_duplicate_ids(references, "references"))

    repo_ids: set[str] = set()
    if isinstance(repositories, list):
        for index, repo in enumerate(repositories):
            if not isinstance(repo, dict):
                continue
            repo_id = repo.get("id")
            if isinstance(repo_id, str) and repo_id:
                repo_ids.add(repo_id)
            url = repo.get("url")
            if isinstance(url, str) and not url.startswith("https://"):
                errors.append(f"$.repositories[{index}].url: repository URL must use https")
            if repo.get("access") == "available" and not _valid_pinned_revision(repo.get("revision")):
                errors.append(
                    f"$.repositories[{index}].revision: available repository requires a full 40- or 64-hex immutable revision"
                )
            errors.extend(_validate_evidence(repo.get("evidence"), f"$.repositories[{index}].evidence"))

    if isinstance(edges, list):
        for index, edge in enumerate(edges):
            if not isinstance(edge, dict):
                continue
            source = edge.get("from")
            target = edge.get("to")
            if isinstance(source, str) and source not in repo_ids:
                errors.append(f"$.edges[{index}].from: unknown repository id {source!r}")
            if isinstance(target, str) and target not in repo_ids:
                errors.append(f"$.edges[{index}].to: unknown repository id {target!r}")
            errors.extend(_validate_evidence(edge.get("evidence"), f"$.edges[{index}].evidence"))

    if isinstance(references, list):
        for index, reference in enumerate(references):
            if not isinstance(reference, dict):
                continue
            url = reference.get("url")
            if isinstance(url, str) and not url.startswith("https://"):
                errors.append(f"$.references[{index}].url: reference URL must use https")
            boundary = reference.get("boundary")
            if isinstance(boundary, str) and not boundary.strip():
                errors.append(f"$.references[{index}].boundary: boundary must not be empty")

    boundaries = payload.get("boundaries")
    if isinstance(boundaries, list):
        for index, boundary in enumerate(boundaries):
            if not isinstance(boundary, str) or not boundary.strip():
                errors.append(f"$.boundaries[{index}]: boundary must be a non-empty string")

    return errors


def validate_payload(payload: dict, schema_root: str) -> tuple[str, list[str]]:
    schema_id = payload.get("schema")
    if not schema_id:
        raise ContractError('payload has no "schema" field to look up a contract by')
    schema = load_schema(schema_id, schema_root)
    errors = validate_instance(payload, schema)
    if schema_id == "simplicio.ecosystem-graph/v1":
        errors.extend(validate_ecosystem_graph_semantics(payload))
    return schema_id, errors


def validate_file(path: str, schema_root: str) -> tuple[str, list[str]]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return validate_payload(payload, schema_root)


def iter_json_files(paths: list[str]) -> list[str]:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate ecosystem-contract JSON payloads against contracts/ecosystem/v1 schemas."
    )
    parser.add_argument(
        "--schema-root",
        default=None,
        help="Directory containing *.schema.json files (default: auto-discover contracts/ecosystem/v1/schemas by walking up from cwd).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="File(s)/dir(s) to validate (default: the fixtures/ directory next to --schema-root).",
    )
    args = parser.parse_args(argv)

    try:
        schema_root = os.path.abspath(args.schema_root) if args.schema_root else find_default_schema_root()
    except ContractError as error:
        print(f"::error::{error}", flush=True)
        return 1

    paths = args.paths or [find_default_fixtures_root(schema_root)]

    try:
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
            schema_id, errors = validate_file(file_path, schema_root)
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


if __name__ == "__main__":
    sys.exit(main())
