"""Ecosystem contract validator + ``doctor --contracts`` CLI (issue #164).

Extends ``simplicio_mapper/contract.py`` (mapper-artifacts/v1, issue #157)
with cross-repo payload shapes that flow through the ecosystem outside the
mapper itself: the ``simplicio-loop`` run-journal/task-anchor execution record,
the ``simplicio-dev-cli`` 6-layer executor contract record, and the renderer-
neutral repository/evidence graph consumed by tools such as Simplicio Canvas.
Schemas + fixtures live in ``contracts/ecosystem/v1/`` -- see that directory's
README for the explicit ownership and cross-repo sync convention.

This module reuses the validator engine from ``simplicio_mapper.contract``
(no need to duplicate it inside the installed package -- the *portable*,
dependency-free duplicate lives at ``scripts/validate_ecosystem_contracts.py``
specifically so other repos can vendor a single file without depending on
``simplicio_mapper`` being installed).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from .contract import ContractError, iter_json_files, validate_instance

CONTRACT_VERSION = "v1"

SCHEMA_FILENAMES = {
    "simplicio.loop-execution/v1": "loop-execution.schema.json",
    "simplicio.executor-contract/v1": "executor-contract.schema.json",
    "simplicio.ecosystem-graph/v1": "ecosystem-graph.schema.json",
}

_PINNED_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def find_ecosystem_contract_root(start: str | None = None) -> str:
    """Locate ``contracts/ecosystem/v1`` by walking upward from ``start``."""
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
        root = os.path.join(candidate, "contracts", "ecosystem", CONTRACT_VERSION)
        if os.path.isdir(os.path.join(root, "schemas")):
            return root
    raise ContractError(
        "could not locate contracts/ecosystem/v1/schemas/ from "
        f"{start or os.getcwd()} or its parents. Run this from within a "
        "simplicio-mapper checkout (not currently shipped in the published "
        "package -- see contracts/ecosystem/v1/README.md)."
    )


def load_schema(schema_id: str, contract_root: str) -> dict:
    filename = SCHEMA_FILENAMES.get(schema_id)
    if not filename:
        raise ContractError(
            f'unknown ecosystem schema id "{schema_id}" (known: {sorted(SCHEMA_FILENAMES)})'
        )
    path = os.path.join(contract_root, "schemas", filename)
    if not os.path.isfile(path):
        raise ContractError(f"schema file missing: {path}")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _duplicate_ids(items: object, label: str) -> list[str]:
    if not isinstance(items, list):
        return []
    errors: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        value = item.get("id")
        if not isinstance(value, str) or not value.strip():
            continue
        if value in seen:
            errors.append(f"$.{label}[{index}].id: duplicate {label[:-1]} id {value!r}")
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
    """Validate graph invariants that the intentionally small JSON-Schema subset cannot express.

    The ecosystem contract is a navigable evidence graph, not merely a shape.  It
    must fail closed on identity duplication, dangling endpoints, unpinned
    available repositories, unsafe evidence links, and empty claim boundaries.
    """
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


def validate_payload(payload: dict, contract_root: str) -> tuple[str, list[str]]:
    schema_id = payload.get("schema")
    if not schema_id:
        raise ContractError('payload has no "schema" field to look up a contract by')
    schema = load_schema(schema_id, contract_root)
    errors = validate_instance(payload, schema)
    if schema_id == "simplicio.ecosystem-graph/v1":
        errors.extend(validate_ecosystem_graph_semantics(payload))
    return schema_id, errors


def validate_file(path: str, contract_root: str) -> tuple[str, list[str]]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return validate_payload(payload, contract_root)


def _validate_tree(paths: list[str], contract_root: str, label: str, validate_file_fn=None) -> bool:
    """Validate every *.json under ``paths`` against ``contract_root``.

    ``validate_file_fn`` defaults to this module's own ``validate_file``
    (ecosystem/v1 schemas); pass ``contract.validate_file`` explicitly when
    validating a mapper-artifacts/v1 tree so the right ``SCHEMA_FILENAMES``
    map is used -- the two contract roots are not interchangeable.

    Returns True if everything passed (or was skippably not a recognized
    contract payload), False if any file failed validation. Prints
    ``[ok]``/``[fail]``/``[skip]`` lines prefixed with ``label`` so combined
    output from multiple contract roots (mapper-artifacts + ecosystem) stays
    distinguishable.
    """
    validate_file_fn = validate_file_fn or validate_file
    try:
        json_files = iter_json_files(paths)
    except ContractError as error:
        print(f"::error::[{label}] {error}", flush=True)
        return False
    if not json_files:
        print(f"::error::[{label}] no *.json files found under the given path(s)", flush=True)
        return False

    ok = True
    for file_path in json_files:
        try:
            schema_id, errors = validate_file_fn(file_path, contract_root)
        except ContractError as error:
            print(f"[skip] [{label}] {file_path}: {error}")
            continue
        if errors:
            ok = False
            print(f"[fail] [{label}] {file_path} ({schema_id}):")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"[ok]   [{label}] {file_path} ({schema_id})")
    return ok


def run_doctor_cli(argv: list[str]) -> int:
    """Entry point for ``simplicio-mapper doctor [--contracts] [<path> ...]``.

    Validates both ``contracts/mapper-artifacts/v1/`` fixtures (issue #157)
    and ``contracts/ecosystem/v1/`` fixtures (issue #164) by default. Extra
    positional paths are validated additionally against the ecosystem schemas
    (e.g. real ``.simplicio/*.json`` output is out of scope here -- use
    ``simplicio-mapper contract validate`` for that instead).
    """
    if not argv or "--contracts" not in argv:
        print(
            "usage: simplicio-mapper doctor --contracts [<path> ...]\n"
            "  validates contracts/mapper-artifacts/v1/ and contracts/ecosystem/v1/\n"
            "  fixtures against their schemas (exit 0 when all valid).",
            flush=True,
        )
        return 2

    cross_repo = "--cross-repo" in argv
    extra_paths = [arg for arg in argv if arg not in {"--contracts", "--cross-repo"}]

    overall_ok = True

    # 1. mapper-artifacts/v1 (issue #157) -- reuse contract.py's own root/fixtures
    #    AND its own validate_file (different SCHEMA_FILENAMES map than ecosystem/v1).
    try:
        from .contract import find_contract_root
        from .contract import validate_file as mapper_validate_file

        mapper_root = find_contract_root()
        mapper_fixtures = os.path.join(mapper_root, "fixtures")
        if os.path.isdir(mapper_fixtures):
            overall_ok &= _validate_tree(
                [mapper_fixtures], mapper_root, "mapper-artifacts/v1", validate_file_fn=mapper_validate_file
            )
        else:
            print("::error::[mapper-artifacts/v1] fixtures/ directory missing", flush=True)
            overall_ok = False
    except ContractError as error:
        print(f"::error::[mapper-artifacts/v1] {error}", flush=True)
        overall_ok = False

    # 2. ecosystem/v1 -- cross-repository payload schemas + fixtures.
    try:
        eco_root = find_ecosystem_contract_root()
        eco_fixtures = os.path.join(eco_root, "fixtures")
        paths = [eco_fixtures] if os.path.isdir(eco_fixtures) else []
        if not paths:
            print("::error::[ecosystem/v1] fixtures/ directory missing", flush=True)
            overall_ok = False
        else:
            overall_ok &= _validate_tree(paths, eco_root, "ecosystem/v1")
        if extra_paths:
            overall_ok &= _validate_tree(extra_paths, eco_root, "ecosystem/v1:extra")
    except ContractError as error:
        print(f"::error::[ecosystem/v1] {error}", flush=True)
        overall_ok = False

    print(f"contract status: {'local-shape-valid' if overall_ok else 'local-shape-invalid'}", flush=True)
    if cross_repo:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        runner = os.path.join(repo_root, "scripts", "cross_repo_conformance.py")
        if not os.path.isfile(runner):
            print("::error::cross-repo-conformant unavailable: runner missing", flush=True)
            return 1
        result = subprocess.run([sys.executable, runner], cwd=repo_root, check=False)
        print(
            f"contract status: {'cross-repo-conformant' if result.returncode == 0 else 'cross-repo-incompatible'}",
            flush=True,
        )
        overall_ok = overall_ok and result.returncode == 0
    else:
        print("contract status: cross-repo-conformant=not-run (use --cross-repo)", flush=True)
    return 0 if overall_ok else 1
