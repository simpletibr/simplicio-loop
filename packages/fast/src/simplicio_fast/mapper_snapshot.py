"""Compile validated Mapper parser facts into a disposable Fast snapshot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .snapshot import (
    KIND_TO_ID,
    MAPPER_HANDOFF_SCHEMA,
    Relation,
    SNAPSHOT_PROVENANCE_SCHEMA,
    Snapshot,
    Symbol,
    VERSION,
    _build_v2,
)


MAPPER_SNAPSHOT_SCHEMA = "simplicio.fast.mapper-snapshot/v1"

_KIND_ALIASES = {
    "method": "function",
    "constructor": "function",
    "field": "property",
    "constant": "property",
    "variable": "property",
    "module": "namespace",
    "package": "namespace",
    "record": "class",
    "delegate": "function",
}


def _internal_id(mapper_id: str) -> str:
    return hashlib.sha256(("mapper:" + mapper_id).encode("utf-8")).hexdigest()


def _kind(value: object) -> str:
    candidate = str(value or "function").casefold()
    candidate = _KIND_ALIASES.get(candidate, candidate)
    return candidate if candidate in KIND_TO_ID else "function"


def compile_mapper_payload(
    root: Path,
    payload: Mapping[str, Any],
    output: Path,
    *,
    mapper_generation: str,
    handoff_sha256: str,
    mapper_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile parser-adapter/v1 facts without reparsing source files."""
    if payload.get("schema") != "simplicio.fast.parser-adapter/v1":
        raise ValueError("mapper_payload_schema_unsupported")
    if payload.get("mode") != "integrated":
        raise ValueError("mapper_projection_requires_canonical_input")
    if not isinstance(mapper_generation, str) or not mapper_generation.strip():
        raise ValueError("mapper_generation_missing")
    files = payload.get("files")
    symbols = payload.get("symbols")
    relations = payload.get("relations")
    if not isinstance(files, list) or not isinstance(symbols, list) or not isinstance(relations, list):
        raise ValueError("mapper_payload_shape_invalid")

    root = root.resolve()
    entries: list[tuple[str, bytes, int, list[Symbol]]] = []
    symbols_by_file: dict[str, list[Symbol]] = {}
    mapper_ids: dict[str, str] = {}
    for item in symbols:
        if not isinstance(item, Mapping):
            raise ValueError("mapper_symbol_invalid")
        mapper_id = item.get("id")
        relative = item.get("file")
        line = item.get("line")
        end_line = item.get("end_line", line)
        if (
            not isinstance(mapper_id, str)
            or not isinstance(relative, str)
            or not isinstance(line, int)
            or isinstance(line, bool)
            or not isinstance(end_line, int)
            or isinstance(end_line, bool)
            or line < 1
            or end_line < line
        ):
            raise ValueError("mapper_symbol_invalid")
        normalized = relative.replace("\\", "/")
        internal_id = _internal_id(mapper_id)
        symbol = Symbol(
            name=str(item.get("name") or mapper_id.rsplit("::", 1)[-1]),
            qualified_name=str(item.get("qualified_name") or mapper_id),
            kind=_kind(item.get("kind")),
            file=normalized,
            line=line,
            end_line=end_line,
            symbol_id=internal_id,
            signature=mapper_id,
        )
        symbols_by_file.setdefault(normalized, []).append(symbol)
        mapper_ids[mapper_id] = internal_id

    for item in files:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise ValueError("mapper_file_invalid")
        relative = str(item["path"]).replace("\\", "/")
        path = (root / relative).resolve()
        if not path.is_file() or not path.is_relative_to(root):
            raise ValueError("mapper_source_missing")
        data = path.read_bytes()
        declared = item.get("sha256")
        actual = hashlib.sha256(data).hexdigest()
        normalized = hashlib.sha256(data.decode("utf-8").replace("\r\n", "\n").encode("utf-8")).hexdigest()
        if declared not in {actual, normalized}:
            raise ValueError("mapper_source_digest_mismatch")
        entries.append(
            (
                relative,
                bytes.fromhex(actual),
                len(data),
                symbols_by_file.get(relative, []),
            )
        )

    compiled_relations: list[Relation] = []
    for item in relations:
        if not isinstance(item, Mapping):
            raise ValueError("mapper_relation_invalid")
        kind = str(item.get("kind") or "reference")
        if kind not in {"import", "reference", "call", "definition", "test"}:
            continue
        origin_id = mapper_ids.get(str(item.get("origin_id") or ""), "")
        destination_id = mapper_ids.get(str(item.get("destination_id") or ""), "")
        compiled_relations.append(
            Relation(
                str(item.get("origin") or ""),
                str(item.get("destination") or ""),
                kind,
                float(item.get("confidence", 0.0)),
                origin_id,
                destination_id,
            )
        )

    source = dict(mapper_provenance or {})
    source_generation = source.get("generation", mapper_generation)
    if source_generation != mapper_generation:
        raise ValueError("mapper_generation_mismatch")
    artifact_digest = str(source.get("artifact_digest") or handoff_sha256)
    artifact_digest = artifact_digest.removeprefix("sha256:")
    if len(artifact_digest) != 64 or any(
        character not in "0123456789abcdef" for character in artifact_digest
    ):
        raise ValueError("mapper_artifact_digest_invalid")
    mapper_version = str(source.get("mapper_version") or "unknown")
    repository_id = str(source.get("repository_id") or root.name)
    capability_coverage = source.get("capability_coverage")
    if not isinstance(capability_coverage, Mapping):
        capability_coverage = {
            "context_graph": True,
            "files": bool(files),
            "symbols": bool(symbols),
            "relations": True,
            "source_hashes": True,
            "stable_handles": True,
        }
    provenance = {
        "schema": SNAPSHOT_PROVENANCE_SCHEMA,
        "mode": "integrated",
        "authority": "simplicio-mapper",
        "mapper_schema": str(source.get("mapper_schema") or MAPPER_HANDOFF_SCHEMA),
        "mapper_version": mapper_version,
        "repository_id": repository_id,
        "mapper_generation": mapper_generation,
        "artifact_digest": artifact_digest,
        "fast_format_version": VERSION,
        "capability_coverage": dict(capability_coverage),
    }
    _build_v2(entries, compiled_relations, output, provenance=provenance)
    with Snapshot(output) as snapshot:
        generation = snapshot.generation
    sidecar = output.with_name(output.name + ".mapper.json")
    sidecar.write_text(
        json.dumps(
            {
                "schema": MAPPER_SNAPSHOT_SCHEMA,
                "mapper_generation": mapper_generation,
                "handoff_sha256": handoff_sha256,
                "mapper_schema": provenance["mapper_schema"],
                "mapper_version": mapper_version,
                "repository_id": repository_id,
                "artifact_digest": artifact_digest,
                "fast_format_version": provenance["fast_format_version"],
                "capability_coverage": provenance["capability_coverage"],
                "fast_generation": generation,
                "files": len(entries),
                "symbols": sum(len(item[3]) for item in entries),
                "relations": len(compiled_relations),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "schema": MAPPER_SNAPSHOT_SCHEMA,
        "mapper_generation": mapper_generation,
        "mapper_schema": provenance["mapper_schema"],
        "mapper_version": mapper_version,
        "repository_id": repository_id,
        "artifact_digest": artifact_digest,
        "fast_format_version": provenance["fast_format_version"],
        "capability_coverage": provenance["capability_coverage"],
        "fast_generation": generation,
        "files": len(entries),
        "symbols": sum(len(item[3]) for item in entries),
        "relations": len(compiled_relations),
    }


__all__ = ["MAPPER_SNAPSHOT_SCHEMA", "compile_mapper_payload"]
