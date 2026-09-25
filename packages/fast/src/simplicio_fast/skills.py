"""Host-authorized skill discovery and bounded handle materialization.

The host/provider owns discovery and authorization.  This module accepts only
already-authorized records; it never walks directories or treats a file's
presence as permission.  Fast owns deterministic ranking, opaque handles and
bounded content expansion, while Runtime remains optional and out of scope for
this standalone source slice.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable

from .catalog import AddressCatalog


SKILL_CATALOG_SCHEMA = "simplicio.fast.skill-catalog/v1"
SKILL_MATERIALIZATION_SCHEMA = "simplicio.fast.skill-materialization/v1"
SKILL_NAMESPACE = "skill"
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]*")


@dataclass(frozen=True, slots=True)
class AuthorizedSkill:
    """A skill record authorized by the host/provider before Fast sees it."""

    name: str
    version: str
    origin: str
    description: str
    content: str
    triggers: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    scope: str = "default"


@dataclass(frozen=True, slots=True)
class _RegisteredSkill:
    definition: AuthorizedSkill
    handle: str
    content_sha256: str


def _tokens(value: str) -> set[str]:
    return set(_TOKEN.findall(value.casefold()))


def _canonical_id(skill: AuthorizedSkill, content_sha256: str) -> str:
    identity = {
        "capabilities": sorted(skill.capabilities),
        "content_sha256": content_sha256,
        "name": skill.name,
        "origin": skill.origin,
        "scope": skill.scope,
        "triggers": sorted(skill.triggers),
        "version": skill.version,
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class SkillCatalog:
    """Bounded catalog for one repository, generation and authorization scope."""

    def __init__(
        self, repository: str, generation: str, *, scope: str = "default"
    ) -> None:
        if not scope:
            raise ValueError("scope must not be empty")
        self.repository = repository
        self.generation = generation
        self.scope = scope
        self._catalog = AddressCatalog(repository, generation)
        self._skills: dict[str, _RegisteredSkill] = {}

    def register(self, skill: AuthorizedSkill) -> str:
        """Register one host-authorized skill and return its opaque handle."""
        if not skill.name or not skill.version or not skill.origin:
            raise ValueError("skill name, version and origin must not be empty")
        if skill.scope != self.scope:
            raise ValueError("skill scope does not match catalog scope")
        if not isinstance(skill.content, str):
            raise TypeError("skill content must be text")
        payload = skill.content.encode("utf-8")
        content_sha256 = hashlib.sha256(payload).hexdigest()
        entry = self._catalog.register(
            SKILL_NAMESPACE,
            _canonical_id(skill, content_sha256),
            payload,
            source_sha256=content_sha256,
            segment_id=skill.origin,
        )
        self._skills[entry.handle] = _RegisteredSkill(
            skill, entry.handle, content_sha256
        )
        return entry.handle

    def register_many(self, skills: Iterable[AuthorizedSkill]) -> list[str]:
        return [self.register(skill) for skill in skills]

    def resolve(self, task: str, *, max_results: int = 32) -> dict[str, object]:
        """Return bounded T0 metadata; skill content is available only by handle."""
        if max_results < 1:
            raise ValueError("max_results must be positive")
        task_terms = _tokens(task)
        candidates: list[tuple[int, _RegisteredSkill, list[str], list[str]]] = []
        for skill in self._skills.values():
            definition = skill.definition
            trigger_terms = _tokens(" ".join(definition.triggers))
            metadata_terms = _tokens(
                " ".join(
                    (definition.name, definition.description, *definition.capabilities)
                )
            )
            matched_triggers = sorted(task_terms & trigger_terms)
            matched_metadata = sorted(task_terms & metadata_terms)
            score = len(matched_triggers) * 4 + len(matched_metadata)
            if score:
                candidates.append((score, skill, matched_triggers, matched_metadata))
        candidates.sort(
            key=lambda item: (
                -item[0],
                item[1].definition.name,
                item[1].definition.version,
            )
        )
        selected = candidates[:max_results]
        skills = [
            {
                "name": item[1].definition.name,
                "version": item[1].definition.version,
                "origin": item[1].definition.origin,
                "description": item[1].definition.description,
                "triggers": list(item[1].definition.triggers),
                "capabilities": list(item[1].definition.capabilities),
                "scope": self.scope,
                "handle": item[1].handle,
                "content_sha256": item[1].content_sha256,
                "applicability_score": item[0],
                "matched_triggers": item[2],
                "matched_metadata": item[3],
            }
            for item in selected
        ]
        truncated = len(selected) < len(candidates)
        return {
            "schema": SKILL_CATALOG_SCHEMA,
            "source": {
                "kind": SKILL_NAMESPACE,
                "status": "available",
                "runtime_required": False,
            },
            "repository": self.repository,
            "generation": self.generation,
            "scope": self.scope,
            "skills": skills,
            "handles": [item["handle"] for item in skills],
            "truncated": truncated,
            "reason_code": "skill_catalog_bounded"
            if truncated
            else "skill_catalog_complete",
        }

    def materialize(
        self,
        handles: Iterable[str],
        *,
        max_entries: int = 16,
        max_bytes: int = 256 * 1024,
    ) -> dict[str, object]:
        """Expand opaque skill handles without exceeding entry or byte budgets."""
        unique_handles = list(dict.fromkeys(handles))
        resolved = self._catalog.resolve_many_bounded(
            unique_handles,
            max_entries=max_entries,
            max_bytes=max_bytes,
            repository=self.repository,
            generation=self.generation,
            namespace=SKILL_NAMESPACE,
        )
        materialized = []
        for reference, item in zip(
            resolved["references"], resolved["materialized"], strict=True
        ):
            registered = self._skills[reference["handle"]]
            materialized.append(
                {
                    "handle": registered.handle,
                    "name": registered.definition.name,
                    "version": registered.definition.version,
                    "origin": registered.definition.origin,
                    "scope": self.scope,
                    "content_sha256": registered.content_sha256,
                    "content": item["payload"].decode("utf-8"),
                }
            )
        return {
            "schema": SKILL_MATERIALIZATION_SCHEMA,
            "source": {
                "kind": SKILL_NAMESPACE,
                "status": "available",
                "runtime_required": False,
            },
            "repository": self.repository,
            "generation": self.generation,
            "scope": self.scope,
            "references": resolved["references"],
            "materialized": materialized,
            "entries_materialized": resolved["entries_materialized"],
            "bytes_materialized": resolved["bytes_materialized"],
            "truncated": resolved["truncated"],
            "reason_code": resolved["reason_code"],
        }


__all__ = [
    "AuthorizedSkill",
    "SKILL_CATALOG_SCHEMA",
    "SKILL_MATERIALIZATION_SCHEMA",
    "SkillCatalog",
]
