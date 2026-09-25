"""Bounded, read-only structural navigation over a Fast snapshot."""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .snapshot import Snapshot, Symbol

CONTRACT = "simplicio.fast-navigation/v1"
PROVENANCE_SCHEMA = "simplicio.fast.provenance/v1"
RELATIONS = frozenset(
    {
        "definition",
        "references",
        "callers",
        "callees",
        "imports",
        "dependents",
        "implementations",
        "overrides",
        "tests",
        "history",
        "next_executable_hop",
        "previous_executable_hop",
    }
)
DIRECTIONS = frozenset({"incoming", "outgoing"})
MAX_NODES = 4096
MAX_BYTES = 1024 * 1024


class NavigationError(RuntimeError):
    """Stable, machine-readable failure from the navigation contract."""

    def __init__(
        self, reason_code: str, message: str, *, generation: str | None = None
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.generation = generation


@dataclass(frozen=True, slots=True)
class NavigationBudget:
    max_nodes: int = 20
    max_bytes: int = 8192
    max_depth: int = 1

    @classmethod
    def coerce(
        cls, value: "NavigationBudget | Mapping[str, Any] | int | None"
    ) -> "NavigationBudget":
        if value is None:
            return cls()
        if isinstance(value, cls):
            candidate = value
        elif isinstance(value, int) and not isinstance(value, bool):
            candidate = cls(max_nodes=value)
        elif isinstance(value, Mapping):
            defaults = cls()
            candidate = cls(
                max_nodes=value.get(
                    "max_nodes", value.get("nodes", defaults.max_nodes)
                ),
                max_bytes=value.get(
                    "max_bytes", value.get("bytes", defaults.max_bytes)
                ),
                max_depth=value.get(
                    "max_depth", value.get("depth", defaults.max_depth)
                ),
            )
        else:
            raise NavigationError(
                "invalid_budget",
                "budget must be an integer, mapping, or NavigationBudget",
            )

        if any(
            isinstance(item, bool) or not isinstance(item, int)
            for item in asdict(candidate).values()
        ):
            raise NavigationError("invalid_budget", "budget values must be integers")
        if (
            candidate.max_nodes < 1
            or candidate.max_bytes < 1
            or candidate.max_depth < 1
        ):
            raise NavigationError("invalid_budget", "budget values must be positive")
        return cls(
            min(candidate.max_nodes, MAX_NODES),
            min(candidate.max_bytes, MAX_BYTES),
            candidate.max_depth,
        )


@dataclass(frozen=True, slots=True)
class NavigationItem:
    id: str
    relation: str
    direction: str
    kind: str
    qualified_name: str
    file: str
    line: int
    snippet: str
    confidence: float
    provenance: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class NavigationPage:
    schema: str
    items: tuple[NavigationItem, ...]
    ids: tuple[str, ...]
    provenance: Mapping[str, Any]
    confidence: float
    generation: str
    cursor: str | None
    truncated: bool = False
    complete: bool = True
    residual: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["items"] = [item.to_dict() for item in self.items]
        value["ids"] = list(self.ids)
        return value


class NavigationIndex:
    """Bind the v1 API to one already-open Fast snapshot."""

    def __init__(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self._generation = snapshot.generation
        self._symbols = tuple(snapshot.symbols())
        self._by_id = {
            symbol.symbol_id: symbol for symbol in self._symbols if symbol.symbol_id
        }
        self._relations = tuple(snapshot.relations())

    @property
    def generation(self) -> str:
        return self._generation

    def navigate(
        self,
        handle: str,
        relation: str,
        direction: str,
        budget: NavigationBudget | Mapping[str, Any] | int | None,
        cursor: str | None = None,
        generation: str | None = None,
    ) -> NavigationPage:
        self._check_generation(generation)
        if relation not in RELATIONS:
            raise NavigationError(
                "invalid_relation",
                f"unsupported relation: {relation}",
                generation=self._generation,
            )
        if direction not in DIRECTIONS:
            raise NavigationError(
                "invalid_direction",
                f"unsupported direction: {direction}",
                generation=self._generation,
            )
        limits = NavigationBudget.coerce(budget)
        symbol = self._by_id.get(handle)
        if symbol is None:
            raise NavigationError(
                "unknown_handle",
                "handle is not a canonical snapshot symbol ID",
                generation=self._generation,
            )

        start = self._cursor_offset(cursor, handle, relation, direction)
        candidates, residual = self._candidates(symbol, relation, direction)
        items = [
            self._item(symbol, target, relation, direction, confidence, raw_kind)
            for target, confidence, raw_kind in candidates
        ]
        if relation == "next_executable_hop":
            items.sort(
                key=lambda item: (
                    -item.confidence,
                    item.qualified_name.casefold(),
                    item.file,
                    item.line,
                    item.id,
                )
            )
        else:
            items.sort(
                key=lambda item: (
                    item.qualified_name.casefold(),
                    item.file,
                    item.line,
                    item.id,
                )
            )
        items = self._deduplicate(items)

        selected: list[NavigationItem] = []
        consumed = 0
        next_offset = start
        for index in range(start, len(items)):
            item = items[index]
            item_bytes = len(
                json.dumps(
                    item.to_dict(), sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            )
            if selected and consumed + item_bytes > limits.max_bytes:
                break
            if not selected and item_bytes > limits.max_bytes:
                next_offset = index + 1
                break
            selected.append(item)
            consumed += item_bytes
            next_offset = index + 1
            if len(selected) >= limits.max_nodes:
                break

        truncated = next_offset < len(items)
        next_cursor = None
        if truncated:
            next_cursor = self._encode_cursor(handle, relation, direction, next_offset)
        page_provenance = {
            "schema": PROVENANCE_SCHEMA,
            "repository_root": None,
            "source_commit": None,
            "source_commit_reason": "navigation_bound_to_open_snapshot",
            "snapshot_path": str(self.snapshot.path),
            "snapshot_sha256": self.snapshot.sha256,
            "snapshot_generation": self._generation,
            "snapshot_version": self.snapshot.format_version,
            "snapshot_provenance": self.snapshot.provenance,
            "item_count": len(selected),
            "limits": {
                "max_nodes": limits.max_nodes,
                "max_bytes": limits.max_bytes,
                "max_depth": limits.max_depth,
            },
            "handle": handle,
        }
        return NavigationPage(
            CONTRACT,
            tuple(selected),
            tuple(item.id for item in selected),
            page_provenance,
            min((item.confidence for item in selected), default=0.0),
            self._generation,
            next_cursor,
            truncated,
            residual is None,
            residual,
        )

    def _check_generation(self, generation: str | None) -> None:
        if generation is not None and generation != self._generation:
            raise NavigationError(
                "stale_generation",
                "requested generation does not match the opened snapshot",
                generation=self._generation,
            )

    def _cursor_offset(
        self, cursor: str | None, handle: str, relation: str, direction: str
    ) -> int:
        if cursor is None:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as error:
            raise NavigationError(
                "invalid_cursor",
                "cursor is not a valid navigation cursor",
                generation=self._generation,
            ) from error
        if not isinstance(payload, dict) or payload.get("schema") != CONTRACT:
            raise NavigationError(
                "invalid_cursor",
                "cursor schema is invalid",
                generation=self._generation,
            )
        if payload.get("generation") != self._generation:
            raise NavigationError(
                "stale_generation",
                "cursor belongs to a different snapshot generation",
                generation=self._generation,
            )
        if (
            payload.get("handle") != handle
            or payload.get("relation") != relation
            or payload.get("direction") != direction
        ):
            raise NavigationError(
                "invalid_cursor",
                "cursor does not match the navigation request",
                generation=self._generation,
            )
        offset = payload.get("offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise NavigationError(
                "invalid_cursor",
                "cursor offset is invalid",
                generation=self._generation,
            )
        return offset

    def _encode_cursor(
        self, handle: str, relation: str, direction: str, offset: int
    ) -> str:
        payload = {
            "schema": CONTRACT,
            "generation": self._generation,
            "handle": handle,
            "relation": relation,
            "direction": direction,
            "offset": offset,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _candidates(
        self, symbol: Symbol, relation: str, direction: str
    ) -> tuple[list[tuple[Symbol, float, str]], str | None]:
        if relation == "definition":
            return [(symbol, 1.0, "definition")], None
        if relation in {"next_executable_hop", "previous_executable_hop"}:
            required_direction = (
                "outgoing" if relation == "next_executable_hop" else "incoming"
            )
            if direction != required_direction:
                return [], f"{relation}_requires_{required_direction}"
            candidates: list[tuple[Symbol, float, str]] = []
            for edge in self._relations:
                if edge.kind != "call":
                    continue
                if (
                    relation == "next_executable_hop"
                    and edge.origin_id == symbol.symbol_id
                ):
                    target = self._resolve(edge.destination_id, edge.destination)
                elif relation == "previous_executable_hop" and (
                    edge.destination_id == symbol.symbol_id
                    or self._name_matches(symbol, edge.destination)
                ):
                    target = self._by_id.get(edge.origin_id)
                else:
                    continue
                if target is not None and target.symbol_id != symbol.symbol_id:
                    candidates.append((target, edge.confidence, "call"))
            candidates.sort(
                key=lambda row: (
                    -row[1],
                    row[0].qualified_name.casefold(),
                    row[0].file,
                    row[0].line,
                    row[0].symbol_id,
                )
            )
            return candidates[:1], None
        raw_kind = {
            "references": "reference",
            "callers": "call",
            "callees": "call",
            "tests": "test",
        }.get(relation)
        if raw_kind is None:
            return [], "relation_not_materialized_by_sfast_v2"

        result: list[tuple[Symbol, float, str]] = []
        for edge in self._relations:
            if edge.kind != raw_kind:
                continue
            target: Symbol | None = None
            if direction == "outgoing" and edge.origin_id == symbol.symbol_id:
                target = self._resolve(edge.destination_id, edge.destination)
            elif direction == "incoming" and (
                edge.destination_id == symbol.symbol_id
                or self._name_matches(symbol, edge.destination)
            ):
                target = self._by_id.get(edge.origin_id)
            if target is not None and target.symbol_id != symbol.symbol_id:
                result.append((target, edge.confidence, edge.kind))
        return result, None

    def _resolve(self, identifier: str, name: str) -> Symbol | None:
        if identifier:
            resolved = self._by_id.get(identifier)
            if resolved is not None:
                return resolved
        exact = [
            item
            for item in self._symbols
            if item.qualified_name.casefold() == name.casefold()
        ]
        if not exact:
            exact = [
                item
                for item in self._symbols
                if item.name.casefold() == name.casefold()
            ]
        return exact[0] if len(exact) == 1 else None

    @staticmethod
    def _name_matches(symbol: Symbol, name: str) -> bool:
        needle = name.casefold()
        return needle in {symbol.name.casefold(), symbol.qualified_name.casefold()}

    @staticmethod
    def _deduplicate(items: list[NavigationItem]) -> list[NavigationItem]:
        result: list[NavigationItem] = []
        seen: set[str] = set()
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            result.append(item)
        return result

    def _item(
        self,
        source: Symbol,
        target: Symbol,
        relation: str,
        direction: str,
        confidence: float,
        raw_kind: str,
    ) -> NavigationItem:
        provenance = {
            "schema": PROVENANCE_SCHEMA,
            "repository_root": None,
            "source_commit": None,
            "source_commit_reason": "navigation_bound_to_open_snapshot",
            "snapshot_path": str(self.snapshot.path),
            "snapshot_sha256": self.snapshot.sha256,
            "snapshot_generation": self._generation,
            "snapshot_version": self.snapshot.format_version,
            "snapshot_provenance": self.snapshot.provenance,
            "source_id": source.symbol_id,
            "relation_kind": raw_kind,
        }
        return NavigationItem(
            target.symbol_id,
            relation,
            direction,
            target.kind,
            target.qualified_name,
            target.file,
            target.line,
            f"{target.qualified_name} ({target.file}:{target.line})",
            max(0.0, min(1.0, confidence)),
            provenance,
        )


def navigate(
    snapshot: Snapshot,
    handle: str,
    relation: str,
    direction: str,
    budget: NavigationBudget | Mapping[str, Any] | int | None,
    cursor: str | None = None,
    generation: str | None = None,
) -> NavigationPage:
    """Navigate one bounded hop from a canonical ID in an open snapshot."""

    return NavigationIndex(snapshot).navigate(
        handle, relation, direction, budget, cursor, generation
    )


__all__ = [
    "CONTRACT",
    "DIRECTIONS",
    "NavigationBudget",
    "NavigationError",
    "NavigationIndex",
    "NavigationItem",
    "NavigationPage",
    "RELATIONS",
    "navigate",
]
