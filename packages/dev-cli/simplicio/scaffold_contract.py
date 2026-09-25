"""Pure deterministic scaffold planning owned by the Dev CLI."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from enum import Enum
from typing import Any

from .mapper_binding import (
    canonical_mapper_binding,
    mapper_binding_digest,
    validate_mapper_binding,
)

SCAFFOLD_PLAN_SCHEMA = "simplicio.dev-cli.scaffold-plan/v1"
SCAFFOLD_RECEIPT_SCHEMA = "simplicio.dev-cli.scaffold-receipt/v1"
_SUPPORTED = {"python-package", "node-package", "rust-crate", "rust-binary"}
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ScaffoldKind(str, Enum):
    RUST_CRATE = "rust-crate"
    RUST_BINARY = "rust-binary"
    PYTHON_PACKAGE = "python-package"
    NODE_PACKAGE = "node-package"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _blocked(code: str, message: str) -> dict[str, Any]:
    body = {
        "schema": SCAFFOLD_PLAN_SCHEMA,
        "status": "blocked",
        "errors": [{"code": code, "message": message}],
        "operations": [],
    }
    body["plan_digest"] = _digest(body)
    return body


def plan_scaffold(
    kind: str | ScaffoldKind, name: str, *, mapper_binding: Mapping[str, Any]
) -> dict[str, Any]:
    """Create a pure create-file plan; Runtime remains the effect authority."""
    if isinstance(kind, ScaffoldKind):
        kind = kind.value
    if not isinstance(kind, str) or kind not in _SUPPORTED:
        return _blocked("unsupported_scaffold", f"unsupported scaffold kind: {kind!r}")
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        return _blocked("invalid_path", "scaffold name must be a safe project identifier")
    binding_errors = validate_mapper_binding(mapper_binding)
    if binding_errors:
        return _blocked("invalid_mapper_binding", "; ".join(binding_errors))
    binding = canonical_mapper_binding(mapper_binding)
    module = "_".join(name.split("-"))
    if kind == "python-package":
        operations = [
            {
                "op": "create_file",
                "path": f"{name}/pyproject.toml",
                "text": f'[project]\nname = "{name}"\nversion = "0.1.0"\nrequires-python = ">=3.11"\n',
            },
            {
                "op": "create_file",
                "path": f"{name}/{module}/__init__.py",
                "text": f'"""{name}."""\n',
            },
        ]
    elif kind == "node-package":
        operations = [
            {
                "op": "create_file",
                "path": f"{name}/package.json",
                "text": f'{{\n  "name": "{name}",\n  "version": "0.1.0",\n  "type": "module"\n}}\n',
            },
            {
                "op": "create_file",
                "path": f"{name}/src/index.js",
                "text": f'export const name = "{name}";\n',
            },
        ]
    elif kind == "rust-binary":
        operations = [
            {
                "op": "create_file",
                "path": f"{name}/Cargo.toml",
                "text": f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n',
            },
            {
                "op": "create_file",
                "path": f"{name}/src/main.rs",
                "text": f'fn main() {{ println!("{name}"); }}\n',
            },
        ]
    else:
        operations = [
            {
                "op": "create_file",
                "path": f"{name}/Cargo.toml",
                "text": f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n',
            },
            {
                "op": "create_file",
                "path": f"{name}/src/lib.rs",
                "text": f'//! {name}\n\npub fn name() -> &\'static str {{ "{name}" }}\n',
            },
        ]
    operations.sort(key=lambda item: item["path"])
    body = {
        "schema": SCAFFOLD_PLAN_SCHEMA,
        "status": "planned",
        "kind": kind,
        "name": name,
        "mapper_binding": binding,
        "mapper_binding_digest": mapper_binding_digest(binding),
        "operations": operations,
        "runtime_authorization_required": True,
    }
    body["plan_digest"] = _digest(body)
    return body


def scaffold_receipt(
    plan: Mapping[str, Any],
    *,
    status: str = "planned",
    applied: bool = False,
    files: list[Mapping[str, Any]] | None = None,
    errors: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a stable scaffold receipt without performing filesystem effects.

    Runtime adapters may use this serializer after authorizing the plan.  The
    Dev CLI owns the receipt shape; Runtime owns whether the effect occurred.
    """

    receipt_errors = errors if errors is not None else plan.get("errors", [])
    receipt: dict[str, Any] = {
        "schema": SCAFFOLD_RECEIPT_SCHEMA,
        "status": status,
        "applied": applied,
        "kind": plan.get("kind"),
        "name": plan.get("name"),
        "plan_digest": plan.get("plan_digest"),
        "operations": list(plan.get("operations", [])),
        "files": [dict(row) for row in (files or [])],
        "errors": [dict(row) for row in receipt_errors],
        "runtime_authorization_required": plan.get("runtime_authorization_required", True),
    }
    binding = plan.get("mapper_binding")
    if isinstance(binding, Mapping):
        receipt["mapper_binding"] = dict(binding)
        receipt["mapper_binding_digest"] = mapper_binding_digest(binding)
    receipt["receipt_digest"] = _digest(receipt)
    return receipt


__all__ = [
    "SCAFFOLD_PLAN_SCHEMA",
    "SCAFFOLD_RECEIPT_SCHEMA",
    "ScaffoldKind",
    "plan_scaffold",
    "scaffold_receipt",
]
