"""Append-only, hash-chained source change journal reference."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SCHEMA = "simplicio.fast.change-journal/v1"
HEADER = {"schema": SCHEMA, "version": 1}
EVENT_TYPES = ("create", "update", "rename", "delete", "config", "schema")
ZERO_HASH = "0" * 64


class ChangeJournalError(ValueError):
    """A journal is invalid, stale, or cannot be recovered safely."""


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    sequence: int
    event_type: str
    path: str
    generation: str
    commit: str | None
    before_sha256: str | None
    after_sha256: str | None
    prev_hash: str
    record_hash: str

    def material(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("record_hash")
        return value

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def _sha(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value.lower()
    ):
        raise ChangeJournalError("sha256_invalid")
    return value.lower()


def _path(value: str) -> str:
    candidate = Path(value)
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        raise ChangeJournalError("path_outside_repository")
    return value.replace("\\", "/")


class ChangeJournal:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def _ensure_header(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("wb") as handle:
            handle.write(
                (
                    json.dumps(HEADER, sort_keys=True, separators=(",", ":")) + "\n"
                ).encode()
            )
            handle.flush()
            os.fsync(handle.fileno())

    def append(
        self,
        event_type: str,
        path: str,
        *,
        generation: str,
        commit: str | None = None,
        before_sha256: str | None = None,
        after_sha256: str | None = None,
    ) -> ChangeEvent:
        if event_type not in EVENT_TYPES:
            raise ChangeJournalError("event_type_invalid")
        path = _path(path)
        before_sha256 = _sha(before_sha256)
        after_sha256 = _sha(after_sha256)
        events = self.read()
        event = ChangeEvent(
            sequence=len(events) + 1,
            event_type=event_type,
            path=path,
            generation=generation,
            commit=commit,
            before_sha256=before_sha256,
            after_sha256=after_sha256,
            prev_hash=events[-1].record_hash if events else ZERO_HASH,
            record_hash="",
        )
        digest = hashlib.sha256(
            (
                event.prev_hash
                + json.dumps(event.material(), sort_keys=True, separators=(",", ":"))
            ).encode()
        ).hexdigest()
        event = ChangeEvent(**{**asdict(event), "record_hash": digest})
        self._ensure_header()
        with self.path.open("ab") as handle:
            handle.write((event.to_json() + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def read(self, *, recover: bool = False) -> list[ChangeEvent]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        lines = raw.splitlines(keepends=True)
        if not lines:
            raise ChangeJournalError("header_missing")
        try:
            header = json.loads(lines[0])
        except json.JSONDecodeError as error:
            raise ChangeJournalError("header_invalid") from error
        if header != HEADER:
            raise ChangeJournalError("schema_mismatch")
        events: list[ChangeEvent] = []
        for index, line in enumerate(lines[1:], start=1):
            if not line.endswith(b"\n"):
                if recover and index == len(lines) - 1:
                    break
                raise ChangeJournalError("truncated_tail")
            try:
                value = json.loads(line)
                event = ChangeEvent(**value)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise ChangeJournalError(f"record_invalid:{index}") from error
            self._verify_event(event, events)
            events.append(event)
        return events

    def events_since(
        self,
        *,
        sequence: int = 0,
        generation: str | None = None,
        max_events: int | None = None,
    ) -> list[ChangeEvent]:
        """Return a verified event window, failing closed when its bound overflows."""
        if not isinstance(sequence, int) or sequence < 0:
            raise ChangeJournalError("sequence_invalid")
        if max_events is not None and (
            not isinstance(max_events, int)
            or isinstance(max_events, bool)
            or max_events < 1
        ):
            raise ChangeJournalError("max_events_invalid")
        event_list = self.read()
        selected = [
            event
            for event in event_list
            if event.sequence > sequence
            and (generation is None or event.generation == generation)
        ]
        if max_events is not None and len(selected) > max_events:
            raise ChangeJournalError("event_window_overflow")
        return selected

    def changed_paths_since(
        self,
        *,
        sequence: int = 0,
        generation: str | None = None,
        max_events: int | None = None,
    ) -> tuple[str, ...]:
        """Return stable unique paths for a verified bounded event window."""
        return tuple(
            sorted(
                {
                    event.path
                    for event in self.events_since(
                        sequence=sequence, generation=generation, max_events=max_events
                    )
                }
            )
        )

    def recover(self) -> dict[str, Any]:
        events = self.read(recover=True)
        raw = self.path.read_bytes() if self.path.exists() else b""
        if raw and not raw.endswith(b"\n"):
            last_newline = raw.rfind(b"\n")
            self.path.write_bytes(raw[: last_newline + 1])
        return {
            "schema": "simplicio.fast.change-journal-recovery/v1",
            "status": "recovered" if raw and not raw.endswith(b"\n") else "valid",
            "events": len(events),
            "last_hash": events[-1].record_hash if events else ZERO_HASH,
        }

    @staticmethod
    def _verify_event(event: ChangeEvent, previous: list[ChangeEvent]) -> None:
        expected_sequence = len(previous) + 1
        expected_prev = previous[-1].record_hash if previous else ZERO_HASH
        if event.sequence != expected_sequence or event.prev_hash != expected_prev:
            raise ChangeJournalError("chain_mismatch")
        expected = hashlib.sha256(
            (
                event.prev_hash
                + json.dumps(event.material(), sort_keys=True, separators=(",", ":"))
            ).encode()
        ).hexdigest()
        if event.record_hash != expected:
            raise ChangeJournalError("record_hash_mismatch")
