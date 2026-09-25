"""Cross-repository stack-lock validation for simplicio-fast.

The validator is intentionally dependency-free and read-only.  It consumes the
stack lock owned by the coordinating integration layer and emits a receipt that
binds every participating repository to an immutable commit, contract digest,
and explicit route.  Fast may compile and consume derived state, but it never
becomes the owner of source mutation, queue/lease state, completion, or effects.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

STACK_LOCK_SCHEMA = "simplicio.stack-lock/v1"
RECEIPT_SCHEMA = "simplicio.fast.cross-repo-receipt/v1"
REPOSITORY_NAMES = {
    "simplicio-mapper",
    "simplicio-fast",
    "simplicio-dev-cli",
    "simplicio-loop",
    "simplicio-runtime",
    "simplicio-agent",
    "simplicio-code",
}
BASE_REQUIRED_REPOSITORIES = {
    "wesleysimplicio/simplicio-mapper",
    "wesleysimplicio/simplicio-fast",
    "wesleysimplicio/simplicio-dev-cli",
    "wesleysimplicio/simplicio-loop",
}
RUNTIME_REPOSITORY = "wesleysimplicio/simplicio-runtime"
MAX_MEMBERS = 32
MAX_CONTRACTS = 128
MAX_ROUTES = 128
MAX_BYTES = 512 * 1024
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_PROFILES = {"loop-standalone", "runtime-backed"}
_AUTHORITY_OWNERS = {
    "source-mutation": "wesleysimplicio/simplicio-dev-cli",
    "queue": "wesleysimplicio/simplicio-loop",
    "lease": "wesleysimplicio/simplicio-loop",
    "completion": "wesleysimplicio/simplicio-loop",
    "effect": "wesleysimplicio/simplicio-runtime",
    "policy": "wesleysimplicio/simplicio-runtime",
}


class CrossRepoError(ValueError):
    """Raised when a stack lock is unsafe or cannot be verified."""

    def __init__(self, reason_code: str, path: str = "") -> None:
        self.reason_code = reason_code
        self.path = path
        suffix = f":{path}" if path else ""
        super().__init__(reason_code + suffix)


def _fail(reason_code: str, path: str = "") -> NoReturn:
    raise CrossRepoError(reason_code, path)


def _canonical(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        _fail("manifest_not_json")
    if len(encoded) > MAX_BYTES:
        _fail("manifest_size_limit")
    return encoded


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: object, reason: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(reason, path)
    return value


def _sha(value: object, reason: str, path: str, *, length: int) -> str:
    result = _text(value, reason, path)
    if length == 64:
        result = result.removeprefix("sha256:")
    pattern = _SHA40 if length == 40 else _SHA64
    if not pattern.fullmatch(result):
        _fail(reason, path)
    return result


def _list(value: object, reason: str, path: str, *, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        _fail(reason, path)
    return value


def _repository(value: object, path: str) -> str:
    repository = _text(value, "repository_invalid", path)
    owner, separator, name = repository.partition("/")
    if (
        not separator
        or owner != "wesleysimplicio"
        or name not in REPOSITORY_NAMES
    ):
        _fail("repository_invalid", path)
    return repository


@dataclass(frozen=True, slots=True)
class LockedMember:
    repository: str
    commit: str
    version: str
    artifact_digest: str | None = None
    optional: bool = False

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], index: int) -> LockedMember:
        path = f"members[{index}]"
        if not isinstance(value, Mapping):
            _fail("member_invalid", path)
        repository = _repository(value.get("repository"), f"{path}.repository")
        commit = _sha(value.get("commit"), "member_commit_unpinned", f"{path}.commit", length=40)
        version = _text(value.get("version"), "member_version_invalid", f"{path}.version")
        artifact = value.get("artifact_digest")
        artifact_digest = None
        if artifact is not None:
            artifact_digest = _sha(artifact, "member_artifact_digest_invalid", f"{path}.artifact_digest", length=64)
            artifact_digest = "sha256:" + artifact.removeprefix("sha256:")
        optional = value.get("optional", False)
        if not isinstance(optional, bool):
            _fail("member_optional_invalid", f"{path}.optional")
        return cls(repository, commit, version, artifact_digest, optional)


@dataclass(frozen=True, slots=True)
class LockedContract:
    schema: str
    owner: str
    producer: str
    consumers: tuple[str, ...]
    digest: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], index: int) -> LockedContract:
        path = f"contracts[{index}]"
        if not isinstance(value, Mapping):
            _fail("contract_invalid", path)
        schema = _text(value.get("schema"), "contract_schema_invalid", f"{path}.schema")
        owner = _repository(value.get("owner"), f"{path}.owner")
        producer = _repository(value.get("producer"), f"{path}.producer")
        consumers_value = _list(value.get("consumers"), "contract_consumers_invalid", f"{path}.consumers", maximum=MAX_MEMBERS)
        consumers = tuple(sorted({_repository(item, f"{path}.consumers[{i}]") for i, item in enumerate(consumers_value)}))
        if not consumers:
            _fail("contract_consumers_empty", f"{path}.consumers")
        digest = _sha(value.get("digest"), "contract_digest_invalid", f"{path}.digest", length=64)
        return cls(schema, owner, producer, consumers, "sha256:" + digest.removeprefix("sha256:"))


def _member_dict(member: LockedMember) -> dict[str, Any]:
    result: dict[str, Any] = {
        "repository": member.repository,
        "commit": member.commit,
        "version": member.version,
        "optional": member.optional,
    }
    if member.artifact_digest is not None:
        result["artifact_digest"] = member.artifact_digest
    return result


def _contract_dict(contract: LockedContract) -> dict[str, Any]:
    return {
        "schema": contract.schema,
        "owner": contract.owner,
        "producer": contract.producer,
        "consumers": list(contract.consumers),
        "digest": contract.digest,
    }


def _validate_routes(value: object, repositories: set[str]) -> list[dict[str, str]]:
    routes = _list(value, "routes_invalid", "routes", maximum=MAX_ROUTES)
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(routes):
        path = f"routes[{index}]"
        if not isinstance(item, Mapping):
            _fail("route_invalid", path)
        source = _repository(item.get("source"), f"{path}.source")
        target = _repository(item.get("target"), f"{path}.target")
        kind = _text(item.get("kind"), "route_kind_invalid", f"{path}.kind")
        authority = _text(item.get("authority"), "route_authority_invalid", f"{path}.authority")
        if source not in repositories or target not in repositories:
            _fail("route_member_missing", path)
        expected_owner = _AUTHORITY_OWNERS.get(authority)
        if expected_owner is not None and target != expected_owner:
            _fail("authority_owner_invalid", path)
        normalized.append({"source": source, "target": target, "kind": kind, "authority": authority})
    if len(normalized) != len({tuple(item.items()) for item in normalized}):
        _fail("duplicate_route", "routes")
    return sorted(normalized, key=lambda item: tuple(item.values()))


def validate_stack_lock(payload: Mapping[str, Any], *, profile: str | None = None) -> dict[str, Any]:
    """Validate a pinned stack lock and return a deterministic Fast receipt."""
    if not isinstance(payload, Mapping):
        _fail("manifest_invalid")
    if payload.get("schema") != STACK_LOCK_SCHEMA:
        _fail("stack_lock_schema_invalid", "schema")
    lock_profile = _text(payload.get("profile"), "profile_invalid", "profile")
    if lock_profile not in _PROFILES:
        _fail("profile_invalid", "profile")
    if profile is not None and profile != lock_profile:
        _fail("profile_mismatch", "profile")

    member_values = _list(payload.get("members"), "members_invalid", "members", maximum=MAX_MEMBERS)
    if not member_values:
        _fail("members_empty", "members")
    members = tuple(LockedMember.from_dict(value, index) for index, value in enumerate(member_values))
    repositories = {member.repository for member in members if not member.optional}
    missing = BASE_REQUIRED_REPOSITORIES - repositories
    if missing:
        _fail("required_member_missing", ",".join(sorted(missing)))
    if lock_profile == "runtime-backed" and RUNTIME_REPOSITORY not in repositories:
        _fail("runtime_member_required", "members")
    if lock_profile == "loop-standalone" and RUNTIME_REPOSITORY in repositories:
        _fail("runtime_route_forbidden", "members")
    if len(repositories) != len([member.repository for member in members if not member.optional]):
        _fail("duplicate_member_repository", "members")

    contract_values = _list(payload.get("contracts"), "contracts_invalid", "contracts", maximum=MAX_CONTRACTS)
    contracts = tuple(LockedContract.from_dict(value, index) for index, value in enumerate(contract_values))
    if len({contract.schema for contract in contracts}) != len(contracts):
        _fail("duplicate_contract_schema", "contracts")
    for index, contract in enumerate(contracts):
        participants = {contract.owner, contract.producer, *contract.consumers}
        if not participants <= {member.repository for member in members}:
            _fail("contract_member_missing", f"contracts[{index}]")

    routes = _validate_routes(payload.get("routes"), {member.repository for member in members})
    required_contracts = _list(payload.get("required_contracts"), "required_contracts_invalid", "required_contracts", maximum=MAX_CONTRACTS)
    required_contracts = [_text(item, "required_contract_invalid", f"required_contracts[{i}]") for i, item in enumerate(required_contracts)]
    available_contracts = {contract.schema for contract in contracts}
    missing_contracts = sorted(set(required_contracts) - available_contracts)
    if missing_contracts:
        _fail("required_contract_missing", ",".join(missing_contracts))

    canonical = {
        "schema": STACK_LOCK_SCHEMA,
        "profile": lock_profile,
        "members": [_member_dict(member) for member in sorted(members, key=lambda item: item.repository)],
        "contracts": [_contract_dict(contract) for contract in sorted(contracts, key=lambda item: item.schema)],
        "routes": routes,
        "required_contracts": sorted(set(required_contracts)),
    }
    lock_digest = _digest(canonical)
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "ready",
        "profile": lock_profile,
        "stack_lock_digest": lock_digest,
        "members": canonical["members"],
        "contracts": canonical["contracts"],
        "routes": routes,
        "required_contracts": canonical["required_contracts"],
        "evidence": {
            "pinned_commits": True,
            "contract_digests": True,
            "deterministic_canonical_input": True,
            "fast_authority": "derived-projection-and-read-only-compute",
            "source_mutation_owner": "wesleysimplicio/simplicio-dev-cli",
            "attempt_and_completion_owner": "wesleysimplicio/simplicio-loop",
            "effect_and_policy_owner": (
                "wesleysimplicio/simplicio-runtime" if lock_profile == "runtime-backed" else None
            ),
        },
    }


def load_stack_lock(raw: str | bytes) -> dict[str, Any]:
    """Parse JSON without accepting NaN/Infinity or trailing documents."""
    try:
        value = json.loads(raw, parse_constant=lambda constant: (_ for _ in ()).throw(ValueError(constant)))
    except (TypeError, ValueError, json.JSONDecodeError):
        _fail("manifest_json_invalid")
    if not isinstance(value, Mapping):
        _fail("manifest_invalid")
    return dict(value)


def receipt_json(receipt: Mapping[str, Any]) -> str:
    """Serialize a receipt using the same bytes used for its digest inputs."""
    return _canonical(receipt).decode("utf-8") + "\n"


__all__ = [
    "BASE_REQUIRED_REPOSITORIES",
    "RECEIPT_SCHEMA",
    "RUNTIME_REPOSITORY",
    "STACK_LOCK_SCHEMA",
    "CrossRepoError",
    "load_stack_lock",
    "receipt_json",
    "validate_stack_lock",
]
