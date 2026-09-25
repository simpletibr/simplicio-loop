"""Incremental graph generations, coverage manifest and portable snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .structural_graph import StructuralGraph, graph_from_dict
from .structural_parser import ParsedFile, parse_source

COVERAGE_SCHEMA = "simplicio.mapper-coverage/v1"
SNAPSHOT_SCHEMA = "simplicio.graph-snapshot/v1"


def _hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    content_hash: str
    size: int
    parser: str
    confidence: float
    syntax_errors: tuple[str, ...] = ()
    unsupported_constructs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SyncReport:
    generation_id: str
    changed_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]
    reused_paths: tuple[str, ...]
    parsed_paths: tuple[str, ...]
    coverage: dict[str, object]


class IncrementalGraphIndex:
    def __init__(self, repo_identity: str, generation_id: str, graph: StructuralGraph | None = None, records: Iterable[FileRecord] = ()) -> None:
        self.repo_identity = repo_identity
        self.generation_id = generation_id
        self.graph = graph or StructuralGraph(repo_identity, generation_id)
        self.records = {record.path: record for record in records}

    def update(self, files: Mapping[str, str], *, generation_id: str | None = None) -> SyncReport:
        next_generation = generation_id or self.generation_id
        current_hashes = {path: _hash(source) for path, source in files.items()}
        previous_paths = set(self.records)
        changed = {path for path, content_hash in current_hashes.items() if self.records.get(path, FileRecord(path, "", 0, "", 0.0)).content_hash != content_hash}
        removed = previous_paths - set(files)
        reusable_paths = previous_paths - changed - removed
        parsed: dict[str, ParsedFile] = {
            path: parse_source(path, files[path], self.repo_identity, next_generation)
            for path in sorted(changed)
        }
        next_graph = StructuralGraph(self.repo_identity, next_generation)
        affected = changed | removed
        for node in self.graph.nodes:
            if node.path not in affected and (not node.generation_id or node.generation_id == self.generation_id):
                next_graph.add_node(replace(node, generation_id=next_generation))
        for item in parsed.values():
            for node in item.nodes:
                next_graph.add_node(node)
        for edge in self.graph.edges:
            source = self.graph.get(edge.source_id)
            target = self.graph.get(edge.target_id)
            if source and target and source.path not in affected and target.path not in affected and source.node_id in {node.node_id for node in next_graph.nodes} and target.node_id in {node.node_id for node in next_graph.nodes}:
                next_graph.add_edge(edge)
        for item in parsed.values():
            for edge in item.edges:
                next_graph.add_edge(edge)
        next_records = {}
        for path in sorted(files):
            item = parsed.get(path)
            old = self.records.get(path)
            if item is None and old is not None:
                next_records[path] = old
            elif item is not None:
                next_records[path] = FileRecord(path, item.content_hash, len(files[path].encode("utf-8")), item.coverage.parser, item.coverage.confidence, item.coverage.syntax_errors, item.coverage.unsupported_constructs)
        self.graph = next_graph
        self.generation_id = next_generation
        self.records = next_records
        coverage = self.coverage_manifest()
        return SyncReport(next_generation, tuple(sorted(changed)), tuple(sorted(removed)), tuple(sorted(reusable_paths)), tuple(sorted(parsed)), coverage)

    def coverage_manifest(self) -> dict[str, object]:
        files = [asdict(record) for record in sorted(self.records.values(), key=lambda item: item.path)]
        for file in files:
            file["syntax_errors"] = list(file["syntax_errors"])
            file["unsupported_constructs"] = list(file["unsupported_constructs"])
        confidence = sum(float(file["confidence"]) for file in files) / len(files) if files else 0.0
        return {"schema": COVERAGE_SCHEMA, "generation_id": self.generation_id, "repo_identity": self.repo_identity, "files": files, "file_count": len(files), "confidence": round(confidence, 6), "fresh": True}

    def snapshot(self, target: str | os.PathLike[str]) -> Path:
        payload = {"schema": SNAPSHOT_SCHEMA, "codec": "zlib", "coverage": self.coverage_manifest(), "graph": self.graph.to_dict()}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        envelope = {"schema": SNAPSHOT_SCHEMA, "codec": "zlib", "sha256": hashlib.sha256(canonical).hexdigest(), "payload": zlib.compress(canonical, level=9).hex()}
        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                json.dump(envelope, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return destination

    @classmethod
    def restore(cls, source: str | os.PathLike[str]) -> IncrementalGraphIndex:
        envelope = json.loads(Path(source).read_text(encoding="ascii"))
        if envelope.get("schema") != SNAPSHOT_SCHEMA or envelope.get("codec") != "zlib":
            raise ValueError("unsupported or incompatible graph snapshot")
        try:
            canonical = zlib.decompress(bytes.fromhex(envelope["payload"]))
        except (KeyError, ValueError, zlib.error) as error:
            raise ValueError("corrupt graph snapshot") from error
        if hashlib.sha256(canonical).hexdigest() != envelope.get("sha256"):
            raise ValueError("graph snapshot integrity mismatch")
        payload = json.loads(canonical)
        graph = graph_from_dict(payload["graph"])
        records = [FileRecord(**record) for record in payload["coverage"]["files"]]
        return cls(graph.repo_identity, graph.generation_id, graph, records)


__all__ = ["COVERAGE_SCHEMA", "FileRecord", "IncrementalGraphIndex", "SNAPSHOT_SCHEMA", "SyncReport"]
