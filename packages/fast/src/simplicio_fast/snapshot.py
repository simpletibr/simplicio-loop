"""Versioned, bounded and memory-mapped Mapper projections.

SFAST001/v1 remains readable for migration.  New snapshots use v2: a little-endian
section directory, checksums for every section, direct lookup indexes and typed
relationships.  Integrated binary files carry the canonical Mapper identity;
the source parser is an explicit development-only bootstrap path.  The binary
file is always a disposable cache; source files and Mapper artifacts remain
authoritative.
"""

from __future__ import annotations

import ast
import tokenize
import hashlib
import json
import mmap
import os
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

MAGIC = b"SFAST001"
LEGACY_VERSION = 1
VERSION = 2
ENDIAN_MARKER = 0x0102
# The agent repository's canonical v2 snapshot is about 406 MiB. Keep a hard
# bound while allowing that supported Windows checkout to publish atomically.
MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024
MAX_FILES = 1_000_000
MAX_SYMBOLS = 5_000_000
MAX_RELATIONS = 10_000_000
MAX_SECTIONS = 32
ATOMIC_PUBLISH_ATTEMPTS = 4
ATOMIC_PUBLISH_DELAY_SECONDS = 0.01

SNAPSHOT_PROVENANCE_SCHEMA = "simplicio.fast.snapshot-provenance/v1"
MAPPER_HANDOFF_SCHEMA = "simplicio.mapper-fast-handoff/v1"


def _atomic_publish(temporary: Path, destination: Path) -> None:
    for attempt in range(ATOMIC_PUBLISH_ATTEMPTS):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if attempt + 1 >= ATOMIC_PUBLISH_ATTEMPTS:
                raise
            time.sleep(ATOMIC_PUBLISH_DELAY_SECONDS * (attempt + 1))


DEFAULT_MAX_SOURCE_FILE_BYTES = 80 * 1024 * 1024  # 83_886_080; override with --max-file-bytes
DEFAULT_BUILD_TIMEOUT_SECONDS = 180.0
VALIDATION_CACHE_SCHEMA = "simplicio.fast.validation-cache/v1"
# A metadata-only hit immediately after publication is unsafe on filesystems
# whose mtime/ctime clock is coarse or frozen for a short interval. During this
# window, verify the digest with a streaming read before reusing parsed data.
# Older cache entries retain the fast metadata-only path.
VALIDATION_CACHE_TIMESTAMP_GUARD_NS = 2_100_000_000
# v1 is deliberately frozen.  Do not change these structs: old snapshots must
# remain readable after a v2 writer is installed.
LEGACY_HEADER = struct.Struct("<8s7I")
LEGACY_FILE_RECORD = struct.Struct("<4I32s")
LEGACY_SYMBOL_RECORD = struct.Struct("<6I")

# v2 header: magic, version, endian marker, section count, generation,
# directory offset/size, total size and a whole-file checksum (with this field
# zeroed while calculating it).
HEADER = struct.Struct("<8sHHIQQQQ32s")
SECTION_RECORD = struct.Struct("<16sQQ32s")
FILE_RECORD = struct.Struct("<IIQ32s16s")
SYMBOL_RECORD = struct.Struct("<IIIIIIIIII32s")
REQUIRED_SECTIONS = ("files", "symbols", "relations", "indexes", "strings")
KIND_TO_ID = {
    "class": 1,
    "function": 2,
    "async_function": 3,
    "import": 4,
    "namespace": 5,
    "interface": 6,
    "struct": 7,
    "trait": 8,
    "enum": 9,
    "test": 10,
    "property": 11,
    "attribute": 12,
    # Mapper/TS/Python emitters may use these kinds; keep snapshot build fail-open.
    "type": 13,
    "variable": 14,
    "constant": 15,
    "module": 16,
    "method": 17,
    "field": 18,
    "unknown": 19,
}
ID_TO_KIND = {value: key for key, value in KIND_TO_ID.items()}


def kind_to_id(kind: str) -> int:
    """Map symbol kind to binary id; unknown kinds collapse to function (2)."""
    if not kind:
        return KIND_TO_ID["function"]
    key = str(kind).strip().casefold()
    if key in KIND_TO_ID:
        return KIND_TO_ID[key]
    # aliases
    aliases = {
        "fn": "function",
        "func": "function",
        "def": "function",
        "cls": "class",
        "typedef": "type",
        "typealias": "type",
        "const": "constant",
        "var": "variable",
    }
    mapped = aliases.get(key)
    if mapped and mapped in KIND_TO_ID:
        return KIND_TO_ID[mapped]
    return KIND_TO_ID["function"]
RELATION_KINDS = {"import", "reference", "call", "definition", "test"}


def _bootstrap_provenance(repository_id: str) -> dict[str, Any]:
    """Describe the explicit development-only source parser path."""

    return {
        "schema": SNAPSHOT_PROVENANCE_SCHEMA,
        "mode": "bootstrap",
        "authority": "simplicio-fast-bootstrap",
        "mapper_schema": None,
        "mapper_version": None,
        "repository_id": repository_id,
        "mapper_generation": None,
        "artifact_digest": None,
        "fast_format_version": VERSION,
        "capability_coverage": {
            "context_graph": False,
            "files": True,
            "symbols": True,
            "relations": True,
            "source_hashes": True,
            "stable_handles": False,
        },
    }


def _validate_snapshot_provenance(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("snapshot provenance is missing")
    required = (
        "schema",
        "mode",
        "authority",
        "mapper_schema",
        "mapper_version",
        "repository_id",
        "mapper_generation",
        "artifact_digest",
        "fast_format_version",
        "capability_coverage",
    )
    if any(key not in value for key in required):
        raise ValueError("snapshot provenance is incomplete")
    if value["schema"] != SNAPSHOT_PROVENANCE_SCHEMA:
        raise ValueError("snapshot provenance schema mismatch")
    mode = value["mode"]
    if mode not in {"bootstrap", "integrated", "legacy"}:
        raise ValueError("snapshot provenance mode is unsupported")
    if not isinstance(value["repository_id"], str) or not value["repository_id"].strip():
        raise ValueError("snapshot provenance repository is invalid")
    if value["fast_format_version"] != VERSION:
        raise ValueError("snapshot provenance format mismatch")
    if not isinstance(value["capability_coverage"], Mapping):
        raise ValueError("snapshot capability coverage is invalid")
    if mode == "integrated":
        if value["authority"] != "simplicio-mapper":
            raise ValueError("snapshot Mapper authority is invalid")
        if value["mapper_schema"] != MAPPER_HANDOFF_SCHEMA:
            raise ValueError("snapshot Mapper schema is invalid")
        if not isinstance(value["mapper_version"], str) or not value["mapper_version"].strip():
            raise ValueError("snapshot Mapper version is invalid")
        if not isinstance(value["mapper_generation"], str) or not value["mapper_generation"].strip():
            raise ValueError("snapshot Mapper generation is invalid")
        digest = value["artifact_digest"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("snapshot Mapper artifact digest is invalid")
    elif mode == "bootstrap":
        if value["authority"] != "simplicio-fast-bootstrap":
            raise ValueError("snapshot bootstrap authority is invalid")
        if value["mapper_schema"] is not None or value["mapper_generation"] is not None:
            raise ValueError("bootstrap snapshot contains Mapper identity")
        if value["artifact_digest"] is not None:
            raise ValueError("bootstrap snapshot contains Mapper artifact digest")
    return dict(value)


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    qualified_name: str
    kind: str
    file: str
    line: int
    end_line: int
    symbol_id: str = ""
    signature: str = ""
    base_generation: str | None = None
    overlay_generation: str | None = None


@dataclass(frozen=True, slots=True)
class Relation:
    origin: str
    destination: str
    kind: str
    confidence: float
    origin_id: str = ""
    destination_id: str = ""


@dataclass(frozen=True, slots=True)
class BuildMetrics:
    files: int
    symbols: int
    parsed_files: int
    reused_files: int
    snapshot_bytes: int
    wall_ms: float
    cpu_ms: float
    format_version: int = VERSION
    generation: str = ""
    relations: int = 0
    parsed_paths: tuple[str, ...] = ()
    reused_paths: tuple[str, ...] = ()
    changed_paths: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    metadata_reused_files: int = 0
    phase_timings_ms: dict[str, float] | None = None


@dataclass(frozen=True, slots=True)
class ContextSpan:
    symbol: str
    kind: str
    file: str
    start_line: int
    end_line: int
    source_sha256: str
    content: str
    symbol_id: str = ""
    tokens: int = 0
    base_generation: str | None = None
    overlay_generation: str | None = None
    # The semantic symbol range is retained separately from the bounded view.
    # Existing start_line/end_line fields describe the delivered content.
    requested_start_line: int | None = None
    requested_end_line: int | None = None
    start_byte: int = 0
    end_byte: int = 0
    content_sha256: str = ""
    fidelity: str = "complete"
    omitted_ranges: tuple[tuple[int, int], ...] = ()
    needs_broader_context: bool = False


class StaleSnapshotError(RuntimeError):
    pass


class SnapshotProvenanceError(ValueError):
    """Raised when a source-parser build would replace a canonical projection."""

    code = "snapshot_provenance_invalid"


def stable_id(
    repository: str, file: str, language: str, symbol: str, signature: str
) -> str:
    """Return the stable 256-bit ID required by the public format contract."""

    value = "\0".join((repository, file, language, symbol, signature))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _repository_id(root: Path) -> str:
    """Use a stable repository marker without making git a runtime dependency."""

    git_marker = root / ".git"
    try:
        if git_marker.is_dir():
            config = git_marker / "config"
        elif git_marker.is_file():
            pointer = git_marker.read_text(encoding="utf-8").strip()
            gitdir = pointer.removeprefix("gitdir:").strip()
            config = Path(gitdir).resolve().parents[1] / "config"
        else:
            config = Path()
        marker = ""
        if config.is_file():
            for line in config.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("url = "):
                    marker = line.split("=", 1)[1].strip()
                    break
    except OSError:
        marker = ""
    return marker or root.name


class _Collector(ast.NodeVisitor):
    def __init__(self, file: str, repository: str) -> None:
        self.file = file
        self.repository = repository
        self.scope: list[str] = []
        self.symbols: list[Symbol] = []
        self.relations: list[Relation] = []
        self._current: list[Symbol] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scope(node, "class")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scope(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scope(node, "async_function")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.relations.append(Relation(self.file, alias.name, "import", 1.0))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            target = f"{module}.{alias.name}" if module else alias.name
            self.relations.append(Relation(self.file, target, "import", 1.0))

    def visit_Call(self, node: ast.Call) -> None:
        if self._current:
            target = _ast_name(node.func)
            if target:
                self.relations.append(
                    Relation(
                        self._current[-1].qualified_name,
                        target,
                        "call",
                        0.8,
                        self._current[-1].symbol_id,
                    )
                )
                if self._current[-1].name.casefold().startswith("test"):
                    self.relations.append(
                        Relation(
                            self._current[-1].qualified_name,
                            target,
                            "test",
                            0.9,
                            self._current[-1].symbol_id,
                        )
                    )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if (
            self._current
            and isinstance(node.ctx, ast.Load)
            and node.id not in {"True", "False", "None"}
        ):
            self.relations.append(
                Relation(
                    self._current[-1].qualified_name,
                    node.id,
                    "reference",
                    0.5,
                    self._current[-1].symbol_id,
                )
            )

    def _visit_scope(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        kind: str,
    ) -> None:
        qualified = ".".join([*self.scope, node.name])
        signature = _signature(node)
        symbol = Symbol(
            node.name,
            qualified,
            kind,
            self.file,
            node.lineno,
            node.end_lineno or node.lineno,
            stable_id(self.repository, self.file, "python", qualified, signature),
            signature,
        )
        self.symbols.append(symbol)
        self.relations.append(
            Relation(self.file, qualified, "definition", 1.0, "", symbol.symbol_id)
        )
        self.scope.append(node.name)
        self._current.append(symbol)
        self.generic_visit(node)
        self._current.pop()
        self.scope.pop()


def _ast_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _ast_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _signature(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    if isinstance(node, ast.ClassDef):
        return ""
    try:
        return ast.unparse(node.args)
    except (AttributeError, ValueError):
        return ""


class SnapshotBuildTimeout(TimeoutError):
    """Raised when a bounded build cannot complete before its deadline."""

    code = "snapshot_build_timeout"
    recovery = (
        "retry with a larger timeout or exclude generated/vendor source directories"
    )

    def __init__(
        self,
        *,
        timeout_seconds: float,
        files_total: int,
        files_processed: int,
        parsed_files: int,
        reused_files: int,
        elapsed_ms: float,
        previous_snapshot_preserved: bool,
        metadata_reused_files: int = 0,
        phase_timings_ms: dict[str, float] | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.progress = {
            "files_total": files_total,
            "files_processed": files_processed,
            "files_remaining": max(0, files_total - files_processed),
            "parsed_files": parsed_files,
            "reused_files": reused_files,
            "elapsed_ms": round(elapsed_ms, 3),
            "previous_snapshot_preserved": previous_snapshot_preserved,
            "metadata_reused_files": metadata_reused_files,
            "phase_timings_ms": phase_timings_ms or {},
        }
        super().__init__(
            f"snapshot build exceeded {timeout_seconds:g}s before publishing; "
            f"progress={json.dumps(self.progress, sort_keys=True, separators=(',', ':'))}; "
            "the previous snapshot was preserved"
        )


class SnapshotTooLarge(ValueError):
    """Raised before allocating or publishing a snapshot over the hard bound."""

    code = "snapshot_too_large"

    def __init__(self, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        self.recovery = (
            "exclude generated/vendor source or use a partitioned repository snapshot"
        )
        super().__init__(
            f"{self.code} size={size} limit={limit} recovery={self.recovery}"
        )


class SourceFileTooLarge(ValueError):
    """Raised before parsing a source file that exceeds the safety bound."""

    code = "source_file_too_large"

    def __init__(self, path: Path, size: int, limit: int) -> None:
        self.path = path.as_posix()
        self.size = size
        self.limit = limit
        self.recovery = (
            "exclude generated/vendor source or raise --max-file-bytes explicitly"
        )
        super().__init__(
            f"{self.code} path={self.path} size={size} limit={limit} recovery={self.recovery}"
        )


class SourceEncodingError(ValueError):
    code = "source_encoding_unreadable"

    def __init__(self, path: Path, cause: BaseException) -> None:
        self.path = path.as_posix()
        self.recovery = (
            "add a PEP 263 encoding cookie or remove the binary-looking source file"
        )
        super().__init__(
            f"{self.code} path={self.path} recovery={self.recovery} cause={type(cause).__name__}"
        )


class SourceParseError(ValueError):
    """A source file is readable but is not valid Python syntax."""

    code = "source_parse_failed"

    def __init__(self, path: Path, cause: SyntaxError) -> None:
        self.path = path.as_posix()
        self.line = cause.lineno
        self.column = cause.offset
        self.reason = cause.msg or "invalid Python syntax"
        self.recovery = (
            "fix the source syntax or exclude the malformed file before rebuilding"
        )
        location = ""
        if self.line is not None:
            location = f" line={self.line}"
            if self.column is not None:
                location += f" column={self.column}"
        super().__init__(
            f"{self.code} path={self.path}{location} reason={self.reason} "
            f"recovery={self.recovery}"
        )


def _read_python_source(path: Path) -> str:
    try:
        with tokenize.open(path) as source:
            return source.read()
    except (SyntaxError, UnicodeDecodeError) as error:
        raise SourceEncodingError(path, error) from error


def _parse_file(
    path: Path, relative_path: str, repository: str
) -> tuple[list[Symbol], list[Relation]]:
    if path.suffix.casefold() not in {".py", ".pyi"}:
        from .adapters import parse_path

        return parse_path(path, relative_path), []
    try:
        tree = ast.parse(_read_python_source(path), filename=relative_path)
    except SyntaxError as error:
        raise SourceParseError(Path(relative_path), error) from error
    collector = _Collector(relative_path, repository)
    collector.visit(tree)
    return collector.symbols, collector.relations


def parse_symbols(path: Path, relative_path: str) -> list[Symbol]:
    """Parse symbols using the legacy public helper signature."""

    return _parse_file(path, relative_path, path.parent.name)[0]


def source_files(root: Path) -> list[Path]:
    ignored = {
        ".git",
        ".venv",
        "__pycache__",
        ".simplicio-fast",
        ".simplicio",
        "node_modules",
    }
    suffixes = {".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".rs", ".cs"}
    found: list[Path] = []
    for directory, directories, filenames in os.walk(
        root, topdown=True, followlinks=False
    ):
        directories[:] = sorted(name for name in directories if name not in ignored)
        found.extend(
            Path(directory) / name
            for name in sorted(filenames)
            if Path(name).suffix.casefold() in suffixes
        )
    return sorted(found)


def _add_string(strings: bytearray, value: str) -> tuple[int, int]:
    encoded = value.encode("utf-8")
    offset = len(strings)
    strings.extend(encoded)
    return offset, len(encoded)


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _build_v2(
    entries: list[tuple[str, bytes, int, list[Symbol]]],
    relations: list[Relation],
    output: Path,
    *,
    provenance: Mapping[str, Any] | None = None,
) -> tuple[int, str]:
    strings = bytearray()
    file_rows: list[bytes] = []
    file_index: dict[str, int] = {}
    for index, (path, digest, size, _) in enumerate(entries):
        file_index[path] = index
        offset, length = _add_string(strings, path)
        file_id = hashlib.sha256(path.encode("utf-8")).digest()[:16]
        file_rows.append(FILE_RECORD.pack(offset, length, size, digest, file_id))

    symbols = sorted(
        (symbol for _, _, _, found in entries for symbol in found),
        key=lambda item: (
            item.name.casefold(),
            item.qualified_name,
            item.file,
            item.line,
        ),
    )
    symbol_rows: list[bytes] = []
    for symbol in symbols:
        name_offset, name_length = _add_string(strings, symbol.name)
        qualified_offset, qualified_length = _add_string(strings, symbol.qualified_name)
        signature_offset, signature_length = _add_string(strings, symbol.signature)
        symbol_rows.append(
            SYMBOL_RECORD.pack(
                name_offset,
                name_length,
                qualified_offset,
                qualified_length,
                signature_offset,
                signature_length,
                file_index[symbol.file],
                symbol.line,
                symbol.end_line,
                kind_to_id(symbol.kind),
                bytes.fromhex(symbol.symbol_id),
            )
        )

    names: dict[str, list[int]] = {}
    paths: dict[str, list[int]] = {}
    kinds: dict[str, list[int]] = {}
    exact: dict[str, list[int]] = {}
    for index, symbol in enumerate(symbols):
        names.setdefault(symbol.name.casefold(), []).append(index)
        exact.setdefault(symbol.qualified_name.casefold(), []).append(index)
        paths.setdefault(symbol.file, []).append(index)
        kinds.setdefault(symbol.kind, []).append(index)
    indexes = {
        "exact": exact,
        "names": names,
        "paths": paths,
        "kinds": kinds,
        "provenance": _validate_snapshot_provenance(
            provenance or _bootstrap_provenance("unknown")
        ),
    }
    relation_payload = [
        {
            "origin": relation.origin,
            "destination": relation.destination,
            "kind": relation.kind,
            "confidence": relation.confidence,
            "origin_id": relation.origin_id,
            "destination_id": relation.destination_id,
        }
        for relation in sorted(
            relations,
            key=lambda item: (
                item.kind,
                item.origin,
                item.destination,
                item.confidence,
            ),
        )
    ]
    sections_data = {
        "files": b"".join(file_rows),
        "symbols": b"".join(symbol_rows),
        "relations": _json_bytes(relation_payload),
        "indexes": _json_bytes(indexes),
        "strings": bytes(strings),
    }
    section_count = len(REQUIRED_SECTIONS)
    directory_offset = HEADER.size
    directory_size = SECTION_RECORD.size * section_count
    offset = directory_offset + directory_size
    section_rows: list[bytes] = []
    section_offsets: list[tuple[str, int, bytes]] = []
    for name in REQUIRED_SECTIONS:
        data = sections_data[name]
        if offset % 8:
            offset += 8 - offset % 8
        digest = hashlib.sha256(data).digest()
        section_offsets.append((name, offset, data))
        section_rows.append(
            SECTION_RECORD.pack(name.encode("ascii"), offset, len(data), digest)
        )
        offset += len(data)
    total_size = offset
    if total_size > MAX_SNAPSHOT_BYTES:
        raise SnapshotTooLarge(total_size, MAX_SNAPSHOT_BYTES)
    source_digest = hashlib.sha256(
        b"".join(digest for _, digest, _, _ in entries)
    ).digest()
    generation_int = int.from_bytes(source_digest[:8], "little")
    header = HEADER.pack(
        MAGIC,
        VERSION,
        ENDIAN_MARKER,
        section_count,
        generation_int,
        directory_offset,
        directory_size,
        total_size,
        b"\0" * 32,
    )
    payload = bytearray(total_size)
    payload[: HEADER.size] = header
    payload[directory_offset : directory_offset + directory_size] = b"".join(
        section_rows
    )
    for _, section_offset, data in section_offsets:
        payload[section_offset : section_offset + len(data)] = data
    checksum = hashlib.sha256(payload).digest()
    payload[: HEADER.size] = HEADER.pack(
        MAGIC,
        VERSION,
        ENDIAN_MARKER,
        section_count,
        generation_int,
        directory_offset,
        directory_size,
        total_size,
        checksum,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output.parent,
            prefix=f".{output.name}.{os.getpid()}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path = Path(temporary_name)
        # Validate the exact bytes before publishing. The old snapshot remains
        # available until this succeeds and os.replace performs one atomic swap.
        with Snapshot(temporary_path):
            pass
        _atomic_publish(temporary_path, output)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return total_size, checksum.hex()


def _validation_cache_path(output: Path) -> Path:
    return output.with_name(f"{output.name}.validation.json")


def _file_identity(stat: os.stat_result) -> dict[str, int]:
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
    }


def _streaming_sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def _load_validation_cache(
    output: Path,
    *,
    snapshot_checksum: str,
    expected_paths: set[str],
) -> dict[str, dict[str, int | str]]:
    path = _validation_cache_path(output)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        files = payload["files"]
        if (
            payload.get("schema") != VALIDATION_CACHE_SCHEMA
            or payload.get("snapshot_checksum") != snapshot_checksum
            or not isinstance(files, dict)
            or set(files) != expected_paths
        ):
            return {}
        for relative, row in files.items():
            if (
                not isinstance(relative, str)
                or not isinstance(row, dict)
                or not isinstance(row.get("size"), int)
                or not isinstance(row.get("mtime_ns"), int)
                or not isinstance(row.get("ctime_ns"), int)
                or not isinstance(row.get("sha256"), str)
                or len(row["sha256"]) != 64
            ):
                return {}
        return files
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def _write_validation_cache(
    output: Path,
    *,
    snapshot_checksum: str,
    files: dict[str, dict[str, int | str]],
) -> None:
    path = _validation_cache_path(output)
    payload = (
        json.dumps(
            {
                "schema": VALIDATION_CACHE_SCHEMA,
                "snapshot_checksum": snapshot_checksum,
                "files": files,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.{os.getpid()}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def build_snapshot(
    root: Path,
    output: Path,
    *,
    timeout_seconds: float | None = None,
    max_file_bytes: int = DEFAULT_MAX_SOURCE_FILE_BYTES,
) -> BuildMetrics:
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    phase_timings = {
        "previous_snapshot_load": 0.0,
        "discovery": 0.0,
        "unchanged_validation": 0.0,
        "parsing": 0.0,
        "publication": 0.0,
    }

    if max_file_bytes < 1:
        raise ValueError("max_file_bytes must be positive")
    root = root.resolve()
    if os.path.isfile(root / ".simplicio" / "fast-handoff.json"):
        raise SnapshotProvenanceError(
            "canonical Mapper handoff is present; compile a Mapper projection instead"
        )
    repository = _repository_id(root)
    previous: dict[str, tuple[bytes, list[Symbol]]] = {}
    previous_relations: list[Relation] = []
    previous_symbol_files: dict[str, str] = {}
    previous_checksum = ""
    previous_valid = False
    previous_format_version = 0
    previous_provenance: dict[str, Any] | None = None
    previous_start = time.perf_counter()
    if output.exists():
        try:
            with Snapshot(output) as snapshot:
                previous = snapshot.grouped()
                previous_relations = snapshot.relations()
                previous_format_version = snapshot.format_version
                previous_symbol_files = {
                    symbol.qualified_name: symbol.file for symbol in snapshot.symbols()
                }
                previous_checksum = snapshot.content_checksum
                previous_provenance = snapshot.provenance
                previous_valid = True
        except (OSError, ValueError):
            previous = {}
            previous_relations = []
            previous_symbol_files = {}
            previous_provenance = None
    if previous_valid and previous_provenance is not None:
        if previous_provenance.get("mode") == "integrated":
            raise SnapshotProvenanceError(
                "canonical Mapper projection requires Mapper input; refusing source-parser rebuild"
            )
    phase_timings["previous_snapshot_load"] = (
        time.perf_counter() - previous_start
    ) * 1000

    discovery_start = time.perf_counter()
    paths = source_files(root)
    relatives = [path.relative_to(root).as_posix() for path in paths]
    phase_timings["discovery"] = (time.perf_counter() - discovery_start) * 1000
    validation_cache = (
        _load_validation_cache(
            output,
            snapshot_checksum=previous_checksum,
            expected_paths=set(relatives),
        )
        if previous_valid
        else {}
    )
    validation_cache_requires_digest = False
    if validation_cache:
        try:
            cache_age_ns = max(
                0,
                time.time_ns() - _validation_cache_path(output).stat().st_mtime_ns,
            )
            validation_cache_requires_digest = (
                cache_age_ns <= VALIDATION_CACHE_TIMESTAMP_GUARD_NS
            )
        except OSError:
            # The cache disappeared or cannot be inspected. Fail closed by
            # forcing normal content validation below.
            validation_cache_requires_digest = True

    entries: list[tuple[str, bytes, int, list[Symbol]]] = []
    relations: list[Relation] = []
    parsed_paths: list[str] = []
    reused_paths: list[str] = []
    metadata_reused_files = 0
    next_validation: dict[str, dict[str, int | str]] = {}
    deadline = None if timeout_seconds is None else wall_start + timeout_seconds

    def current_timings() -> dict[str, float]:
        return {name: round(value, 3) for name, value in phase_timings.items()}

    def raise_timeout() -> None:
        assert timeout_seconds is not None
        raise SnapshotBuildTimeout(
            timeout_seconds=timeout_seconds,
            files_total=len(paths),
            files_processed=len(entries),
            parsed_files=len(parsed_paths),
            reused_files=len(reused_paths),
            elapsed_ms=(time.perf_counter() - wall_start) * 1000,
            previous_snapshot_preserved=output.exists(),
            metadata_reused_files=metadata_reused_files,
            phase_timings_ms=current_timings(),
        )

    for path, relative in zip(paths, relatives, strict=True):
        if deadline is not None and time.perf_counter() >= deadline:
            raise_timeout()
        validation_start = time.perf_counter()
        try:
            stat = path.stat()
        except OSError as error:
            raise OSError(f"could not stat source file {path}: {error}") from error
        if stat.st_size > max_file_bytes:
            raise SourceFileTooLarge(path, stat.st_size, max_file_bytes)
        identity = _file_identity(stat)
        cached = previous.get(relative)
        row = validation_cache.get(relative)
        metadata_candidate = bool(
            cached
            and row
            and all(row.get(key) == value for key, value in identity.items())
            and row.get("sha256") == cached[0].hex()
        )
        probed_digest = (
            _streaming_sha256(path)
            if metadata_candidate and validation_cache_requires_digest
            else None
        )
        metadata_hit = metadata_candidate and (
            probed_digest is None or probed_digest == cached[0]
        )
        if metadata_hit:
            digest = cached[0]
            symbols = cached[1]
            reused_paths.append(relative)
            metadata_reused_files += 1
            phase_timings["unchanged_validation"] += (
                time.perf_counter() - validation_start
            ) * 1000
        else:
            if probed_digest is None:
                contents = path.read_bytes()
                digest = hashlib.sha256(contents).digest()
            else:
                digest = probed_digest
            phase_timings["unchanged_validation"] += (
                time.perf_counter() - validation_start
            ) * 1000
            if cached and cached[0] == digest:
                symbols = cached[1]
                reused_paths.append(relative)
            else:
                parse_start = time.perf_counter()
                symbols, found_relations = _parse_file(path, relative, repository)
                phase_timings["parsing"] += (time.perf_counter() - parse_start) * 1000
                relations.extend(found_relations)
                parsed_paths.append(relative)
        next_validation[relative] = {
            **identity,
            "sha256": digest.hex(),
        }
        entries.append((relative, digest, stat.st_size, symbols))
        if deadline is not None and time.perf_counter() >= deadline:
            raise_timeout()

    current_digests = {path: digest for path, digest, _, _ in entries}
    current_paths = set(current_digests)
    previous_paths = set(previous)
    added_paths = sorted(current_paths - previous_paths)
    deleted_paths = sorted(previous_paths - current_paths)
    modified_paths = sorted(
        path
        for path in current_paths & previous_paths
        if previous[path][0] != current_digests[path]
    )
    if previous_valid:
        changed_paths = tuple(sorted({*added_paths, *deleted_paths, *modified_paths}))
        reason_codes = tuple(
            [
                code
                for code, present in (
                    ("source_changed", bool(modified_paths)),
                    ("source_added", bool(added_paths)),
                    ("source_deleted", bool(deleted_paths)),
                )
                if present
            ]
            or ["no_change"]
        )
    elif output.exists():
        changed_paths = ()
        reason_codes = ("snapshot_invalidated",)
    else:
        changed_paths = ()
        reason_codes = ("cold_build",)

    if reused_paths and output.exists():
        invalidated_paths = set(changed_paths)
        relations = [
            relation
            for relation in previous_relations
            if relation.origin not in invalidated_paths
            and previous_symbol_files.get(relation.origin) not in invalidated_paths
        ] + relations
    if previous_valid and previous_format_version == VERSION and not changed_paths:
        # A validated unchanged source tree already has the exact published
        # bytes. Avoid reserializing and atomically replacing the full SFAST
        # file during warm/unchanged refreshes.
        return BuildMetrics(
            files=len(entries),
            symbols=sum(len(found) for _, _, _, found in entries),
            parsed_files=0,
            reused_files=len(reused_paths),
            snapshot_bytes=output.stat().st_size,
            wall_ms=(time.perf_counter() - wall_start) * 1000,
            cpu_ms=(time.process_time() - cpu_start) * 1000,
            format_version=previous_format_version,
            generation=previous_checksum,
            relations=len(previous_relations),
            parsed_paths=(),
            reused_paths=tuple(reused_paths),
            changed_paths=(),
            reason_codes=("no_change",),
            metadata_reused_files=metadata_reused_files,
            phase_timings_ms=current_timings(),
        )
    if deadline is not None and time.perf_counter() >= deadline:
        raise_timeout()
    publication_start = time.perf_counter()
    total_size, checksum = _build_v2(
        entries,
        relations,
        output,
        provenance=_bootstrap_provenance(repository),
    )
    try:
        _write_validation_cache(
            output,
            snapshot_checksum=checksum,
            files=next_validation,
        )
    except OSError:
        pass
    phase_timings["publication"] = (time.perf_counter() - publication_start) * 1000
    return BuildMetrics(
        files=len(entries),
        symbols=sum(len(found) for _, _, _, found in entries),
        parsed_files=len(parsed_paths),
        reused_files=len(reused_paths),
        snapshot_bytes=total_size,
        wall_ms=(time.perf_counter() - wall_start) * 1000,
        cpu_ms=(time.process_time() - cpu_start) * 1000,
        generation=checksum,
        relations=len(relations),
        parsed_paths=tuple(parsed_paths),
        reused_paths=tuple(reused_paths),
        changed_paths=changed_paths,
        reason_codes=reason_codes,
        metadata_reused_files=metadata_reused_files,
        phase_timings_ms=current_timings(),
    )


class Snapshot:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._sha256: str | None = None
        self._file = path.open("rb")
        try:
            size = os.fstat(self._file.fileno()).st_size
            if size < LEGACY_HEADER.size or size > MAX_SNAPSHOT_BYTES:
                raise ValueError("invalid snapshot size")
            self._map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
            magic = self._map[:8]
            if magic != MAGIC:
                raise ValueError("invalid or unsupported Simplicio Fast snapshot")
            version = struct.unpack_from("<H", self._map, 8)[0]
            if version == LEGACY_VERSION:
                self._open_legacy()
            elif version == VERSION:
                self._open_v2()
            else:
                raise ValueError(
                    f"unsupported Simplicio Fast snapshot version: {version}"
                )
        except Exception:
            self.close()
            raise

    def _open_legacy(self) -> None:
        if len(self._map) < LEGACY_HEADER.size:
            raise ValueError("truncated SFAST001/v1 header")
        (
            magic,
            version,
            self.file_count,
            self.symbol_count,
            self.files_offset,
            self.symbols_offset,
            self.strings_offset,
            total_size,
        ) = LEGACY_HEADER.unpack_from(self._map)
        if magic != MAGIC or version != LEGACY_VERSION or total_size != len(self._map):
            raise ValueError("invalid or unsupported SFAST001/v1 snapshot")
        self.format_version = LEGACY_VERSION
        self._header_generation = ""
        self.relation_count = 0
        self._sections = {}
        self._provenance = {
            "schema": SNAPSHOT_PROVENANCE_SCHEMA,
            "mode": "legacy",
            "authority": "unknown",
            "mapper_schema": None,
            "mapper_version": None,
            "repository_id": "unknown",
            "mapper_generation": None,
            "artifact_digest": None,
            "fast_format_version": LEGACY_VERSION,
            "capability_coverage": {},
        }
        if self.file_count > MAX_FILES or self.symbol_count > MAX_SYMBOLS:
            raise ValueError("snapshot record limit exceeded")
        _validate_region(
            self.files_offset,
            self.file_count * LEGACY_FILE_RECORD.size,
            self.strings_offset,
            LEGACY_HEADER.size,
        )
        _validate_region(
            self.symbols_offset,
            self.symbol_count * LEGACY_SYMBOL_RECORD.size,
            self.strings_offset,
            LEGACY_HEADER.size,
        )
        if (
            not self.files_offset
            <= self.symbols_offset
            <= self.strings_offset
            <= total_size
        ):
            raise ValueError("invalid v1 section offsets")
        for index in range(self.file_count):
            row = LEGACY_FILE_RECORD.unpack_from(
                self._map, self.files_offset + index * LEGACY_FILE_RECORD.size
            )
            _validate_text(row[0], row[1], total_size - self.strings_offset)
        for index in range(self.symbol_count):
            row = LEGACY_SYMBOL_RECORD.unpack_from(
                self._map, self.symbols_offset + index * LEGACY_SYMBOL_RECORD.size
            )
            _validate_text(row[0], row[1], total_size - self.strings_offset)
            if (
                row[2] >= self.file_count
                or row[3] < 1
                or row[4] < row[3]
                or row[5] not in ID_TO_KIND
            ):
                raise ValueError("invalid v1 symbol record")

    def _open_v2(self) -> None:
        if len(self._map) < HEADER.size:
            raise ValueError("truncated SFAST001/v2 header")
        (
            magic,
            version,
            endian,
            section_count,
            generation,
            directory_offset,
            directory_size,
            total_size,
            checksum,
        ) = HEADER.unpack_from(self._map)
        if (
            magic != MAGIC
            or version != VERSION
            or endian != ENDIAN_MARKER
            or total_size != len(self._map)
        ):
            raise ValueError("invalid or unsupported SFAST001/v2 header")
        if section_count < len(REQUIRED_SECTIONS) or section_count > MAX_SECTIONS:
            raise ValueError("invalid section count")
        _validate_region(directory_offset, directory_size, len(self._map), HEADER.size)
        if directory_size != section_count * SECTION_RECORD.size:
            raise ValueError("invalid section directory size")
        directory_end = directory_offset + directory_size
        check_payload = bytearray(self._map)
        check_payload[HEADER.size - 32 : HEADER.size] = b"\0" * 32
        if hashlib.sha256(check_payload).digest() != checksum:
            raise ValueError("snapshot checksum mismatch")
        sections: dict[str, tuple[int, int]] = {}
        regions: list[tuple[int, int]] = []
        for index in range(section_count):
            name_raw, offset, length, section_checksum = SECTION_RECORD.unpack_from(
                self._map, directory_offset + index * SECTION_RECORD.size
            )
            name = name_raw.rstrip(b"\0").decode("ascii", errors="strict")
            if not name or name in sections:
                raise ValueError("invalid or duplicate section name")
            _validate_region(offset, length, len(self._map), directory_end)
            if offset % 8:
                raise ValueError("unaligned section offset")
            if (
                hashlib.sha256(self._map[offset : offset + length]).digest()
                != section_checksum
            ):
                raise ValueError(f"section checksum mismatch: {name}")
            sections[name] = (offset, length)
            regions.append((offset, offset + length))
        if any(name not in sections for name in REQUIRED_SECTIONS):
            raise ValueError("snapshot is missing a required section")
        if any(
            a < b and c < d and max(a, c) < min(b, d)
            for i, (a, b) in enumerate(regions)
            for c, d in regions[i + 1 :]
        ):
            raise ValueError("overlapping snapshot sections")
        self.format_version = VERSION
        self._header_generation = f"{generation:016x}"
        self._content_checksum = checksum.hex()
        self._sections = sections
        if (
            sections["files"][1] % FILE_RECORD.size
            or sections["symbols"][1] % SYMBOL_RECORD.size
        ):
            raise ValueError("section length is not a whole number of records")
        self.file_count = sections["files"][1] // FILE_RECORD.size
        self.symbol_count = sections["symbols"][1] // SYMBOL_RECORD.size
        self.relation_count = 0
        if self.file_count > MAX_FILES or self.symbol_count > MAX_SYMBOLS:
            raise ValueError("snapshot record limit exceeded")
        try:
            index_data = json.loads(self._section_bytes("indexes"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid index or relation section") from error
        if not isinstance(index_data, dict):
            raise ValueError("invalid index payload")
        self._provenance = _validate_snapshot_provenance(index_data.get("provenance"))
        self._validate_v2_records()

    def _validate_v2_records(self) -> None:
        string_offset, string_length = self._sections["strings"]
        for index in range(self.file_count):
            row = FILE_RECORD.unpack_from(
                self._map, self._sections["files"][0] + index * FILE_RECORD.size
            )
            _validate_text(row[0], row[1], string_length)
        for index in range(self.symbol_count):
            row = SYMBOL_RECORD.unpack_from(
                self._map, self._sections["symbols"][0] + index * SYMBOL_RECORD.size
            )
            _validate_text(row[0], row[1], string_length)
            _validate_text(row[2], row[3], string_length)
            _validate_text(row[4], row[5], string_length)
            if (
                row[6] >= self.file_count
                or row[7] < 1
                or row[8] < row[7]
                or row[9] not in ID_TO_KIND
            ):
                raise ValueError("invalid symbol record")
        try:
            relation_data = json.loads(self._section_bytes("relations"))
            index_data = json.loads(self._section_bytes("indexes"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid index or relation section") from error
        if not isinstance(relation_data, list) or len(relation_data) > MAX_RELATIONS:
            raise ValueError("invalid relation count")
        for relation in relation_data:
            if (
                not isinstance(relation, dict)
                or relation.get("kind") not in RELATION_KINDS
            ):
                raise ValueError("invalid relation record")
            if (
                not isinstance(relation.get("confidence"), (int, float))
                or not 0 <= relation["confidence"] <= 1
            ):
                raise ValueError("invalid relation confidence")
        if not isinstance(index_data, dict):
            raise ValueError("invalid index payload")
        for key in ("exact", "names", "paths", "kinds"):
            if not isinstance(index_data.get(key), dict):
                raise ValueError("missing direct index")
            for values in index_data[key].values():
                if not isinstance(values, list) or any(
                    not isinstance(value, int)
                    or value < 0
                    or value >= self.symbol_count
                    for value in values
                ):
                    raise ValueError("direct index points outside symbol section")
        self.relation_count = len(relation_data)

    def close(self) -> None:
        if hasattr(self, "_map") and not self._map.closed:
            self._map.close()
        if not self._file.closed:
            self._file.close()

    def __enter__(self) -> "Snapshot":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def content_checksum(self) -> str:
        """Return the validated checksum stored in the v2 header."""
        if self.format_version != VERSION:
            return self.sha256
        return self._content_checksum

    @property
    def provenance(self) -> dict[str, Any]:
        """Return the immutable Mapper/source lineage stored in the snapshot."""

        return dict(self._provenance)

    def matches_mapper(self, mapper: Mapping[str, Any]) -> bool:
        """Return whether this projection is pinned to a supplied Mapper identity."""

        if self.provenance.get("mode") != "integrated":
            return False
        return all(
            self.provenance.get(snapshot_key) == mapper.get(mapper_key)
            for snapshot_key, mapper_key in (
                ("mapper_schema", "mapper_schema"),
                ("mapper_version", "mapper_version"),
                ("repository_id", "repository_id"),
                ("mapper_generation", "generation"),
                ("artifact_digest", "artifact_digest"),
            )
        )

    def require_mapper(self, mapper: Mapping[str, Any]) -> None:
        """Fail closed when a caller tries to use a stale Mapper projection."""

        if not self.matches_mapper(mapper):
            raise StaleSnapshotError(
                "snapshot Mapper provenance differs from the requested canonical generation"
            )

    @property
    def sha256(self) -> str:
        """Return the digest of the exact snapshot bytes opened by mmap."""
        if self._sha256 is not None:
            return self._sha256
        digest = hashlib.sha256()
        for offset in range(0, len(self._map), 1024 * 1024):
            digest.update(self._map[offset : offset + 1024 * 1024])
        self._sha256 = digest.hexdigest()
        return self._sha256

    @property
    def generation(self) -> str:
        """Return a stable generation handle derived only from snapshot bytes."""
        return f"{MAGIC.decode('ascii')}:{self.sha256}"

    def _section_bytes(self, name: str) -> bytes:
        offset, length = self._sections[name]
        return self._map[offset : offset + length]

    def _text(self, offset: int, length: int) -> str:
        if self.format_version == LEGACY_VERSION:
            _validate_text(offset, length, len(self._map) - self.strings_offset)
            start = self.strings_offset + offset
        else:
            start = self._sections["strings"][0] + offset
            _validate_text(offset, length, self._sections["strings"][1])
        return self._map[start : start + length].decode("utf-8")

    def files(self) -> list[tuple[str, bytes]]:
        result: list[tuple[str, bytes]] = []
        for index in range(self.file_count):
            if self.format_version == LEGACY_VERSION:
                row = LEGACY_FILE_RECORD.unpack_from(
                    self._map, self.files_offset + index * LEGACY_FILE_RECORD.size
                )
                result.append((self._text(row[0], row[1]), row[4]))
            else:
                row = FILE_RECORD.unpack_from(
                    self._map, self._sections["files"][0] + index * FILE_RECORD.size
                )
                result.append((self._text(row[0], row[1]), row[3]))
        return result

    def _symbol_at(self, index: int, files: list[str] | None = None) -> Symbol:
        files = files or [path for path, _ in self.files()]
        if self.format_version == LEGACY_VERSION:
            row = LEGACY_SYMBOL_RECORD.unpack_from(
                self._map, self.symbols_offset + index * LEGACY_SYMBOL_RECORD.size
            )
            qualified = self._text(row[0], row[1])
            file = files[row[2]]
            return Symbol(
                row and qualified.rsplit(".", 1)[-1],
                qualified,
                ID_TO_KIND[row[5]],
                file,
                row[3],
                row[4],
                stable_id(file.split("/", 1)[0], file, "python", qualified, ""),
            )
        row = SYMBOL_RECORD.unpack_from(
            self._map, self._sections["symbols"][0] + index * SYMBOL_RECORD.size
        )
        name = self._text(row[0], row[1])
        qualified = self._text(row[2], row[3])
        signature = self._text(row[4], row[5])
        return Symbol(
            name,
            qualified,
            ID_TO_KIND[row[9]],
            files[row[6]],
            row[7],
            row[8],
            row[10].hex(),
            signature,
        )

    def symbols(self) -> list[Symbol]:
        files = [path for path, _ in self.files()]
        return [self._symbol_at(index, files) for index in range(self.symbol_count)]

    def _indexes(self) -> dict[str, Any]:
        if self.format_version == LEGACY_VERSION:
            return {}
        value = json.loads(self._section_bytes("indexes"))
        return value

    def find_exact(self, query: str) -> list[Symbol]:
        if self.format_version == LEGACY_VERSION:
            return [
                symbol
                for symbol in self.symbols()
                if symbol.qualified_name.casefold() == query.casefold()
            ]
        indexes = self._indexes()["exact"]
        files = [path for path, _ in self.files()]
        return [
            self._symbol_at(index, files) for index in indexes.get(query.casefold(), [])
        ]

    def search(
        self,
        query: str,
        *,
        prefix: bool = False,
        path: str | None = None,
        kind: str | None = None,
    ) -> list[Symbol]:
        needle = query.casefold()
        if self.format_version == LEGACY_VERSION:
            candidates = list(range(self.symbol_count))
        else:
            indexes = self._indexes()
            if prefix:
                candidates = [
                    index
                    for name, values in indexes["names"].items()
                    if name.startswith(needle)
                    for index in values
                ]
            else:
                candidates = [
                    index
                    for name, values in indexes["names"].items()
                    if needle in name
                    for index in values
                ]
                candidates.extend(
                    index
                    for name, values in indexes["exact"].items()
                    if needle in name
                    for index in values
                )
            if path is not None:
                candidates = sorted(
                    set(candidates).intersection(indexes["paths"].get(path, []))
                )
            if kind is not None:
                candidates = sorted(
                    set(candidates).intersection(indexes["kinds"].get(kind, []))
                )
        files = [path_value for path_value, _ in self.files()]
        result = [self._symbol_at(index, files) for index in sorted(set(candidates))]
        return sorted(
            result,
            key=lambda item: (
                item.name.casefold(),
                item.qualified_name,
                item.file,
                item.line,
            ),
        )

    def find(self, query: str) -> list[Symbol]:
        return self.search(query)

    def relations(self) -> list[Relation]:
        if self.format_version == LEGACY_VERSION:
            return []
        return [
            Relation(**value) for value in json.loads(self._section_bytes("relations"))
        ]

    def invalidation_closure(
        self,
        changed_paths: Iterable[str],
        *,
        max_symbols: int = 10_000,
        max_files: int = 1_000,
    ) -> dict[str, object]:
        """Return a deterministic, bounded reverse dependency closure."""
        if max_symbols < 1 or max_files < 1:
            raise ValueError("max_symbols and max_files must be positive")
        paths = tuple(
            sorted(
                {
                    str(path).replace("\\", "/").strip("/")
                    for path in changed_paths
                    if str(path).strip()
                }
            )
        )
        symbols = self.symbols()
        by_id = {symbol.symbol_id: symbol for symbol in symbols}
        name_to_ids: dict[str, set[str]] = {}
        for symbol in symbols:
            for name in (symbol.name, symbol.qualified_name):
                name_to_ids.setdefault(name.casefold(), set()).add(symbol.symbol_id)

        reverse: dict[str, set[str]] = {}
        edge_count = 0
        for relation in self.relations():
            origins = (
                {relation.origin_id}
                if relation.origin_id
                else name_to_ids.get(relation.origin.casefold(), set())
            )
            origins = {origin for origin in origins if origin in by_id}
            if not origins:
                continue
            destinations = {relation.destination.casefold()}
            if relation.destination_id:
                destinations.add(relation.destination_id.casefold())
            for destination in destinations:
                reverse.setdefault(destination, set()).update(origins)
            edge_count += len(origins)

        frontier = sorted(
            symbol.symbol_id for symbol in symbols if symbol.file in paths
        )
        affected: set[str] = set()
        while frontier and len(affected) < max_symbols:
            current = frontier.pop(0)
            if current in affected or current not in by_id:
                continue
            affected.add(current)
            symbol = by_id[current]
            keys = {
                current.casefold(),
                symbol.name.casefold(),
                symbol.qualified_name.casefold(),
            }
            frontier.extend(
                sorted(
                    {
                        origin
                        for key in keys
                        for origin in reverse.get(key, set())
                        if origin not in affected
                    }
                )
            )

        selected = sorted(
            (by_id[symbol_id] for symbol_id in affected),
            key=lambda item: (item.file, item.line, item.qualified_name),
        )
        files = sorted({symbol.file for symbol in selected})
        files_truncated = len(files) > max_files
        truncated = bool(frontier) or files_truncated
        status = (
            "no_op" if not selected else "truncated" if truncated else "invalidated"
        )
        return {
            "schema": "simplicio.fast.invalidation-closure/v1",
            "status": status,
            "reason_code": "no_changed_symbols"
            if not selected
            else "closure_bounded"
            if truncated
            else "dependency_changed",
            "changed_paths": paths,
            "affected_symbol_ids": [symbol.symbol_id for symbol in selected],
            "affected_symbols": [symbol.qualified_name for symbol in selected],
            "affected_files": files[:max_files],
            "edge_count": edge_count,
            "truncated": truncated,
        }

    def impact(self, query: str) -> list[Relation]:
        needle = query.casefold()
        symbols = self.search(query)
        ids = {symbol.symbol_id for symbol in symbols}
        names = {symbol.name.casefold() for symbol in symbols}
        qualified = {symbol.qualified_name.casefold() for symbol in symbols}
        result = []
        for relation in self.relations():
            fields = {
                relation.origin.casefold(),
                relation.destination.casefold(),
                relation.origin_id.casefold(),
                relation.destination_id.casefold(),
            }
            if (
                needle in fields
                or any(needle in value for value in fields)
                or ids.intersection(fields)
                or names.intersection(fields)
                or qualified.intersection(fields)
            ):
                result.append(relation)
        return sorted(
            result,
            key=lambda item: (
                item.kind,
                item.origin,
                item.destination,
                item.confidence,
            ),
        )

    def context(
        self,
        root: Path,
        query: str,
        *,
        max_results: int = 10,
        max_lines: int = 120,
        max_bytes: int = 32_000,
        max_tokens: int | None = None,
        mapper_provenance: Mapping[str, Any] | None = None,
    ) -> list[ContextSpan]:
        return self.context_many(
            root,
            (query,),
            max_results=max_results,
            max_lines=max_lines,
            max_bytes=max_bytes,
            max_tokens=max_tokens,
            mapper_provenance=mapper_provenance,
        )

    def context_many(
        self,
        root: Path,
        queries: Iterable[str],
        *,
        max_results: int = 10,
        max_lines: int = 120,
        max_bytes: int = 32_000,
        max_tokens: int | None = None,
        mapper_provenance: Mapping[str, Any] | None = None,
    ) -> list[ContextSpan]:
        """Resolve several queries with one verified source cache per request."""
        if (
            max_results < 1
            or max_lines < 1
            or max_bytes < 1
            or (max_tokens is not None and max_tokens < 1)
        ):
            raise ValueError("context limits must be positive")
        if mapper_provenance is not None:
            self.require_mapper(mapper_provenance)
        root = root.resolve()
        expected_hashes = {path: digest for path, digest in self.files()}
        spans: list[ContextSpan] = []
        consumed = consumed_tokens = 0
        seen: set[tuple[str, int, int]] = set()
        # A single context request may match many symbols in one file. Keep
        # the verified source bytes local to this request so each file is
        # read, decoded and hashed at most once.
        source_cache: dict[str, tuple[bytes, str, list[str]]] = {}
        for query in queries:
            for symbol in self.find(query):
                if len(spans) >= max_results:
                    return spans
                if symbol.file not in expected_hashes:
                    raise ValueError(f"symbol references unknown file: {symbol.file}")
                path = (root / symbol.file).resolve()
                try:
                    path.relative_to(root)
                except ValueError as error:
                    raise ValueError(
                        f"snapshot path escapes root: {symbol.file}"
                    ) from error
                cached_source = source_cache.get(symbol.file)
                if cached_source is None:
                    contents = path.read_bytes()
                    actual_hash = hashlib.sha256(contents).digest()
                    try:
                        lines = contents.decode("utf-8").splitlines()
                    except UnicodeDecodeError as error:
                        raise ValueError(f"source is not valid UTF-8: {symbol.file}") from error
                    source_cache[symbol.file] = (contents, actual_hash.hex(), lines)
                else:
                    contents, actual_hash_hex, lines = cached_source
                    actual_hash = bytes.fromhex(actual_hash_hex)
                if actual_hash != expected_hashes[symbol.file]:
                    raise StaleSnapshotError(
                        f"source changed after snapshot: {symbol.file}; run simplicio-fast refresh"
                    )
                start = symbol.line
                requested_end = symbol.end_line
                end = min(requested_end, start + max_lines - 1)
                source_line_starts = [0]
                source_line_starts.extend(
                    index + 1
                    for index, value in enumerate(contents)
                    if value == 10
                )
                source_start = source_line_starts[
                    min(start - 1, len(source_line_starts) - 1)
                ]
                key = (symbol.file, start, end)
                if key in seen:
                    continue
                snippet = "\n".join(lines[start - 1 : end])
                truncated = end < requested_end
                content_truncated = False
                if consumed + len(snippet.encode("utf-8")) > max_bytes:
                    remaining = max_bytes - consumed
                    if remaining <= 0:
                        return spans
                    snippet = snippet.encode("utf-8")[:remaining].decode(
                        "utf-8", errors="ignore"
                    )
                    truncated = True
                    content_truncated = True
                encoded_size = len(snippet.encode("utf-8"))
                tokens = max(1, (encoded_size + 3) // 4) if encoded_size else 0
                if max_tokens is not None and consumed_tokens + tokens > max_tokens:
                    remaining_tokens = max_tokens - consumed_tokens
                    if remaining_tokens <= 0:
                        return spans
                    snippet = snippet.encode("utf-8")[: remaining_tokens * 4].decode(
                        "utf-8", errors="ignore"
                    )
                    truncated = True
                    content_truncated = True
                    encoded_size = len(snippet.encode("utf-8"))
                    tokens = max(1, (encoded_size + 3) // 4) if encoded_size else 0
                seen.add(key)
                consumed += encoded_size
                consumed_tokens += tokens
                content_bytes = snippet.encode("utf-8")
                delivered_end = (
                    start + snippet.count("\n")
                    if content_truncated and snippet and not snippet.endswith("\n")
                    else start + snippet.count("\n") - 1
                    if content_truncated and snippet
                    else end
                )
                omitted_start = (
                    delivered_end
                    if content_truncated and snippet and not snippet.endswith("\n")
                    else start
                    if content_truncated and not snippet
                    else delivered_end + 1
                )
                omitted_ranges = (
                    ((omitted_start, requested_end),)
                    if truncated and omitted_start <= requested_end
                    else ()
                )
                spans.append(
                    ContextSpan(
                        symbol.qualified_name,
                        symbol.kind,
                        symbol.file,
                        start,
                        delivered_end,
                        actual_hash.hex(),
                        snippet,
                        symbol.symbol_id,
                        tokens,
                        None,
                        None,
                        start,
                        requested_end,
                        source_start,
                        source_start + len(content_bytes),
                        hashlib.sha256(content_bytes).hexdigest(),
                        "partial" if truncated else "complete",
                        omitted_ranges,
                        truncated,
                    )
                )
        return spans

    def stats(self) -> dict[str, object]:
        return {
            "format": f"SFAST001/v{self.format_version}",
            "version": self.format_version,
            "generation": self.generation,
            "bytes": len(self._map),
            "files": self.file_count,
            "symbols": self.symbol_count,
            "relations": self.relation_count,
            "sections": sorted(self._sections),
            "provenance": self.provenance,
            "repository_id": self.provenance.get("repository_id"),
            "mapper_generation": self.provenance.get("mapper_generation"),
            "artifact_digest": self.provenance.get("artifact_digest"),
            "fast_format_version": self.provenance.get("fast_format_version"),
            "capability_coverage": self.provenance.get("capability_coverage"),
        }

    def grouped(self) -> dict[str, tuple[bytes, list[Symbol]]]:
        hashes = dict(self.files())
        grouped = {path: (digest, []) for path, digest in hashes.items()}
        for symbol in self.symbols():
            grouped[symbol.file][1].append(symbol)
        return grouped


def _validate_region(offset: int, length: int, limit: int, minimum: int) -> None:
    if offset < minimum or length < 0 or offset > limit or length > limit - offset:
        raise ValueError("snapshot offset or length is outside the mapped file")


def _validate_text(offset: int, length: int, limit: int) -> None:
    if offset < 0 or length < 0 or offset > limit or length > limit - offset:
        raise ValueError(
            "snapshot string offset or length is outside the string section"
        )
