"""Versioned parser-adapter payloads for the Python fallback path.

The adapter is deliberately a data contract around the existing language
adapters.  It does not expose snapshot offsets or replace Mapper's public
ContextGraph.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from .adapters import (
    SUPPORTED_EXTENSIONS,
    csharp_workspace_fingerprint,
    language_for_path,
    negotiate,
    parse_path,
    rust_workspace_fingerprint,
    typescript_workspace_fingerprint,
)
from .mapper_ingest import MapperIngestError, validate_handoff
from .projection import ProjectionEnvelope
from .snapshot import SourceParseError, _parse_file, stable_id

SCHEMA = "simplicio.fast.parser-adapter/v1"
SUPPORTED_MODES = {"bootstrap", "integrated"}
DEFAULT_LIMITS = {
    "max_files": 10_000,
    "max_symbols": 1_000_000,
    "max_relations": 2_000_000,
    "max_payload_bytes": 64 * 1024 * 1024,
}


def adapter_capability() -> dict[str, Any]:
    """Return the versioned, deterministic capability receipt for this adapter."""

    contract = {
        "schema": SCHEMA,
        "producer": "simplicio-fast-python-adapter",
        "limits": DEFAULT_LIMITS,
        "modes": sorted(SUPPORTED_MODES),
    }
    return {
        "schema": SCHEMA,
        "producer": contract["producer"],
        "version": "1",
        "health": "ready",
        "completeness": "contract",
        "modes": contract["modes"],
        "fingerprints": {"contract_sha256": _digest(contract)},
        "limits": dict(DEFAULT_LIMITS),
    }


class ParserAdapterError(ValueError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _mapper_artifact_path(root: Path, provenance: Mapping[str, Any], name: str) -> Path:
    artifacts = provenance.get("artifacts")
    if not isinstance(artifacts, (tuple, list)):
        raise ParserAdapterError("mapper_artifact_missing", name)
    artifact = next(
        (
            item
            for item in artifacts
            if isinstance(item, Mapping) and item.get("name") == name
        ),
        None,
    )
    if not isinstance(artifact, Mapping) or not isinstance(artifact.get("path"), str):
        raise ParserAdapterError("mapper_artifact_missing", name)
    path = (root / str(artifact["path"])).resolve()
    if not path.is_file() or not path.is_relative_to(root.resolve()):
        raise ParserAdapterError("mapper_artifact_missing", name)
    return path


def _mapper_json(root: Path, provenance: Mapping[str, Any], name: str) -> dict[str, Any]:
    path = _mapper_artifact_path(root, provenance, name)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ParserAdapterError("mapper_artifact_invalid", name) from error
    if not isinstance(value, dict):
        raise ParserAdapterError("mapper_artifact_invalid", name)
    return value


def _git_ignored(root: Path, paths: Iterable[str]) -> set[str]:
    candidates = sorted(set(paths))
    if not candidates:
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--stdin", "--no-index", "-z"],
            input=b"\0".join(path.encode("utf-8") for path in candidates) + b"\0",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            close_fds=True,
        )
    except OSError:
        return set()
    if result.returncode not in {0, 1}:
        return set()
    return {
        value.decode("utf-8")
        for value in result.stdout.split(b"\0")
        if value
    }


def build_payload_from_mapper(
    root: Path,
    mapper_handoff: Mapping[str, Any],
    *,
    limits: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Convert Mapper-owned language facts into the v1 adapter contract.

    Stable IDs are read only from the Mapper context snapshot.  The symbol and
    call indexes are metadata sources; they cannot invent or remap IDs.
    """

    root = root.resolve()
    try:
        provenance = validate_handoff(root, dict(mapper_handoff))
    except MapperIngestError as error:
        raise ParserAdapterError(error.reason_code) from error
    selected_limits = _adapter_limits(limits)
    symbols_doc = _mapper_json(root, provenance, "symbol_index")
    project_doc = _mapper_json(root, provenance, "project_map")
    context_doc = _mapper_json(root, provenance, "context_snapshot")
    calls_doc = _mapper_json(root, provenance, "call_graph")
    if symbols_doc.get("schema") != "simplicio.symbol-index/v1":
        raise ParserAdapterError("mapper_schema_unsupported", "symbol_index")
    if project_doc.get("schema") != "simplicio.project-map/v1":
        raise ParserAdapterError("mapper_schema_unsupported", "project_map")
    if context_doc.get("schema") != "simplicio.context-snapshot/v1":
        raise ParserAdapterError("mapper_schema_unsupported", "context_snapshot")
    if calls_doc.get("schema") != "simplicio.call-graph/v1":
        raise ParserAdapterError("mapper_schema_unsupported", "call_graph")
    graph = context_doc.get("graph")
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if not isinstance(nodes, list):
        raise ParserAdapterError("mapper_graph_missing")
    mapper_nodes: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            mapper_nodes[node["id"]] = node
    raw_files = project_doc.get("files")
    if not isinstance(raw_files, list):
        raise ParserAdapterError("mapper_files_missing")
    candidate_paths = [
        _safe_relative(item["path"])
        for item in raw_files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]
    ignored_paths = _git_ignored(root, candidate_paths)
    files: list[dict[str, Any]] = []
    file_languages: dict[str, str] = {}
    diagnostics: list[dict[str, Any]] = []
    for item in raw_files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ParserAdapterError("mapper_files_invalid")
        relative = _safe_relative(item["path"])
        if relative in ignored_paths:
            continue
        language = item.get("language")
        if not isinstance(language, str) or not language:
            raise ParserAdapterError("mapper_language_missing", relative)
        if language not in set(SUPPORTED_EXTENSIONS.values()) | {
            "html",
            "css",
            "javascript",
            "markdown",
            "shell",
        }:
            continue
        path = root / relative
        if not path.is_file():
            raise ParserAdapterError("source_missing", relative)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ParserAdapterError("encoding_invalid", relative) from error
        raw_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        normalized_digest = hashlib.sha256(
            text.replace("\r\n", "\n").encode("utf-8")
        ).hexdigest()
        declared_digest = item.get("file_hash")
        if declared_digest not in {raw_digest, normalized_digest}:
            raise ParserAdapterError("source_digest_mismatch", relative)
        file_id = f"file:{relative}"
        file_node = mapper_nodes.get(file_id)
        file_id_value = file_node.get("id") if isinstance(file_node, dict) else None
        file_record: dict[str, Any] = {
            "path": relative,
            "language": language,
            "sha256": declared_digest,
            "encoding": "utf-8",
        }
        if isinstance(file_id_value, str):
            file_record["id"] = file_id_value
        else:
            diagnostics.append(
                {"path": relative, "code": "mapper_file_id_missing", "detail": file_id}
            )
        files.append(
            file_record
        )
        file_languages[relative] = language
    if len(files) > selected_limits["max_files"]:
        raise ParserAdapterError("file_limit_exceeded")
    raw_symbols = symbols_doc.get("symbols")
    if not isinstance(raw_symbols, list):
        raise ParserAdapterError("mapper_symbols_missing")
    symbols: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_symbols:
        if not isinstance(item, dict):
            raise ParserAdapterError("mapper_symbols_invalid")
        qualified = item.get("qualified_name")
        relative_value = item.get("defined_in")
        line = item.get("line")
        if (
            not isinstance(qualified, str)
            or not isinstance(relative_value, str)
            or not isinstance(line, int)
            or isinstance(line, bool)
            or relative_value not in file_languages
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("kind"), str)
            or not isinstance(item.get("language", file_languages.get(relative_value)), str)
            or item.get("language", file_languages.get(relative_value)) not in set(SUPPORTED_EXTENSIONS.values()) | {"html", "css", "javascript"}
        ):
            diagnostics.append(
                {
                    "path": relative_value if isinstance(relative_value, str) else "",
                    "code": "mapper_symbols_skipped",
                    "detail": str(qualified or ""),
                }
            )
            continue
        relative = relative_value
        symbol_id = f"symbol:{qualified}"
        node = mapper_nodes.get(symbol_id)
        source = node.get("source") if isinstance(node, dict) else None
        if not isinstance(source, dict) or source.get("file") != relative or source.get("line") != line:
            diagnostics.append(
                {"path": relative, "code": "mapper_id_missing", "detail": qualified}
            )
            continue
        if symbol_id in seen_ids:
            diagnostics.append(
                {"path": relative, "code": "mapper_symbol_ambiguous", "detail": qualified}
            )
            continue
        seen_ids.add(symbol_id)
        symbols.append(
            {
                "id": symbol_id,
                "name": item.get("name"),
                "qualified_name": qualified,
                "kind": item.get("kind"),
                "language": item.get("language", file_languages[relative]),
                "file": relative,
                "line": line,
                "end_line": line,
                "signature": None,
            }
        )
    if len(symbols) > selected_limits["max_symbols"]:
        raise ParserAdapterError("symbol_limit_exceeded")
    if raw_symbols and not symbols:
        if any(d.get("code") == "mapper_symbols_skipped" for d in diagnostics):
            raise ParserAdapterError("mapper_symbols_invalid")
        raise ParserAdapterError("mapper_id_missing")
    symbol_ids = {item["qualified_name"]: item["id"] for item in symbols}
    raw_edges = calls_doc.get("edges")
    if not isinstance(raw_edges, list):
        raise ParserAdapterError("mapper_relations_missing")
    relations: list[dict[str, Any]] = []
    for edge in raw_edges:
        if not isinstance(edge, dict):
            raise ParserAdapterError("mapper_relations_invalid")
        source_file = edge.get("source_file")
        edge_type = edge.get("type")
        if not isinstance(source_file, str) or source_file not in file_languages:
            raise ParserAdapterError("mapper_relations_invalid")
        kind = {
            "calls": "call",
            "imports": "import",
            "defined_in": "definition",
            "member_of": "reference",
        }.get(str(edge_type))
        if kind is None:
            diagnostics.append(
                {"path": source_file, "code": "mapper_relation_kind_unsupported", "detail": str(edge_type)}
            )
            continue
        source_symbol = edge.get("source_symbol")
        target_symbol = edge.get("target_symbol")
        if kind == "import":
            origin = source_file
            destination = edge.get("import", target_symbol)
            origin_id = ""
            destination_id = symbol_ids.get(target_symbol, "") if isinstance(target_symbol, str) else ""
        else:
            if not isinstance(target_symbol, str):
                raise ParserAdapterError("mapper_relations_invalid")
            origin = source_symbol if isinstance(source_symbol, str) else source_file
            destination = target_symbol
            origin_id = symbol_ids.get(source_symbol, "") if isinstance(source_symbol, str) else ""
            destination_id = symbol_ids.get(target_symbol, "")
        if not isinstance(destination, str) or not destination:
            raise ParserAdapterError("mapper_relations_invalid")
        if kind != "import" and (
            not destination_id
            or (isinstance(source_symbol, str) and not origin_id)
        ):
            diagnostics.append(
                {
                    "path": source_file,
                    "code": "mapper_relation_id_missing",
                    "detail": f"{origin}->{target_symbol}",
                }
            )
            continue
        confidence = edge.get("confidence")
        if confidence is None:
            diagnostics.append(
                {
                    "path": source_file,
                    "code": "mapper_relation_confidence_unavailable",
                    "detail": f"{origin}->{destination}",
                }
            )
            continue
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            raise ParserAdapterError("mapper_relation_confidence_invalid")
        relations.append(
            {
                "origin": origin,
                "destination": destination,
                "kind": kind,
                "confidence": confidence,
                "origin_id": origin_id,
                "destination_id": destination_id,
                "file": source_file,
            }
        )
    if len(relations) > selected_limits["max_relations"]:
        raise ParserAdapterError("relation_limit_exceeded")
    files.sort(key=lambda item: item["path"])
    symbols.sort(key=lambda item: (item["file"], item["line"], item["id"]))
    relations.sort(key=lambda item: (item["file"], item["kind"], item["origin"], item["destination"]))
    changed_paths = sorted(
        _safe_relative(path) for path in provenance.get("changed_paths", [])
    )
    deleted_paths = sorted(
        _safe_relative(path) for path in provenance.get("deleted_paths", [])
    )
    if set(changed_paths).intersection(deleted_paths):
        raise ParserAdapterError("mapper_delta_invalid")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "adapter_version": "1",
        "mode": "integrated",
        "producer": "simplicio-fast-python-adapter",
        "source_adapter": "simplicio-mapper",
        "repository": str(root),
        "mapper_schema": provenance.get("mapper_schema", "simplicio.mapper-fast-handoff/v1"),
        "mapper_version": provenance.get("mapper_version", "unknown"),
        "artifact_digest": provenance.get("artifact_digest"),
        "capability_coverage": provenance.get("capability_coverage", {}),
        "commit": provenance["commit"],
        "mapper_generation": provenance["generation"],
        "config_fingerprint": _digest(project_doc.get("dependencies", {})),
        "changed_paths": changed_paths,
        "files": files,
        "symbols": symbols,
        "relations": relations,
        "diagnostics": diagnostics,
        "completeness": "complete" if not diagnostics else "partial",
        "invalidation": {
            "schema": "simplicio.fast.parser-invalidation/v1",
            "requested_paths": changed_paths,
            "parsed_paths": [
                item["path"] for item in files if item["path"] in changed_paths
            ]
            if changed_paths
            else [item["path"] for item in files],
            "reused_paths": [item["path"] for item in files if item["path"] not in changed_paths]
            if changed_paths
            else [],
            "deleted_paths": deleted_paths,
            "reason_codes": [
                "mapper_delta" if changed_paths or deleted_paths else "mapper_full_snapshot"
            ],
        },
    }
    payload["workspace_fingerprints"] = {}
    payload["payload_sha256"] = _digest(payload)
    if len(_canonical(payload)) > selected_limits["max_payload_bytes"]:
        raise ParserAdapterError("payload_limit_exceeded")
    return payload


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _safe_relative(path: str) -> str:
    if not isinstance(path, str) or not path or "\0" in path or ":" in path:
        raise ParserAdapterError("path_escape", path)
    normalized = path.replace("\\", "/")
    raw_parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or any(not part or part in {".", ".."} for part in raw_parts)
    ):
        raise ParserAdapterError("path_escape", path)
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute():
        raise ParserAdapterError("path_escape", path)
    return candidate.as_posix()


def _adapter_limits(limits: Mapping[str, int] | None) -> dict[str, int]:
    selected = dict(DEFAULT_LIMITS)
    if limits is not None:
        for name, value in limits.items():
            if name not in selected or isinstance(value, bool) or not isinstance(value, int):
                raise ParserAdapterError("limit_invalid", name)
            if value < 1:
                raise ParserAdapterError("limit_invalid", name)
            selected[name] = value
    return selected


def _source_files(root: Path, changed_paths: Iterable[str] | None) -> list[Path]:
    if changed_paths is None:
        ignored = {
            ".git",
            ".simplicio-loop",
            ".simplicio-fast",
            "__pycache__",
            "node_modules",
            "target",
            "bin",
            "obj",
        }
        found: list[Path] = []
        for directory, directories, filenames in os.walk(root, topdown=True):
            directories[:] = sorted(name for name in directories if name not in ignored)
            found.extend(
                Path(directory) / name
                for name in sorted(filenames)
                if language_for_path(Path(name)) is not None
            )
        return sorted(found)
    result: list[Path] = []
    for relative in changed_paths:
        safe = _safe_relative(relative)
        path = root / safe
        if path.is_file() and language_for_path(path) is not None:
            result.append(path)
    return sorted(set(result))


def _lexical_relations(
    path: Path,
    relative: str,
    language: str,
    symbols: list[Any],
    symbol_ids: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Emit bounded, deterministic relations for optional lexical adapters."""

    text = path.read_text(encoding="utf-8")
    relations: list[dict[str, Any]] = []
    for symbol in symbols:
        identifier = symbol_ids.get(symbol.qualified_name, "")
        relations.append(
            {
                "origin": symbol.qualified_name,
                "destination": symbol.qualified_name,
                "kind": "definition",
                "confidence": 0.75,
                "origin_id": identifier,
                "destination_id": identifier,
                "file": relative,
            }
        )
        if symbol.name.casefold().startswith(("test", "spec")):
            relations.append(
                {
                    "origin": relative,
                    "destination": symbol.qualified_name,
                    "kind": "test",
                    "confidence": 0.6,
                    "origin_id": "",
                    "destination_id": identifier,
                    "file": relative,
                }
            )
    import_pattern = {
        "typescript": re.compile(r"^\s*import\b.*?[\"']([^\"']+)[\"']"),
        "rust": re.compile(r"^\s*(?:pub\s+)?use\s+([^;]+)"),
        "csharp": re.compile(r"^\s*(?:global\s+)?using\s+([^;=]+)"),
    }[language]
    for line in text.splitlines():
        match = import_pattern.search(line)
        if match:
            relations.append(
                {
                    "origin": relative,
                    "destination": match.group(1).strip(),
                    "kind": "import",
                    "confidence": 0.5,
                    "origin_id": "",
                    "destination_id": "",
                    "file": relative,
                }
            )
    return relations


_RUST_CFG_ATTRIBUTE = re.compile(
    r"^\s*#\s*!?\s*\[\s*(?:cfg|cfg_attr)\s*\("
)
_RUST_MACRO_DECLARATION = re.compile(r"\bmacro_rules!\s*[A-Za-z_]\w*")
_RUST_MACRO_INVOCATION = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*!\s*[\(\[\{]"
)


def _rust_completeness_diagnostics(
    text: str, relative: str
) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    if any(_RUST_CFG_ATTRIBUTE.search(line) for line in text.splitlines()):
        diagnostics.append(
            {
                "path": relative,
                "code": "rust_cfg_unresolved",
                "detail": (
                    "cfg/cfg_attr branches are not evaluated by the bounded "
                    "lexical adapter"
                ),
                "fallback": (
                    "use Mapper-native or rust-analyzer parsing with selected "
                    "Cargo features and toolchain"
                ),
            }
        )
    if _RUST_MACRO_DECLARATION.search(text) or _RUST_MACRO_INVOCATION.search(text):
        diagnostics.append(
            {
                "path": relative,
                "code": "rust_macro_unexpanded",
                "detail": (
                    "Rust macro definitions and invocations are not expanded by "
                    "the bounded lexical adapter"
                ),
                "fallback": "use Mapper-native or rust-analyzer parsing",
            }
        )
    return diagnostics


def build_payload(
    root: Path,
    *,
    mapper_generation: str | None = None,
    commit: str | None = None,
    config_fingerprint: str | None = None,
    changed_paths: Iterable[str] | None = None,
    mode: str = "bootstrap",
    limits: Mapping[str, int] | None = None,
    previous_payload: Mapping[str, Any] | None = None,
    rust_features: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a deterministic, bounded contract payload from existing adapters."""

    root = root.resolve()
    if mode not in SUPPORTED_MODES:
        raise ParserAdapterError("mode_invalid", mode)
    if mode == "integrated" and (
        not isinstance(mapper_generation, str)
        or not mapper_generation.strip()
        or not isinstance(commit, str)
        or len(commit) != 40
    ):
        raise ParserAdapterError("mapper_required")
    selected_limits = _adapter_limits(limits)
    if previous_payload is not None and changed_paths is None:
        raise ParserAdapterError("previous_payload_requires_changed_paths")
    scoped = changed_paths is not None
    changed_set = {
        _safe_relative(path) for path in (changed_paths or ())
    }
    changed_paths = sorted(changed_set) if scoped else None
    previous: dict[str, Any] | None = None
    if previous_payload is not None:
        validate_payload(
            previous_payload,
            root=root,
            skip_file_paths=changed_set,
        )
        if previous_payload.get("repository") != str(root):
            raise ParserAdapterError("previous_repository_mismatch")
        previous = dict(previous_payload)
    files: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    diagnostics: list[dict[str, Any]] = []
    for path in _source_files(root, changed_paths):
        if len(files) >= selected_limits["max_files"]:
            raise ParserAdapterError("file_limit_exceeded")
        relative = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        try:
            source_text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            diagnostics.append(
                {"path": relative, "code": "encoding_invalid", "detail": str(error)}
            )
            continue
        language = SUPPORTED_EXTENSIONS[path.suffix.casefold()]
        files.append(
            {
                "path": relative,
                "language": language,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "encoding": "utf-8",
            }
        )
        capability = negotiate(language)
        if capability.status != "available":
            diagnostics.append(
                {
                    "path": relative,
                    "code": "native_parser_unavailable",
                    "detail": capability.reason or "adapter_fallback",
                    "fallback": capability.fallback,
                }
            )
        if language == "rust":
            diagnostics.extend(_rust_completeness_diagnostics(source_text, relative))
        try:
            if language == "python":
                parsed, parsed_relations = _parse_file(path, relative, str(root))
            else:
                parsed = parse_path(path, relative)
                lexical_ids = {
                    item.qualified_name: stable_id(
                        str(root), relative, language, item.qualified_name,
                        item.signature or item.kind,
                    )
                    for item in parsed
                }
                parsed_relations = _lexical_relations(
                    path, relative, language, parsed, lexical_ids
                )
        except (OSError, SourceParseError, SyntaxError, UnicodeDecodeError) as error:
            diagnostics.append(
                {
                    "path": relative,
                    "code": "parse_failed",
                    "detail": type(error).__name__,
                }
            )
            continue
        for item in parsed:
            if len(symbols) >= selected_limits["max_symbols"]:
                raise ParserAdapterError("symbol_limit_exceeded")
            signature = item.signature or item.kind
            # The Python path is the legacy Mapper-compatible extractor.  Its
            # Symbol already carries the historical ID, including the exact
            # signature treatment for classes and symbols without a
            # signature.  Reusing it is required for adapter/legacy parity;
            # lexical adapters still derive their bounded fallback IDs below.
            symbol_id = (
                item.symbol_id
                if language == "python" and item.symbol_id
                else stable_id(
                    str(root), relative, language, item.qualified_name, signature
                )
            )
            if symbol_id in seen_ids:
                # Lexical adapters cannot always recover overload signatures.
                # Keep the first historical ID stable and disambiguate later
                # declarations with their source span instead of rejecting a
                # valid overloaded corpus.
                symbol_id = stable_id(
                    str(root),
                    relative,
                    language,
                    item.qualified_name,
                    f"{signature}@{item.line}:{item.end_line}",
                )
            if symbol_id in seen_ids:
                raise ParserAdapterError("symbol_id_collision", symbol_id)
            seen_ids.add(symbol_id)
            symbols.append(
                {
                    "id": symbol_id,
                    "name": item.name,
                    "qualified_name": item.qualified_name,
                    "kind": item.kind,
                    "language": language,
                    "file": relative,
                    "line": item.line,
                    "end_line": item.end_line,
                    "signature": item.signature,
                }
            )
        symbol_ids = {
            item.qualified_name: item.symbol_id for item in parsed if item.symbol_id
        }
        for relation in parsed_relations:
            if len(relations) >= selected_limits["max_relations"]:
                raise ParserAdapterError("relation_limit_exceeded")
            if isinstance(relation, Mapping):
                destination = relation["destination"]
                origin = relation["origin"]
                kind = relation["kind"]
                confidence = relation["confidence"]
                origin_id = relation.get("origin_id", "")
                supplied_destination_id = relation.get("destination_id", "")
            else:
                destination = relation.destination
                origin = relation.origin
                kind = relation.kind
                confidence = relation.confidence
                origin_id = relation.origin_id
                supplied_destination_id = relation.destination_id
            destination_id = supplied_destination_id or symbol_ids.get(destination, "")
            relations.append(
                {
                    "origin": origin,
                    "destination": destination,
                    "kind": kind,
                    "confidence": confidence,
                    "origin_id": origin_id,
                    "destination_id": destination_id,
                    "file": relative,
                }
            )
    reused_paths: set[str] = set()
    deleted_paths: set[str] = set()
    if previous is not None:
        previous_files = {
            str(item["path"]): item for item in previous["files"]
        }
        current_paths = {str(item["path"]) for item in files}
        for path_name, item in previous_files.items():
            if path_name in changed_set:
                if not (root / path_name).is_file():
                    deleted_paths.add(path_name)
                continue
            if path_name in current_paths:
                continue
            files.append(dict(item))
            reused_paths.add(path_name)
        for item in previous["symbols"]:
            if item.get("file") in reused_paths:
                symbols.append(dict(item))
        for item in previous["relations"]:
            if item.get("file") in reused_paths:
                relations.append(dict(item))
        diagnostics.extend(
            item
            for item in previous["diagnostics"]
            if item.get("path") in reused_paths
        )
    files.sort(key=lambda item: str(item["path"]))
    symbols.sort(key=lambda item: (str(item["file"]), int(item["line"]), str(item["id"])))
    relations.sort(
        key=lambda item: (
            str(item["file"]),
            str(item["kind"]),
            str(item["origin"]),
            str(item["destination"]),
        )
    )
    diagnostics.sort(key=lambda item: (str(item.get("path", "")), str(item.get("code", ""))))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "adapter_version": "1",
        "mode": mode,
        "producer": "simplicio-fast-python-adapter",
        "repository": str(root),
        "commit": commit,
        "mapper_generation": mapper_generation,
        "config_fingerprint": config_fingerprint,
        "changed_paths": sorted(
            {_safe_relative(path) for path in (changed_paths or ())}
        ),
        "files": files,
        "symbols": symbols,
        "relations": relations,
        "diagnostics": diagnostics,
        "completeness": "complete" if not diagnostics else "partial",
        "invalidation": {
            "schema": "simplicio.fast.parser-invalidation/v1",
            "requested_paths": sorted(changed_set),
            "parsed_paths": sorted(item["path"] for item in files if item["path"] not in reused_paths),
            "reused_paths": sorted(reused_paths),
            "deleted_paths": sorted(deleted_paths),
            "reason_codes": [
                "full_scan" if not scoped else "explicit_changed_paths",
                *("previous_payload_reuse" if previous is not None else "no_previous_payload",),
            ],
        },
    }
    languages = {item["language"] for item in files}
    payload["workspace_fingerprints"] = {
        language: fingerprint
        for language, fingerprint in (
            ("csharp", csharp_workspace_fingerprint(root)),
            ("rust", rust_workspace_fingerprint(root, features=rust_features)),
            ("typescript", typescript_workspace_fingerprint(root)),
        )
        if language in languages
    }
    payload["payload_sha256"] = _digest(payload)
    if len(_canonical(payload)) > selected_limits["max_payload_bytes"]:
        raise ParserAdapterError("payload_limit_exceeded")
    return payload


def build_projection(
    root: Path,
    *,
    mapper_generation: str | None = None,
    commit: str | None = None,
    config_fingerprint: str | None = None,
    changed_paths: Iterable[str] | None = None,
    mode: str = "bootstrap",
    limits: Mapping[str, int] | None = None,
    previous_payload: Mapping[str, Any] | None = None,
    rust_features: Iterable[str] = (),
) -> ProjectionEnvelope:
    """Compile the Code adapter payload into the shared projection ABI."""
    payload = build_payload(
        root,
        mapper_generation=mapper_generation,
        commit=commit,
        config_fingerprint=config_fingerprint,
        changed_paths=changed_paths,
        mode=mode,
        limits=limits,
        previous_payload=previous_payload,
        rust_features=rust_features,
    )
    generation = payload.get("mapper_generation") or (
        f"bootstrap:{payload['payload_sha256']}"
    )
    return ProjectionEnvelope.create(
        "code",
        producer="simplicio-fast.parser-adapter",
        producer_schema=SCHEMA,
        generation=str(generation),
        stable_handle=f"code:{payload['payload_sha256']}",
        payload=payload,
    )


def validate_payload(
    value: Mapping[str, Any],
    *,
    root: Path | None = None,
    skip_file_paths: Iterable[str] = (),
) -> dict[str, Any]:
    """Validate schema, bounds, paths, stable IDs and canonical payload digest."""

    if not isinstance(value, Mapping):
        raise ParserAdapterError("payload_shape_invalid")
    if value.get("schema") != SCHEMA:
        raise ParserAdapterError("schema_unsupported")
    if value.get("mode") not in SUPPORTED_MODES:
        raise ParserAdapterError("mode_invalid")
    if value.get("producer") != "simplicio-fast-python-adapter":
        raise ParserAdapterError("producer_invalid")
    if value.get("adapter_version") != "1":
        raise ParserAdapterError("adapter_version_unsupported")
    mode = value.get("mode")
    commit = value.get("commit")
    mapper_generation = value.get("mapper_generation")
    if mode == "integrated":
        if (
            not isinstance(commit, str)
            or len(commit) != 40
            or any(character not in "0123456789abcdef" for character in commit)
            or not isinstance(mapper_generation, str)
            or not mapper_generation.strip()
        ):
            raise ParserAdapterError("mapper_identity_invalid")
    elif commit is not None and (
        not isinstance(commit, str)
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise ParserAdapterError("commit_invalid")
    changed_paths = value.get("changed_paths")
    if not isinstance(changed_paths, list):
        raise ParserAdapterError("changed_paths_invalid")
    for path in changed_paths:
        if not isinstance(path, str):
            raise ParserAdapterError("changed_path_invalid")
        _safe_relative(path)
    completeness = value.get("completeness")
    if completeness not in {"complete", "partial"}:
        raise ParserAdapterError("completeness_invalid")
    diagnostics = value.get("diagnostics")
    if not isinstance(diagnostics, list):
        raise ParserAdapterError("diagnostics_invalid")
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, Mapping):
            raise ParserAdapterError("diagnostics_invalid")
        if any(
            not isinstance(diagnostic.get(field), str) or not diagnostic[field]
            for field in ("path", "code", "detail")
        ):
            raise ParserAdapterError("diagnostics_invalid")
        fallback = diagnostic.get("fallback")
        if fallback is not None and not isinstance(fallback, str):
            raise ParserAdapterError("diagnostics_invalid")
    invalidation = value.get("invalidation")
    if not isinstance(invalidation, Mapping):
        raise ParserAdapterError("invalidation_invalid")
    if invalidation.get("schema") != "simplicio.fast.parser-invalidation/v1":
        raise ParserAdapterError("invalidation_invalid")
    for field in ("requested_paths", "parsed_paths", "reused_paths", "deleted_paths"):
        values = invalidation.get(field)
        if not isinstance(values, list) or any(
            not isinstance(path, str) for path in values
        ):
            raise ParserAdapterError("invalidation_invalid")
        for path in values:
            _safe_relative(path)
    reason_codes = invalidation.get("reason_codes")
    if not isinstance(reason_codes, list) or any(
        not isinstance(reason, str) or not reason for reason in reason_codes
    ):
        raise ParserAdapterError("invalidation_invalid")
    workspace_fingerprints = value.get("workspace_fingerprints")
    if not isinstance(workspace_fingerprints, Mapping):
        raise ParserAdapterError("workspace_fingerprints_invalid")
    for language, fingerprint in workspace_fingerprints.items():
        if (
            language not in {"csharp", "rust", "typescript"}
            or not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise ParserAdapterError("workspace_fingerprint_invalid")
    files = value.get("files")
    symbols = value.get("symbols")
    relations = value.get("relations")
    if (
        not isinstance(files, list)
        or not isinstance(symbols, list)
        or not isinstance(relations, list)
    ):
        raise ParserAdapterError("payload_shape_invalid")
    limits = _adapter_limits(None)
    if len(files) > limits["max_files"]:
        raise ParserAdapterError("file_limit_exceeded")
    if len(symbols) > limits["max_symbols"]:
        raise ParserAdapterError("symbol_limit_exceeded")
    if len(relations) > limits["max_relations"]:
        raise ParserAdapterError("relation_limit_exceeded")
    file_paths = set()
    skipped_paths = {_safe_relative(path) for path in skip_file_paths}
    for item in files:
        if not isinstance(item, Mapping):
            raise ParserAdapterError("file_invalid")
        path = item.get("path")
        if not isinstance(path, str):
            raise ParserAdapterError("file_invalid")
        normalized_path = _safe_relative(path)
        if item.get("language") not in set(SUPPORTED_EXTENSIONS.values()):
            raise ParserAdapterError("file_language_invalid")
        if item.get("encoding") != "utf-8":
            raise ParserAdapterError("file_encoding_invalid")
        file_paths.add(normalized_path)
        if (
            not isinstance(item.get("sha256"), str)
            or len(item["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in item["sha256"])
        ):
            raise ParserAdapterError("file_digest_invalid")
        if item.get("id") is not None and not isinstance(item["id"], str):
            raise ParserAdapterError("file_invalid")
        if root is not None and normalized_path not in skipped_paths:
            source_root = root.resolve()
            source = (source_root / normalized_path).resolve()
            if not source.is_relative_to(source_root) or not source.is_file():
                raise ParserAdapterError("source_missing", normalized_path)
            source_bytes = source.read_bytes()
            try:
                source_text = source.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise ParserAdapterError("file_encoding_invalid", normalized_path) from error
            source_digests = {
                hashlib.sha256(source_bytes).hexdigest(),
                hashlib.sha256(
                    source_text.replace("\r\n", "\n").encode("utf-8")
                ).hexdigest(),
            }
            if item["sha256"] not in source_digests:
                raise ParserAdapterError("source_digest_mismatch", normalized_path)
    ids: set[str] = set()
    for item in symbols:
        line_value = item.get("line") if isinstance(item, Mapping) else None
        end_line_value = item.get("end_line") if isinstance(item, Mapping) else None
        if (
            not isinstance(item, Mapping)
            or not isinstance(item.get("id"), str)
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("qualified_name"), str)
            or not isinstance(item.get("kind"), str)
            or not isinstance(item.get("language"), str)
            or not isinstance(line_value, int)
            or isinstance(line_value, bool)
            or not isinstance(end_line_value, int)
            or isinstance(end_line_value, bool)
            or line_value < 1
            or end_line_value < line_value
        ):
            raise ParserAdapterError("symbol_invalid")
        if item["id"] in ids:
            raise ParserAdapterError("symbol_id_collision")
        ids.add(item["id"])
        if item.get("file") not in file_paths or item.get("language") not in set(
            SUPPORTED_EXTENSIONS.values()
        ):
            raise ParserAdapterError("symbol_file_missing")
    for item in relations:
        confidence_value = item.get("confidence") if isinstance(item, Mapping) else None
        if (
            not isinstance(item, Mapping)
            or item.get("file") not in file_paths
            or not isinstance(item.get("origin"), str)
            or not isinstance(item.get("destination"), str)
            or not isinstance(item.get("origin_id"), str)
            or not isinstance(item.get("destination_id"), str)
            or not isinstance(confidence_value, (int, float))
            or isinstance(confidence_value, bool)
            or not 0 <= confidence_value <= 1
        ):
            raise ParserAdapterError("relation_file_missing")
        if item.get("kind") not in {
            "import",
            "reference",
            "call",
            "definition",
            "test",
        }:
            raise ParserAdapterError("relation_kind_invalid")
    supplied = value.get("payload_sha256")
    unsigned = dict(value)
    unsigned.pop("payload_sha256", None)
    if not isinstance(supplied, str) or supplied != _digest(unsigned):
        raise ParserAdapterError("payload_digest_mismatch")
    if len(_canonical(value)) > limits["max_payload_bytes"]:
        raise ParserAdapterError("payload_limit_exceeded")
    return {
        "schema": SCHEMA,
        "status": "valid",
        "files": len(files),
        "symbols": len(symbols),
        "relations": len(relations),
        "completeness": value.get("completeness"),
    }


__all__ = [
    "DEFAULT_LIMITS",
    "SCHEMA",
    "ParserAdapterError",
    "build_payload",
    "build_payload_from_mapper",
    "build_projection",
    "validate_payload",
]
