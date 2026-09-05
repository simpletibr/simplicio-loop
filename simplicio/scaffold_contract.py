"""Pure deterministic scaffold planning owned by the Dev CLI."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .mapper_binding import (
    canonical_mapper_binding,
    mapper_binding_digest,
    validate_mapper_binding,
)

SCAFFOLD_PLAN_SCHEMA = "simplicio.dev-cli.scaffold-plan/v1"
_SUPPORTED = {"python-package", "node-package", "rust-crate"}
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _blocked(code: str, message: str) -> dict[str, Any]:
    return {
        "schema": SCAFFOLD_PLAN_SCHEMA,
        "status": "blocked",
        "errors": [{"code": code, "message": message}],
        "operations": [],
    }


def plan_scaffold(
    kind: str, name: str, *, mapper_binding: Mapping[str, Any]
) -> dict[str, Any]:
    """Create a pure create-file plan; Runtime remains the effect authority."""
    if kind not in _SUPPORTED:
        return _blocked("unsupported_scaffold", f"unsupported scaffold kind: {kind!r}")
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        return _blocked(
            "invalid_path", "scaffold name must be a safe project identifier"
        )
    binding_errors = validate_mapper_binding(mapper_binding)
    if binding_errors:
        return _blocked("invalid_mapper_binding", "; ".join(binding_errors))
    binding = canonical_mapper_binding(mapper_binding)
    if kind == "python-package":
        operations = [
            {
                "op": "create_file",
                "path": f"{name}/__init__.py",
                "text": '"""Generated package."""\n',
            },
            {
                "op": "create_file",
                "path": f"{name}/pyproject.toml",
                "text": f'[project]\nname = "{name}"\nversion = "0.1.0"\n',
            },
        ]
    elif kind == "node-package":
        operations = [
            {
                "op": "create_file",
                "path": f"{name}/package.json",
                "text": _canonical({"name": name, "version": "0.1.0"}) + "\n",
            },
        ]
    else:
        operations = [
            {
                "op": "create_file",
                "path": f"{name}/Cargo.toml",
                "text": f'[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n',
            },
        ]
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


__all__ = ["SCAFFOLD_PLAN_SCHEMA", "plan_scaffold"]
