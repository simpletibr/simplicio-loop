"""Canonical Mapper generation binding for Dev CLI plans and receipts.

The Dev CLI owns mechanical transformations, but it must never guess which
Mapper observation produced a plan.  This module validates and canonicalizes
that observation identity without mapping source files or applying effects.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

MAPPER_BINDING_SCHEMA = "simplicio.mapper-binding/v1"
_HASH_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_SAFE_REPOSITORY = re.compile(r"^[^\\s/]+/[^\\s/]+$")


class MapperBindingError(ValueError):
    """Raised when a Mapper observation binding is not canonical."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalise_hash(value: Any) -> str | None:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        return None
    return value.removeprefix("sha256:")


def _normalise_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    path = value.replace("\\", "/")
    portable = PurePosixPath(path)
    if (
        not path
        or path in {".", ".."}
        or path.startswith("/")
        or PureWindowsPath(path).is_absolute()
        or any(part in {"", ".", ".."} for part in portable.parts)
        or any(ord(char) < 32 for char in path)
    ):
        return None
    return path


def _body(value: Mapping[str, Any]) -> dict[str, Any]:
    source_hashes = value.get("source_hashes")
    normalised_hashes: dict[str, str] = {}
    if isinstance(source_hashes, Mapping):
        for raw_path, raw_hash in source_hashes.items():
            path = _normalise_path(raw_path)
            digest = _normalise_hash(raw_hash)
            if path is not None and digest is not None:
                normalised_hashes[path] = digest
    generation = value.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, (str, int)):
        generation_value = generation
    else:
        generation_value = str(generation)
    return {
        "schema": MAPPER_BINDING_SCHEMA,
        "repository_id": value.get("repository_id"),
        "generation": generation_value,
        "source_tree_id": value.get("source_tree_id"),
        "source_hashes": dict(sorted(normalised_hashes.items())),
    }


def validate_mapper_binding(
    value: Any, *, require_source_hashes: bool = True
) -> list[str]:
    """Return stable diagnostics for a canonical Mapper observation binding."""
    if not isinstance(value, Mapping):
        return ["mapper_binding must be an object"]
    errors: list[str] = []
    if value.get("schema") != MAPPER_BINDING_SCHEMA:
        errors.append(f"mapper_binding.schema must be {MAPPER_BINDING_SCHEMA!r}")
    repository_id = value.get("repository_id")
    if not isinstance(repository_id, str) or not repository_id.strip():
        errors.append("mapper_binding.repository_id must be a non-empty string")
    generation = value.get("generation")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, (str, int))
        or not str(generation).strip()
    ):
        errors.append("mapper_binding.generation must be a non-empty string or integer")
    source_tree_id = value.get("source_tree_id")
    if not isinstance(source_tree_id, str) or not source_tree_id.strip():
        errors.append("mapper_binding.source_tree_id must be a non-empty string")
    source_hashes = value.get("source_hashes")
    if not isinstance(source_hashes, Mapping):
        errors.append("mapper_binding.source_hashes must be an object")
    elif require_source_hashes and not source_hashes:
        errors.append("mapper_binding.source_hashes must not be empty")
    else:
        seen: set[str] = set()
        for raw_path, raw_hash in source_hashes.items():
            path = _normalise_path(raw_path)
            if path is None:
                errors.append(
                    f"mapper_binding.source_hashes contains an unsafe path: {raw_path!r}"
                )
            elif path in seen:
                errors.append(
                    f"mapper_binding.source_hashes contains duplicate path: {path!r}"
                )
            else:
                seen.add(path)
            if _normalise_hash(raw_hash) is None:
                errors.append(
                    f"mapper_binding.source_hashes[{raw_path!r}] must be a SHA-256 digest"
                )
    if "binding_digest" in value:
        digest = value.get("binding_digest")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(
                "mapper_binding.binding_digest must be a lowercase SHA-256 hex digest"
            )
        elif not errors and digest != _digest(_body(value)):
            errors.append(
                "mapper_binding.binding_digest does not match the canonical binding"
            )
    return sorted(set(errors))


def canonical_mapper_binding(
    value: Mapping[str, Any], *, require_source_hashes: bool = True
) -> dict[str, Any]:
    """Return a normalized binding with a self-checking digest."""
    errors = validate_mapper_binding(value, require_source_hashes=require_source_hashes)
    if errors:
        raise MapperBindingError("; ".join(errors))
    body = _body(value)
    body["binding_digest"] = _digest(body)
    return body


def build_mapper_binding(
    repository_id: str,
    generation: str | int,
    source_tree_id: str,
    source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Build a deterministic binding from Mapper-owned observation metadata."""
    return canonical_mapper_binding(
        {
            "schema": MAPPER_BINDING_SCHEMA,
            "repository_id": repository_id,
            "generation": generation,
            "source_tree_id": source_tree_id,
            "source_hashes": dict(source_hashes),
        }
    )


def mapper_binding_digest(value: Mapping[str, Any]) -> str:
    """Return the digest of the binding body, excluding its self-digest."""
    return _digest(_body(canonical_mapper_binding(value)))


def verify_mapper_sources(
    binding: Mapping[str, Any],
    observed_hashes: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    """Compare an observed workspace snapshot with expected Mapper hashes."""
    canonical = canonical_mapper_binding(binding)
    errors: list[dict[str, Any]] = []
    for path, expected in canonical["source_hashes"].items():
        actual = _normalise_hash(observed_hashes.get(path))
        if actual is None:
            errors.append(
                {
                    "code": "missing_target",
                    "message": f"Mapper source target is missing: {path}",
                    "path": path,
                    "expected": expected,
                }
            )
        elif actual != expected:
            errors.append(
                {
                    "code": "hash_drift",
                    "message": f"Mapper source hash drifted: {path}",
                    "path": path,
                    "expected": expected,
                    "actual": actual,
                }
            )
    return errors


def conflict_receipt(code: str, message: str, **details: Any) -> dict[str, Any]:
    """Create a typed, non-applying conflict outcome."""
    allowed = {
        "missing_target",
        "ambiguous_anchor",
        "hash_drift",
        "invalid_path",
        "unsupported_scaffold",
    }
    if code not in allowed:
        raise ValueError(f"unsupported conflict code: {code}")
    return {"status": "blocked", "code": code, "message": message, **details}


__all__ = [
    "MAPPER_BINDING_SCHEMA",
    "MapperBindingError",
    "build_mapper_binding",
    "canonical_mapper_binding",
    "conflict_receipt",
    "mapper_binding_digest",
    "validate_mapper_binding",
    "verify_mapper_sources",
]
