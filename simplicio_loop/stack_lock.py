"""Deterministic installed-stack lock and route freeze for issue #1032.

The caller supplies version/capability observations from the installed
operators. This module canonicalizes them, hashes executable artifacts when
available, and freezes the selected route before an effect. It never installs,
updates, or launches a component.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

STACK_LOCK_SCHEMA = "simplicio.stack-lock/v1"
STACK_REGISTRY_SCHEMA = "simplicio.stack-registry/v1"
STACK_DIAGNOSTICS_SCHEMA = "simplicio.stack-diagnostics/v1"
ROUTES = frozenset({"standalone"})
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


class StackLockError(ValueError):
    """Raised when a stack lock is invalid or drifted after freeze."""


@dataclass(frozen=True)
class StackRegistryEntry:
    """One installed component contract in the local compatibility registry."""

    name: str
    version_range: str = "*"
    required_capabilities: tuple[str, ...] = ()
    routes: tuple[str, ...] = tuple(sorted(ROUTES))
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version_range": self.version_range,
            "required_capabilities": list(self.required_capabilities),
            "routes": list(self.routes),
            "required": self.required,
        }


@dataclass(frozen=True)
class StackCompatibilityRule:
    """A producer/consumer row in the installed-stack compatibility matrix."""

    producer: str
    consumer: str
    producer_range: str = "*"
    consumer_range: str = "*"
    required_capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "producer": self.producer,
            "consumer": self.consumer,
            "producer_range": self.producer_range,
            "consumer_range": self.consumer_range,
            "required_capabilities": list(self.required_capabilities),
        }


@dataclass(frozen=True)
class StackUpgradeGroup:
    """Components that must move together when a lock is upgraded."""

    name: str
    components: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "components": list(self.components)}


@dataclass(frozen=True)
class StackCompatibilityRegistry:
    """Immutable, dependency-free registry used by stack diagnostics."""

    generation: str
    components: tuple[StackRegistryEntry, ...]
    compatibility: tuple[StackCompatibilityRule, ...] = ()
    upgrade_groups: tuple[StackUpgradeGroup, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StackCompatibilityRegistry:
        if payload.get("schema") != STACK_REGISTRY_SCHEMA:
            raise StackLockError("invalid stack registry: schema_mismatch")
        generation = str(payload.get("generation") or "").strip()
        if not generation:
            raise StackLockError("invalid stack registry: generation_missing")

        raw_components = payload.get("components")
        if not isinstance(raw_components, list) or not raw_components:
            raise StackLockError("invalid stack registry: components_missing")
        components: list[StackRegistryEntry] = []
        names: set[str] = set()
        for index, raw in enumerate(raw_components):
            if not isinstance(raw, Mapping):
                raise StackLockError(f"invalid stack registry: component_{index}_invalid")
            name = str(raw.get("name") or "").strip()
            if not name or name in names:
                raise StackLockError(f"invalid stack registry: duplicate_component_{name or index}")
            routes = _normalize_routes(raw.get("routes", tuple(sorted(ROUTES))))
            version_range = str(raw.get("version_range") or "*").strip()
            _validate_version_range(version_range)
            required_capabilities = _normalize_strings(raw.get("required_capabilities", ()))
            components.append(StackRegistryEntry(
                name=name,
                version_range=version_range,
                required_capabilities=required_capabilities,
                routes=routes,
                required=bool(raw.get("required", True)),
            ))
            names.add(name)

        raw_rules = payload.get("compatibility", [])
        if not isinstance(raw_rules, list):
            raise StackLockError("invalid stack registry: compatibility_invalid")
        compatibility: list[StackCompatibilityRule] = []
        for index, raw in enumerate(raw_rules):
            if not isinstance(raw, Mapping):
                raise StackLockError(f"invalid stack registry: compatibility_{index}_invalid")
            producer = str(raw.get("producer") or "").strip()
            consumer = str(raw.get("consumer") or "").strip()
            if producer not in names or consumer not in names or producer == consumer:
                raise StackLockError(f"invalid stack registry: compatibility_{index}_endpoint")
            producer_range = str(raw.get("producer_range") or "*").strip()
            consumer_range = str(raw.get("consumer_range") or "*").strip()
            _validate_version_range(producer_range)
            _validate_version_range(consumer_range)
            compatibility.append(StackCompatibilityRule(
                producer=producer,
                consumer=consumer,
                producer_range=producer_range,
                consumer_range=consumer_range,
                required_capabilities=_normalize_strings(raw.get("required_capabilities", ())),
            ))

        raw_groups = payload.get("upgrade_groups", [])
        if not isinstance(raw_groups, list):
            raise StackLockError("invalid stack registry: upgrade_groups_invalid")
        upgrade_groups: list[StackUpgradeGroup] = []
        group_names: set[str] = set()
        for index, raw in enumerate(raw_groups):
            if not isinstance(raw, Mapping):
                raise StackLockError(f"invalid stack registry: upgrade_group_{index}_invalid")
            group_name = str(raw.get("name") or "").strip()
            members = _normalize_strings(raw.get("components", ()))
            if not group_name or group_name in group_names or not members or any(member not in names for member in members):
                raise StackLockError(f"invalid stack registry: upgrade_group_{index}_members")
            upgrade_groups.append(StackUpgradeGroup(group_name, members))
            group_names.add(group_name)

        return cls(generation, tuple(components), tuple(compatibility), tuple(upgrade_groups))

    @classmethod
    def from_json(cls, path: str | Path) -> StackCompatibilityRegistry:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StackLockError(f"cannot read stack registry: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise StackLockError("invalid stack registry: root_not_object")
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": STACK_REGISTRY_SCHEMA,
            "generation": self.generation,
            "components": [entry.to_dict() for entry in self.components],
            "compatibility": [rule.to_dict() for rule in self.compatibility],
            "upgrade_groups": [group.to_dict() for group in self.upgrade_groups],
        }

    @property
    def registry_hash(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    def entry(self, name: str) -> StackRegistryEntry | None:
        return next((entry for entry in self.components if entry.name == name), None)


def load_stack_registry(path: str | Path) -> StackCompatibilityRegistry:
    """Load a local JSON compatibility registry without side effects."""
    return StackCompatibilityRegistry.from_json(path)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _normalize_strings(values: Any) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    if not isinstance(values, Iterable) or isinstance(values, (bytes, bytearray, Mapping)):
        raise StackLockError("registry string list is invalid")
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _normalize_routes(values: Any) -> tuple[str, ...]:
    routes = _normalize_strings(values)
    if not routes or any(route not in ROUTES for route in routes):
        raise StackLockError("registry route is invalid")
    return routes


def _parse_stack_version(value: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.match(str(value).strip())
    if not match:
        raise StackLockError(f"invalid semantic version: {value}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _range_tokens(expression: str) -> tuple[str, ...]:
    return tuple(token.strip() for token in str(expression).split(",") if token.strip())


def _validate_version_range(expression: str) -> None:
    if expression in {"", "*"}:
        return
    for token in _range_tokens(expression):
        if token in {"*", "x", "X"}:
            continue
        if token[0] in {"^", "~"}:
            _parse_stack_version(token[1:])
            continue
        comparator = token[:2] if token[:2] in {">=", "<=", "=="} else token[:1]
        version = token[len(comparator):] if comparator in {">", "<", ">=", "<=", "=="} else token
        _parse_stack_version(version)


def _version_matches(version: str, expression: str) -> bool:
    if expression in {"", "*"}:
        return bool(str(version).strip())
    try:
        actual = _parse_stack_version(version)
    except StackLockError:
        return False
    for token in _range_tokens(expression):
        if token in {"*", "x", "X"}:
            continue
        if token[0] == "^":
            lower = _parse_stack_version(token[1:])
            if lower[0] > 0:
                upper = (lower[0] + 1, 0, 0)
            elif lower[1] > 0:
                upper = (0, lower[1] + 1, 0)
            else:
                upper = (0, 0, lower[2] + 1)
            if not lower <= actual < upper:
                return False
            continue
        if token[0] == "~":
            lower = _parse_stack_version(token[1:])
            upper = (lower[0], lower[1] + 1, 0)
            if not lower <= actual < upper:
                return False
            continue
        comparator = token[:2] if token[:2] in {">=", "<=", "=="} else token[:1]
        if comparator in {">", "<", ">=", "<=", "=="}:
            expected = _parse_stack_version(token[len(comparator):])
        else:
            comparator = "=="
            expected = _parse_stack_version(token)
        if comparator == ">" and not actual > expected:
            return False
        if comparator == ">=" and not actual >= expected:
            return False
        if comparator == "<" and not actual < expected:
            return False
        if comparator == "<=" and not actual <= expected:
            return False
        if comparator == "==" and actual != expected:
            return False
    return True


def _lock_payload(route: str, run_id: str, components: Iterable[StackComponent]) -> dict[str, Any]:
    return {
        "schema": STACK_LOCK_SCHEMA,
        "route": route,
        "run_id": str(run_id),
        "components": [item.to_dict() for item in components],
    }


def _lock_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class StackComponent:
    name: str
    version: str
    executable: str
    build_sha: str
    artifact_sha256: str
    capabilities: tuple[str, ...] = ()
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "executable": self.executable,
            "build_sha": self.build_sha,
            "artifact_sha256": self.artifact_sha256,
            "capabilities": list(self.capabilities),
            "available": self.available,
        }


def observe_component(
    name: str,
    version: str,
    executable: str | Path = "",
    *,
    build_sha: str = "",
    capabilities: Iterable[str] = (),
    artifact_sha256: str | None = None,
) -> StackComponent:
    """Create a component observation without invoking the executable."""
    path = Path(executable) if executable else None
    executable_text = str(path) if path is not None else ""
    artifact = artifact_sha256 or ""
    if not artifact and path is not None and path.is_file():
        artifact = _sha256_file(path)
    available = bool(version and executable_text and artifact)
    return StackComponent(
        name=str(name),
        version=str(version),
        executable=executable_text,
        build_sha=str(build_sha),
        artifact_sha256=artifact,
        capabilities=tuple(sorted({str(value) for value in capabilities if str(value)})),
        available=available,
    )


def observe_components(payload: Mapping[str, Any] | Iterable[Mapping[str, Any]]) -> tuple[StackComponent, ...]:
    """Normalize a JSON observation payload without invoking any component."""
    rows = payload.get("components") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        raise StackLockError("component observations must be a JSON array")
    result: list[StackComponent] = []
    for index, item in enumerate(rows):
        if not isinstance(item, Mapping):
            raise StackLockError(f"component observation {index} is not an object")
        name = str(item.get("name") or "").strip()
        version = str(item.get("version") or "").strip()
        if not name or not version:
            raise StackLockError(f"component observation {index} has no name/version")
        component = observe_component(
            name,
            version,
            str(item.get("executable") or ""),
            build_sha=str(item.get("build_sha") or ""),
            capabilities=item.get("capabilities") or (),
            artifact_sha256=item.get("artifact_sha256"),
        )
        if "available" in item:
            component = replace(component, available=bool(item["available"]))
        result.append(component)
    return tuple(result)


def load_component_observations(path: str | Path) -> tuple[StackComponent, ...]:
    """Load JSON observations for a deterministic, non-executing stack lock."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StackLockError(f"cannot read component observations: {exc}") from exc
    if not isinstance(payload, (Mapping, list)):
        raise StackLockError("component observations root must be an object or array")
    return observe_components(payload)


def _module_artifact(module_name: str) -> str:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return ""
    if spec is None:
        return ""
    origin = str(spec.origin or "")
    if origin and origin not in {"built-in", "frozen"} and Path(origin).is_file():
        return origin
    locations = list(spec.submodule_search_locations or ())
    candidate = Path(locations[0]) / "__init__.py" if locations else None
    return str(candidate) if candidate and candidate.is_file() else ""


def _distribution_version(distribution: str, module_name: str) -> str:
    try:
        return str(importlib.metadata.version(distribution))
    except importlib.metadata.PackageNotFoundError:
        if distribution == "simplicio-loop":
            try:
                from . import __version__

                return str(__version__)
            except (ImportError, AttributeError):
                pass
        module = module_name.rsplit(".", 1)[0] if module_name else ""
        try:
            imported = __import__(module, fromlist=["__version__"])
            return str(getattr(imported, "__version__", ""))
        except (ImportError, AttributeError):
            return ""


def _executable_or_module(executables: Iterable[str], module_name: str) -> str:
    for executable in executables:
        found = shutil.which(executable)
        if found:
            return found
    return _module_artifact(module_name)


def discover_installed_components() -> tuple[StackComponent, ...]:
    """Observe the installed Python stack read-only."""
    override = os.environ.get("SIMPLICIO_STACK_COMPONENTS_FILE", "").strip()
    if override:
        return load_component_observations(override)

    specs = (
        ("simplicio-loop", "simplicio-loop", "simplicio_loop", ("simplicio-loop",),
         ("orchestrator", "stack-lock", "standalone")),
        ("simplicio-mapper", "simplicio-mapper", "simplicio_mapper", ("simplicio-mapper",),
         ("map", "context", "store")),
        ("simplicio-cli", "simplicio-cli", "simplicio", ("simplicio-dev-cli", "simplicio-cli"),
         ("mutation", "verify", "changeset")),
    )
    components = []
    for name, distribution, module_name, executables, capabilities in specs:
        executable = _executable_or_module(executables, module_name)
        components.append(observe_component(
            name,
            _distribution_version(distribution, module_name),
            executable,
            capabilities=capabilities,
        ))

    return tuple(components)


def _validate_route(route: str) -> None:
    if route not in ROUTES:
        raise StackLockError(f"invalid route: {route}")


@dataclass(frozen=True)
class StackLock:
    route: str
    components: tuple[StackComponent, ...]
    lock_hash: str
    run_id: str = ""

    @classmethod
    def create(
        cls,
        components: Iterable[StackComponent],
        route: str,
        *,
        run_id: str = "",
    ) -> StackLock:
        normalized = tuple(sorted(components, key=lambda item: item.name))
        names = [item.name for item in normalized]
        if len(names) != len(set(names)):
            raise StackLockError("duplicate stack component")
        _validate_route(route)
        digest = _lock_hash(_lock_payload(route, str(run_id), normalized))
        return cls(route=route, components=normalized, lock_hash=digest, run_id=str(run_id))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StackLock:
        """Load a lock only when its structure and canonical hash are valid."""
        errors = validate_stack_lock(payload)
        if errors:
            raise StackLockError("invalid stack lock: " + ", ".join(errors))
        components = tuple(_component_from_dict(item) for item in payload["components"])
        _validate_route(str(payload["route"]))
        return cls(
            route=str(payload["route"]),
            components=components,
            lock_hash=str(payload["lock_hash"]),
            run_id=str(payload.get("run_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": STACK_LOCK_SCHEMA,
            "route": self.route,
            "run_id": self.run_id,
            "components": [item.to_dict() for item in self.components],
            "lock_hash": self.lock_hash,
            "frozen": True,
        }

    def verify_unchanged(
        self,
        components: Iterable[StackComponent],
        route: str,
    ) -> None:
        """Fail closed when artifacts, capabilities, or route drift after freeze."""
        current = StackLock.create(components, route, run_id=self.run_id)
        if current.lock_hash != self.lock_hash:
            raise StackLockError(
                f"stack drift after route freeze: expected {self.lock_hash}, found {current.lock_hash}"
            )


@dataclass(frozen=True)
class StackDiagnostic:
    """Stable, actionable finding emitted by :func:`diagnose_stack`."""

    code: str
    severity: str
    message: str
    action: str
    components: tuple[str, ...] = ()
    details: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "action": self.action,
            "components": list(self.components),
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class StackDiagnosis:
    """Read-only compatibility verdict for an observed installed stack."""

    route: str
    registry_generation: str
    registry_hash: str
    issues: tuple[StackDiagnostic, ...] = ()
    lock_hash: str = ""

    @property
    def ready(self) -> bool:
        return not self.issues

    @property
    def status(self) -> str:
        return "READY" if self.ready else "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": STACK_DIAGNOSTICS_SCHEMA,
            "status": self.status,
            "ready": self.ready,
            "route": self.route,
            "registry_generation": self.registry_generation,
            "registry_hash": self.registry_hash,
            "lock_hash": self.lock_hash,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _representative(components: Iterable[StackComponent]) -> StackComponent | None:
    ordered = sorted(
        components,
        key=lambda item: (item.executable, item.version, item.build_sha, item.artifact_sha256),
    )
    return ordered[0] if ordered else None


def _diagnostic(
    code: str,
    message: str,
    action: str,
    components: Iterable[str] = (),
    details: Mapping[str, Any] | None = None,
) -> StackDiagnostic:
    return StackDiagnostic(
        code=code,
        severity="error",
        message=message,
        action=action,
        components=tuple(sorted({str(component) for component in components})),
        details=tuple(sorted((str(key), str(value)) for key, value in (details or {}).items())),
    )


def _lock_changes(
    locked: StackLock,
    current: Mapping[str, tuple[StackComponent, ...]],
) -> tuple[set[str], set[str]]:
    baseline = {component.name: component for component in locked.components}
    names = set(baseline) | set(current)
    changed: set[str] = set()
    unchanged: set[str] = set()
    for name in names:
        candidate = current.get(name, ())
        if len(candidate) == 1 and name in baseline and candidate[0] == baseline[name]:
            unchanged.add(name)
        else:
            changed.add(name)
    return changed, unchanged


def diagnose_stack(
    components: Iterable[StackComponent],
    registry: StackCompatibilityRegistry,
    route: str,
    *,
    locked: StackLock | None = None,
) -> StackDiagnosis:
    """Diagnose compatibility before any run/claim/effect boundary.

    The function only evaluates caller-provided observations. It never invokes
    a binary, consults a service, installs a package, or mutates a lock.
    Duplicate names are retained as observations so a shadowed PATH entry is
    reported instead of being silently selected.
    """
    observed = tuple(components)
    by_name: dict[str, list[StackComponent]] = {}
    for component in observed:
        by_name.setdefault(component.name, []).append(component)

    issues: list[StackDiagnostic] = []
    if route not in ROUTES:
        issues.append(_diagnostic(
            "route_invalid",
            f"route {route!r} is not supported by the Stack Lock",
            "select standalone before creating the lock",
        ))

    registry_names = {entry.name for entry in registry.components}
    for name in sorted(set(by_name) - registry_names):
        paths = tuple(sorted({item.executable for item in by_name[name] if item.executable}))
        issues.append(_diagnostic(
            "unregistered_component",
            f"component {name!r} is not present in registry generation {registry.generation!r}",
            "publish a registry entry with its supported versions, capabilities, and route",
            (name,),
            {"paths": ",".join(paths)},
        ))

    for name in sorted(by_name):
        matches = by_name[name]
        if len(matches) > 1:
            paths = tuple(sorted({item.executable or "<unknown>" for item in matches}))
            issues.append(_diagnostic(
                "duplicate_binary",
                f"multiple installed observations exist for {name!r}: {', '.join(paths)}",
                "remove the shadowed binary or select one immutable path before locking",
                (name,),
                {"paths": ";".join(paths)},
            ))

    for entry in registry.components:
        matches = by_name.get(entry.name, [])
        active = entry.required or route in entry.routes
        if not matches:
            if active:
                issues.append(_diagnostic(
                    "missing_component",
                    f"required component {entry.name!r} is not available for route {route!r}",
                    "install or expose the pinned component, then re-run stack diagnostics",
                    (entry.name,),
                ))
            continue

        if not matches:
            continue
        for component in matches:
            if not component.available:
                issues.append(_diagnostic(
                    "component_unavailable",
                    f"component {entry.name!r} is not available for route {route!r}",
                    "install a readable executable and re-run stack diagnostics",
                    (entry.name,),
                ))
            if not _version_matches(component.version, entry.version_range):
                issues.append(_diagnostic(
                    "version_incompatible",
                    f"component {entry.name!r} version {component.version!r} does not match {entry.version_range!r}",
                    "install a version inside the registry range before locking",
                    (entry.name,),
                    {"actual": component.version, "expected": entry.version_range},
                ))
            missing_capabilities = sorted(
                set(entry.required_capabilities) - set(component.capabilities)
            )
            if missing_capabilities:
                issues.append(_diagnostic(
                    "capability_missing",
                    f"component {entry.name!r} lacks required capabilities: {', '.join(missing_capabilities)}",
                    "publish or install the declared capabilities before locking",
                    (entry.name,),
                    {"missing": ",".join(missing_capabilities)},
                ))
        if active and route not in entry.routes:
            issues.append(_diagnostic(
                "route_incompatible",
                f"component {entry.name!r} is not declared for route {route!r}",
                "select a supported route or update the compatibility registry",
                (entry.name,),
                {"routes": ",".join(entry.routes)},
            ))

    for rule in registry.compatibility:
        producers = by_name.get(rule.producer, [])
        consumers = by_name.get(rule.consumer, [])
        if not producers or not consumers:
            continue
        if len(producers) != 1 or len(consumers) != 1:
            issues.append(_diagnostic(
                "compatibility_mismatch",
                f"compatibility rule {rule.producer!r} -> {rule.consumer!r} is ambiguous",
                "remove duplicate observations before locking",
                (rule.producer, rule.consumer),
            ))
            continue
        producer = producers[0]
        consumer = consumers[0]
        if (
            not _version_matches(producer.version, rule.producer_range)
            or not _version_matches(consumer.version, rule.consumer_range)
            or not set(rule.required_capabilities).issubset(set(producer.capabilities))
        ):
            issues.append(_diagnostic(
                "compatibility_mismatch",
                f"compatibility rule {rule.producer!r} -> {rule.consumer!r} does not match observed versions/capabilities",
                "install compatible producer/consumer artifacts before locking",
                (rule.producer, rule.consumer),
                {
                    "producer_version": producer.version,
                    "consumer_version": consumer.version,
                    "producer_range": rule.producer_range,
                    "consumer_range": rule.consumer_range,
                },
            ))

    if locked is not None:
        current = {name: tuple(items) for name, items in by_name.items()}
        changed, unchanged = _lock_changes(locked, current)
        for group in registry.upgrade_groups:
            members = set(group.components)
            changed_members = sorted(members & changed)
            unchanged_members = sorted(members & unchanged)
            if changed_members and unchanged_members:
                issues.append(_diagnostic(
                    "partial_upgrade",
                    f"upgrade group {group.name!r} is only partially upgraded",
                    "upgrade or roll back the complete group before resuming effects",
                    tuple(members),
                    {
                        "changed": ",".join(changed_members),
                        "unchanged": ",".join(unchanged_members),
                    },
                ))

    return StackDiagnosis(
        route=route,
        registry_generation=registry.generation,
        registry_hash=registry.registry_hash,
        issues=tuple(issues),
        lock_hash=locked.lock_hash if locked is not None else "",
    )



def _component_from_dict(payload: Mapping[str, Any]) -> StackComponent:
    if not isinstance(payload, Mapping):
        raise StackLockError("component observation must be an object")
    required = ("name", "version", "executable", "build_sha", "artifact_sha256")
    missing = [field for field in required if field not in payload]
    if missing:
        raise StackLockError("component fields missing: " + ", ".join(missing))
    capabilities = payload.get("capabilities", ())
    if not isinstance(capabilities, (list, tuple)):
        raise StackLockError("component capabilities must be a list")
    available = payload.get("available", True)
    if not isinstance(available, bool):
        raise StackLockError("component available must be boolean")
    return StackComponent(
        name=str(payload["name"]),
        version=str(payload["version"]),
        executable=str(payload["executable"]),
        build_sha=str(payload["build_sha"]),
        artifact_sha256=str(payload["artifact_sha256"]),
        capabilities=tuple(sorted({str(value) for value in capabilities if str(value)})),
        available=available,
    )


def validate_stack_lock(payload: Any) -> list[str]:
    """Return stable validation codes for a persisted immutable stack lock."""
    if not isinstance(payload, Mapping):
        return ["root_not_object"]
    errors: list[str] = []
    if payload.get("schema") != STACK_LOCK_SCHEMA:
        errors.append("schema_mismatch")
    route = payload.get("route")
    if route not in ROUTES:
        errors.append("route_invalid")
    run_id = payload.get("run_id", "")
    if not isinstance(run_id, str):
        errors.append("run_id_invalid")
        run_id = str(run_id)
    if payload.get("frozen") is not True:
        errors.append("lock_not_frozen")
    raw_components = payload.get("components")
    components: list[StackComponent] = []
    if not isinstance(raw_components, list):
        errors.append("components_invalid")
    else:
        names: set[str] = set()
        for index, raw in enumerate(raw_components):
            try:
                component = _component_from_dict(raw)
            except (TypeError, ValueError, StackLockError):
                errors.append(f"component_{index}_invalid")
                continue
            if not component.name:
                errors.append(f"component_{index}_name_missing")
            if component.name in names:
                errors.append("duplicate_component")
            names.add(component.name)
            components.append(component)
    lock_hash = payload.get("lock_hash")
    if not isinstance(lock_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", lock_hash):
        errors.append("lock_hash_invalid")
    elif not errors and route in ROUTES:
        normalized = tuple(sorted(components, key=lambda item: item.name))
        expected = _lock_hash(_lock_payload(str(route), run_id, normalized))
        if lock_hash != expected:
            errors.append("lock_hash_mismatch")
    return errors


def load_stack_lock(path: str | Path) -> StackLock:
    """Load and validate an immutable stack lock without changing it."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StackLockError(f"cannot read stack lock: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise StackLockError("invalid stack lock: root_not_object")
    return StackLock.from_dict(payload)


def write_stack_lock(lock: StackLock, path: str | Path) -> Path:
    """Persist a lock atomically and reject replacement with a different hash."""
    target = Path(path)
    if target.exists():
        try:
            current = load_stack_lock(target)
        except (OSError, UnicodeError, json.JSONDecodeError, StackLockError) as exc:
            raise StackLockError(f"cannot replace invalid stack lock: {exc}") from exc
        if current.lock_hash != lock.lock_hash:
            raise StackLockError("stack lock already exists with a different hash")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(lock.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


__all__ = [
    "ROUTES",
    "STACK_DIAGNOSTICS_SCHEMA",
    "STACK_LOCK_SCHEMA",
    "STACK_REGISTRY_SCHEMA",
    "StackCompatibilityRegistry",
    "StackCompatibilityRule",
    "StackComponent",
    "StackDiagnostic",
    "StackDiagnosis",
    "StackLock",
    "StackLockError",
    "StackRegistryEntry",
    "StackUpgradeGroup",
    "diagnose_stack",
    "discover_installed_components",
    "load_component_observations",
    "load_stack_lock",
    "load_stack_registry",
    "observe_component",
    "observe_components",
    "validate_stack_lock",
    "write_stack_lock",
]
