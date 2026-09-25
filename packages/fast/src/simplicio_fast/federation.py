"""Bounded, deterministic federation of pinned projection members."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Sequence


MANIFEST_SCHEMA = "simplicio.fast.federation-manifest/v1"
EDGE_SCHEMA = "simplicio.fast.federated-edge/v1"
GENERATION_SCHEMA = "simplicio.fast.federated-generation/v1"
MAX_MEMBERS = 256
MAX_EDGES = 100_000
MAX_BYTES = 8 * 1024 * 1024


class FederationError(ValueError):
    """Raised when a federation cannot be safely compiled or queried."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _canonical(value: Any) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise FederationError("federation_not_json") from error
    if len(encoded) > MAX_BYTES:
        raise FederationError("federation_size_limit")
    return encoded


def _text(value: object, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FederationError(reason)
    return value


def _handle(value: object, reason: str) -> str:
    value = _text(value, reason)
    owner, separator, local = value.partition(":")
    if not separator or not owner.strip() or not local.strip():
        raise FederationError("edge_handle_invalid")
    return value


def _budget(value: object, reason: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise FederationError(reason)
    return value


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class FederationMember:
    repository: str
    commit: str
    generation: str
    schema: str
    digest: str
    scope: str = "*"
    tombstone: bool = False

    def __post_init__(self) -> None:
        for value, reason in (
            (self.repository, "member_repository_invalid"),
            (self.commit, "member_commit_invalid"),
            (self.generation, "member_generation_invalid"),
            (self.schema, "member_schema_invalid"),
            (self.digest, "member_digest_invalid"),
            (self.scope, "member_scope_invalid"),
        ):
            _text(value, reason)
        digest = self.digest.removeprefix("sha256:")
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise FederationError("member_digest_invalid")
        if not isinstance(self.tombstone, bool):
            raise FederationError("member_tombstone_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "commit": self.commit,
            "generation": self.generation,
            "schema": self.schema,
            "digest": self.digest,
            "scope": self.scope,
            "tombstone": self.tombstone,
        }


@dataclass(frozen=True, slots=True)
class FederatedEdge:
    source_handle: str
    target_handle: str
    relation_type: str
    confidence: float
    evidence: tuple[str, ...] = ()
    derived: bool = False

    def __post_init__(self) -> None:
        _handle(self.source_handle, "edge_source_invalid")
        _handle(self.target_handle, "edge_target_invalid")
        for value, reason in (
            (self.relation_type, "edge_relation_invalid"),
        ):
            _text(value, reason)
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(float(self.confidence))
            or not 0.0 <= self.confidence <= 1.0
        ):
            raise FederationError("edge_confidence_invalid")
        if not isinstance(self.evidence, (tuple, list)) or any(not isinstance(item, str) or not item.strip() for item in self.evidence):
            raise FederationError("edge_evidence_invalid")
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if not isinstance(self.derived, bool):
            raise FederationError("edge_derived_invalid")
        if self.derived and not self.evidence:
            raise FederationError("derived_edge_evidence_missing")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EDGE_SCHEMA,
            "source_handle": self.source_handle,
            "target_handle": self.target_handle,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "derived": self.derived,
        }


class Federation:
    """Immutable member/edge view with bounded read-only indexes."""

    def __init__(self, members: Sequence[FederationMember], edges: Sequence[FederatedEdge] = ()) -> None:
        if not isinstance(members, Sequence) or isinstance(members, (str, bytes)):
            raise FederationError("member_type_invalid")
        if not isinstance(edges, Sequence) or isinstance(edges, (str, bytes)):
            raise FederationError("edge_type_invalid")
        if not members or len(members) > MAX_MEMBERS:
            raise FederationError("member_count_limit")
        if len(edges) > MAX_EDGES:
            raise FederationError("edge_count_limit")
        if any(not isinstance(member, FederationMember) for member in members):
            raise FederationError("member_type_invalid")
        if any(not isinstance(edge, FederatedEdge) for edge in edges):
            raise FederationError("edge_type_invalid")
        repositories = [member.repository.casefold() for member in members]
        if len(repositories) != len(set(repositories)):
            raise FederationError("duplicate_member_repository")
        if any(member.tombstone for member in members):
            raise FederationError("member_tombstone_present")
        repository_set = set(repositories)

        def edge_repository(handle: str) -> str:
            return handle.split(":", 1)[0].casefold()

        if len(edges) != len(set(edges)):
            raise FederationError("duplicate_edge")
        for edge in edges:
            if (
                edge_repository(edge.source_handle) not in repository_set
                or edge_repository(edge.target_handle) not in repository_set
            ):
                raise FederationError("edge_member_missing")
        self.members = tuple(sorted(members, key=lambda item: (item.repository, item.generation)))
        self.edges = tuple(sorted(edges, key=lambda item: (item.source_handle, item.target_handle, item.relation_type)))
        self._consumers: dict[str, tuple[FederatedEdge, ...]] = {}
        self._dependencies: dict[str, tuple[FederatedEdge, ...]] = {}
        for edge in self.edges:
            self._consumers[edge.target_handle] = self._consumers.get(edge.target_handle, ()) + (edge,)
            self._dependencies[edge.source_handle] = self._dependencies.get(edge.source_handle, ()) + (edge,)

    @property
    def generation(self) -> str:
        return _digest({"members": [item.to_dict() for item in self.members], "edges": [item.to_dict() for item in self.edges]})

    def manifest(self) -> dict[str, Any]:
        body = {
            "schema": MANIFEST_SCHEMA,
            "members": [item.to_dict() for item in self.members],
            "edges": [item.to_dict() for item in self.edges],
            "generation": self.generation,
        }
        return {"schema": GENERATION_SCHEMA, "body": body, "digest": _digest(body)}

    def encode(self) -> bytes:
        return _canonical(self.manifest()) + b"\n"

    def apply_delta(
        self,
        changed_members: Sequence[FederationMember] = (),
        *,
        removed_repositories: Sequence[str] = (),
        added_edges: Sequence[FederatedEdge] = (),
        removed_edges: Sequence[FederatedEdge] = (),
    ) -> tuple["Federation", dict[str, Any]]:
        """Build a new generation from changed members without mutating this one."""
        changed_members = tuple(changed_members)
        removed_repositories = tuple(removed_repositories)
        added_edges = tuple(added_edges)
        removed_edges = tuple(removed_edges)
        if any(not isinstance(member, FederationMember) for member in changed_members):
            raise FederationError("delta_member_type_invalid")
        if any(not isinstance(edge, FederatedEdge) for edge in (*added_edges, *removed_edges)):
            raise FederationError("delta_edge_type_invalid")
        for repository in removed_repositories:
            _text(repository, "delta_repository_invalid")
        removed = {repository.casefold() for repository in removed_repositories}
        active_changes: dict[str, FederationMember] = {}
        tombstones = set(removed)
        for member in changed_members:
            key = member.repository.casefold()
            if key in removed or key in active_changes or key in tombstones:
                raise FederationError("delta_split_brain")
            if member.tombstone:
                tombstones.add(key)
            else:
                active_changes[key] = member
        members = [
            member
            for member in self.members
            if member.repository.casefold() not in tombstones
            and member.repository.casefold() not in active_changes
        ]
        members.extend(active_changes.values())
        removed_edge_set = set(removed_edges)
        def belongs_to_removed(edge: FederatedEdge) -> bool:
            return any(
                edge.source_handle.casefold().startswith(repository + ":")
                or edge.target_handle.casefold().startswith(repository + ":")
                for repository in tombstones
            )
        edges = [
            edge
            for edge in self.edges
            if edge not in removed_edge_set and not belongs_to_removed(edge)
        ]
        edges.extend(added_edges)
        next_generation = Federation(members, edges)
        closure = sorted(
            {
                handle
                for edge in (*added_edges, *removed_edges)
                for handle in (edge.source_handle, edge.target_handle)
            }
        )
        receipt = {
            "schema": "simplicio.fast.federated-delta/v1",
            "from_generation": self.generation,
            "to_generation": next_generation.generation,
            "changed_repositories": sorted(active_changes),
            "tombstones": sorted(tombstones),
            "closure_handles": closure,
            "reused_members": len(members) - len(active_changes),
            "complete": True,
        }
        return next_generation, receipt

    @staticmethod
    def _bounded_records(records: Iterable[dict[str, Any]], *, max_bytes: int) -> list[dict[str, Any]]:
        used = 0
        result: list[dict[str, Any]] = []
        for record in records:
            encoded = _canonical(record)
            if used + len(encoded) > max_bytes:
                raise FederationError("result_size_limit")
            result.append(record)
            used += len(encoded)
        if len(_canonical(result)) > max_bytes:
            raise FederationError("result_size_limit")
        return result

    def consumers(
        self,
        target_handle: str,
        *,
        max_edges: int = 1000,
        max_bytes: int = MAX_BYTES,
    ) -> list[dict[str, Any]]:
        _handle(target_handle, "target_handle_invalid")
        _budget(max_edges, "edge_budget_invalid", minimum=0, maximum=MAX_EDGES)
        _budget(max_bytes, "byte_budget_invalid", minimum=0, maximum=MAX_BYTES)
        records = (edge.to_dict() for edge in self._consumers.get(target_handle, ())[:max_edges])
        return self._bounded_records(records, max_bytes=max_bytes)

    def dependencies(
        self,
        source_handle: str,
        *,
        max_edges: int = 1000,
        max_bytes: int = MAX_BYTES,
    ) -> list[dict[str, Any]]:
        _handle(source_handle, "source_handle_invalid")
        _budget(max_edges, "edge_budget_invalid", minimum=0, maximum=MAX_EDGES)
        _budget(max_bytes, "byte_budget_invalid", minimum=0, maximum=MAX_BYTES)
        records = (edge.to_dict() for edge in self._dependencies.get(source_handle, ())[:max_edges])
        return self._bounded_records(records, max_bytes=max_bytes)

    def traverse(
        self,
        start_handle: str,
        *,
        max_depth: int = 8,
        max_nodes: int = 1000,
        max_edges: int = MAX_EDGES,
        max_bytes: int = MAX_BYTES,
    ) -> dict[str, Any]:
        _handle(start_handle, "source_handle_invalid")
        _budget(max_depth, "traversal_budget_invalid", minimum=0, maximum=MAX_EDGES)
        _budget(max_nodes, "traversal_budget_invalid", minimum=1, maximum=MAX_EDGES)
        _budget(max_edges, "edge_budget_invalid", minimum=0, maximum=MAX_EDGES)
        _budget(max_bytes, "byte_budget_invalid", minimum=0, maximum=MAX_BYTES)
        queue: list[tuple[str, int]] = [(start_handle, 0)]
        visited: set[str] = set()
        paths: dict[str, list[str]] = {start_handle: [start_handle]}
        edges: list[dict[str, Any]] = []
        used_bytes = 0
        truncation_reasons: set[str] = set()
        while queue and len(visited) < max_nodes:
            current, depth = queue.pop(0)
            if current in visited:
                continue
            if depth > max_depth:
                truncation_reasons.add("max_depth")
                continue
            visited.add(current)
            outgoing = self._dependencies.get(current, ())
            if depth == max_depth and outgoing:
                truncation_reasons.add("max_depth")
            for edge in outgoing:
                if len(edges) >= max_edges:
                    raise FederationError("edge_budget_exceeded")
                record = edge.to_dict()
                record_bytes = len(_canonical(record))
                if used_bytes + record_bytes > max_bytes:
                    raise FederationError("result_size_limit")
                edges.append(record)
                used_bytes += record_bytes
                if depth < max_depth and edge.target_handle not in visited and edge.target_handle not in paths:
                    paths[edge.target_handle] = paths[current] + [edge.target_handle]
                    queue.append((edge.target_handle, depth + 1))
        if queue:
            truncation_reasons.add("max_nodes")
        result = {
            "start_handle": start_handle,
            "nodes": sorted(visited),
            "edges": edges,
            "paths": paths,
            "complete": not queue and not truncation_reasons,
            "truncation_reasons": sorted(truncation_reasons),
        }
        if len(_canonical(result)) > max_bytes:
            raise FederationError("result_size_limit")
        return result


def compile_federation(members: Iterable[FederationMember], edges: Iterable[FederatedEdge] = ()) -> Federation:
    """Compile a pinned set; no implicit latest/member discovery is allowed."""
    return Federation(tuple(members), tuple(edges))


__all__ = [
    "EDGE_SCHEMA", "FederatedEdge", "Federation", "FederationError",
    "FederationMember", "GENERATION_SCHEMA", "MANIFEST_SCHEMA", "compile_federation",
]
