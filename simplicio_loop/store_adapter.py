"""Evidence-gated Loop storage routing for MapperStore/v1 (#1025).

This module owns route selection only.  Loop remains the authority for DAGs,
readiness, retries and completion; MapperStore is a persistence provider.  A
probe imports the installed Mapper package and inspects metadata without
creating a directory, database, lock or receipt.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import platform
import re
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any

ADAPTER_SCHEMA = "simplicio.loop-store-adapter/v1"
ROUTE_RECEIPT_SCHEMA = "simplicio.loop-store-route-receipt/v1"
CAPABILITY_SCHEMA = "simplicio.mapper-store-capability/v1"
MAPPER_MIN_VERSION = (0, 26, 1)
REQUIRED_MAPPER_EXPORTS = ("OperationsStore", "inspect_store", "resolve_store_location")
_MAPPER_VERSION_RE = re.compile(r"^\d+(?:\.\d+)*$")


class StoreAdapterError(ValueError):
    """Fail-closed route or capability error."""


class StorageRoute(StrEnum):
    LEGACY = "legacy"
    SHADOW = "shadow"
    MAPPER = "mapper"


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _version_tuple(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not _MAPPER_VERSION_RE.fullmatch(value):
        return ()
    try:
        return tuple(int(part) for part in value.split("."))
    except (AttributeError, ValueError):
        return ()


def _mapper_version(module: Any) -> str | None:
    package = sys.modules.get("simplicio_mapper")
    if package is not None and hasattr(package, "__version__"):
        value = getattr(package, "__version__")
        return None if value is None else str(value)
    try:
        from importlib.metadata import version

        return version("simplicio-mapper")
    except (ImportError, PackageNotFoundError, TypeError, ValueError):  # pragma: no cover
        return None


def _version_failure(version: str | None) -> str | None:
    if version is None or version == "":
        return "MAPPER_VERSION_UNAVAILABLE"
    if not _version_tuple(version):
        return "MAPPER_VERSION_INVALID"
    return None


def _data_dir(value: str | os.PathLike[str] | None) -> Path | None:
    if value is None:
        return None
    target = Path(value).expanduser().absolute()
    if target == Path(target.anchor):
        raise StoreAdapterError("store data directory cannot be filesystem root")
    return target


@dataclass(frozen=True)
class CapabilityReport:
    """Machine-readable, side-effect-free Mapper capability result."""

    status: str
    reason_code: str
    mapper_version: str | None
    exports: tuple[str, ...]
    capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    data_dir: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": CAPABILITY_SCHEMA,
            "status": self.status,
            "reason_code": self.reason_code,
            "mapper_version": self.mapper_version,
            "exports": list(self.exports),
            "capabilities": list(self.capabilities),
            "missing_capabilities": list(self.missing_capabilities),
            "data_dir": self.data_dir,
        }


def probe_mapper(
    *,
    data_dir: str | os.PathLike[str] | None = None,
    required_capabilities: tuple[str, ...] = (),
    module_name: str = "simplicio_mapper.store",
) -> CapabilityReport:
    """Probe the installed Mapper API without touching its filesystem state."""

    target = _data_dir(data_dir)
    try:
        package_name = module_name.split(".", 1)[0]
        importlib.import_module(package_name)
    except (ImportError, ModuleNotFoundError):
        return CapabilityReport(
            "unavailable",
            "MAPPER_NOT_INSTALLED",
            None,
            (),
            (),
            tuple(sorted(required_capabilities)),
            str(target) if target else None,
        )
    try:
        module = importlib.import_module(module_name)
    except (ImportError, ModuleNotFoundError):
        return CapabilityReport(
            "incompatible",
            "MAPPER_API_INCOMPATIBLE",
            _mapper_version(None),
            (),
            (),
            tuple(sorted(required_capabilities)),
            str(target) if target else None,
        )
    version = _mapper_version(module)
    exports = tuple(
        sorted(name for name in REQUIRED_MAPPER_EXPORTS if hasattr(module, name))
    )
    missing_exports = tuple(
        name for name in REQUIRED_MAPPER_EXPORTS if name not in exports
    )
    capabilities = (
        {"mapper-store-api", "sqlite", "read-only-probe"}
        if not missing_exports
        else set()
    )
    missing = set(required_capabilities) - capabilities
    if missing_exports:
        return CapabilityReport(
            "incompatible",
            "MAPPER_API_INCOMPATIBLE",
            version,
            exports,
            tuple(sorted(capabilities)),
            tuple(sorted(missing | set(missing_exports))),
            str(target) if target else None,
        )
    version_failure = _version_failure(version)
    if version_failure is not None:
        return CapabilityReport(
            "incompatible",
            version_failure,
            version,
            exports,
            tuple(sorted(capabilities)),
            tuple(sorted(missing)),
            str(target) if target else None,
        )
    if _version_tuple(version) < MAPPER_MIN_VERSION:
        return CapabilityReport(
            "incompatible",
            "MAPPER_VERSION_TOO_OLD",
            version,
            exports,
            tuple(sorted(capabilities)),
            tuple(sorted(missing)),
            str(target) if target else None,
        )
    if missing:
        return CapabilityReport(
            "partial",
            "MAPPER_CAPABILITY_MISSING",
            version,
            exports,
            tuple(sorted(capabilities)),
            tuple(sorted(missing)),
            str(target) if target else None,
        )
    return CapabilityReport(
        "available",
        "MAPPER_CAPABILITY_VERIFIED",
        version,
        exports,
        tuple(sorted(capabilities)),
        (),
        str(target) if target else None,
    )


class StoreAdapter:
    """Small adapter boundary; domain-specific Loop stores remain unchanged."""

    route: StorageRoute

    def probe(self) -> CapabilityReport:
        raise NotImplementedError


class LegacyLoopStoreAdapter(StoreAdapter):
    route = StorageRoute.LEGACY

    def probe(self) -> CapabilityReport:
        return CapabilityReport(
            "available",
            "LEGACY_ROUTE_DEFAULT",
            None,
            (),
            ("legacy-loop-storage",),
            (),
            None,
        )


class MapperStoreAdapter(StoreAdapter):
    route = StorageRoute.MAPPER

    def __init__(
        self,
        *,
        data_dir: str | os.PathLike[str] | None = None,
        required_capabilities: tuple[str, ...] = (),
    ):
        self.data_dir = _data_dir(data_dir)
        self.required_capabilities = tuple(required_capabilities)

    def probe(self) -> CapabilityReport:
        return probe_mapper(
            data_dir=self.data_dir, required_capabilities=self.required_capabilities
        )


class StorageRouter:
    """Select and freeze a route before the first write, claim or effect intent."""

    def __init__(
        self,
        *,
        requested: StorageRoute | str = StorageRoute.MAPPER,
        mapper: MapperStoreAdapter | None = None,
        run_id: str | None = None,
        generation: str | None = None,
    ):
        try:
            self.requested = StorageRoute(requested)
        except ValueError as error:
            raise StoreAdapterError("STORAGE_ROUTE_INVALID") from error
        self.mapper = mapper or MapperStoreAdapter()
        self.run_id = run_id or str(uuid.uuid4())
        self.generation = generation or str(uuid.uuid4())
        self.selected: StorageRoute | None = None
        self.frozen = False
        self.freeze_reason: str | None = None

    def select(self) -> dict[str, Any]:
        if self.selected is not None:
            return self.status()
        if self.requested == StorageRoute.LEGACY:
            self.selected = StorageRoute.LEGACY
            reason = "LEGACY_ROUTE_EXPLICIT"
        else:
            report = self.mapper.probe()
            if report.status != "available":
                self.selected = None
                return self._blocked(report.reason_code, report)
            self.selected = self.requested
            reason = "MAPPER_ROUTE_CAPABILITY_VERIFIED"
        return self.status(reason_code=reason)

    def _blocked(self, reason_code: str, report: CapabilityReport) -> dict[str, Any]:
        return {
            "schema": ADAPTER_SCHEMA,
            "status": "BLOCKED",
            "reason_code": reason_code,
            "requested": self.requested.value,
            "selected": None,
            "route": None,
            "generation": self.generation,
            "run_id": self.run_id,
            "writer_authority": None,
            "capability": report.as_dict(),
            "frozen": self.frozen,
        }

    def freeze(self, reason: str = "first_write") -> dict[str, Any]:
        if self.selected is None:
            result = self.select()
            if result.get("status") == "BLOCKED":
                raise StoreAdapterError(result["reason_code"])
        self.frozen = True
        self.freeze_reason = reason
        return self.status(reason_code="ROUTE_FROZEN")

    def select_again(self, requested: StorageRoute | str) -> dict[str, Any]:
        try:
            candidate = StorageRoute(requested)
        except ValueError as error:
            raise StoreAdapterError("STORAGE_ROUTE_INVALID") from error
        if self.frozen and candidate != self.selected:
            raise StoreAdapterError("ROUTE_FROZEN_AFTER_FIRST_WRITE")
        self.requested = candidate
        self.selected = None
        return self.select()

    def status(self, *, reason_code: str | None = None) -> dict[str, Any]:
        selected = self.selected.value if self.selected else None
        return {
            "schema": ADAPTER_SCHEMA,
            "status": "READY" if selected else "BLOCKED",
            "reason_code": reason_code
            or ("ROUTE_SELECTED" if selected else "ROUTE_NOT_SELECTED"),
            "requested": self.requested.value,
            "selected": selected,
            "route": selected,
            "generation": self.generation,
            "run_id": self.run_id,
            "writer_authority": "loop"
            if selected == StorageRoute.LEGACY.value
            else "mapper-store"
            if selected
            else None,
            "frozen": self.frozen,
            "freeze_reason": self.freeze_reason,
            "capability": self.mapper.probe().as_dict()
            if self.requested != StorageRoute.LEGACY
            else None,
        }

    def receipt(self) -> dict[str, Any]:
        status = self.status()
        record = {**status, "schema": ROUTE_RECEIPT_SCHEMA, "immutable": self.frozen}
        record["receipt_hash"] = _sha(
            {key: value for key, value in record.items() if key != "receipt_hash"}
        )
        return record


def storage_doctor(
    *,
    requested: StorageRoute | str = StorageRoute.MAPPER,
    data_dir: str | os.PathLike[str] | None = None,
    required_capabilities: tuple[str, ...] = (),
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return a JSON-safe route/capability report; never creates storage."""

    router = StorageRouter(
        requested=requested,
        mapper=MapperStoreAdapter(
            data_dir=data_dir, required_capabilities=required_capabilities
        ),
    )
    result = router.select()
    result.update(
        {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "effects_attempted": False,
        }
    )
    if repo_root is not None:
        from .storage_cutover import inspect_storage_cutover

        result["cutover"] = inspect_storage_cutover(repo_root)
    return result


def storage_cli(argv: list[str]) -> int:
    """CLI used by ``simplicio-loop doctor/inspect --storage``."""

    import argparse

    parser = argparse.ArgumentParser(prog="simplicio-loop storage")
    parser.add_argument(
        "--route", choices=[route.value for route in StorageRoute], default="legacy"
    )
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--repo", default=None)
    parser.add_argument("--require-capability", action="append", default=[])
    args = parser.parse_args(argv)
    result = storage_doctor(
        requested=args.route,
        data_dir=args.data_dir,
        required_capabilities=tuple(args.require_capability),
        repo_root=args.repo,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "READY" else 2


def verify_route_receipt(
    receipt: Mapping[str, Any],
    *,
    requested: StorageRoute | str | None = None,
    require_frozen: bool = True,
    probe_capability: bool = True,
) -> dict[str, Any]:
    """Validate a persisted route decision without creating storage.

    A receipt is an execution input, not merely a status message.  Its hash,
    selected route and capability snapshot must remain stable between bootstrap
    and the first claim/effect boundary.  The optional capability probe is
    read-only and is intentionally skipped for the legacy route.
    """

    if not isinstance(receipt, Mapping):
        raise StoreAdapterError("ROUTE_RECEIPT_INVALID")
    if receipt.get("schema") != ROUTE_RECEIPT_SCHEMA:
        raise StoreAdapterError("ROUTE_RECEIPT_SCHEMA_INVALID")
    try:
        requested_route = StorageRoute(str(receipt.get("requested")))
    except ValueError as error:
        raise StoreAdapterError("ROUTE_RECEIPT_INVALID") from error
    selected_value = receipt.get("selected")
    try:
        selected_route = StorageRoute(str(selected_value)) if selected_value is not None else None
    except ValueError as error:
        raise StoreAdapterError("ROUTE_RECEIPT_INVALID") from error
    if receipt.get("route") != selected_value:
        raise StoreAdapterError("ROUTE_RECEIPT_ROUTE_MISMATCH")
    if receipt.get("status") == "READY" and selected_route is None:
        raise StoreAdapterError("ROUTE_RECEIPT_INVALID")
    if receipt.get("status") == "BLOCKED" and selected_route is not None:
        raise StoreAdapterError("ROUTE_RECEIPT_INVALID")
    if receipt.get("status") not in {"READY", "BLOCKED"}:
        raise StoreAdapterError("ROUTE_RECEIPT_INVALID")
    if not isinstance(receipt.get("generation"), str) or not receipt["generation"].strip():
        raise StoreAdapterError("ROUTE_RECEIPT_INVALID")
    if not isinstance(receipt.get("run_id"), str) or not receipt["run_id"].strip():
        raise StoreAdapterError("ROUTE_RECEIPT_INVALID")
    supplied_hash = str(receipt.get("receipt_hash") or "")
    if supplied_hash != _sha({key: value for key, value in receipt.items() if key != "receipt_hash"}):
        raise StoreAdapterError("ROUTE_RECEIPT_HASH_INVALID")
    if require_frozen and (
        receipt.get("status") != "READY"
        or receipt.get("frozen") is not True
        or receipt.get("immutable") is not True
    ):
        raise StoreAdapterError("ROUTE_NOT_FROZEN")
    if requested is not None:
        try:
            current_route = StorageRoute(requested)
        except ValueError as error:
            raise StoreAdapterError("STORAGE_ROUTE_INVALID") from error
        if current_route != requested_route or (
            selected_route is not None and current_route != selected_route
        ):
            raise StoreAdapterError("ROUTE_FROZEN_AFTER_FIRST_WRITE")
    if selected_route in {StorageRoute.MAPPER, StorageRoute.SHADOW} and probe_capability:
        capability = receipt.get("capability")
        if not isinstance(capability, Mapping):
            raise StoreAdapterError("ROUTE_CAPABILITY_RECEIPT_MISSING")
        current = probe_mapper()
        if current.status != "available":
            raise StoreAdapterError(current.reason_code)
        fields = ("status", "reason_code", "mapper_version", "exports", "capabilities", "missing_capabilities")
        if any(capability.get(field) != current.as_dict().get(field) for field in fields):
            raise StoreAdapterError("MAPPER_CAPABILITY_DRIFT")
    return dict(receipt)


__all__ = [
    "ADAPTER_SCHEMA",
    "CAPABILITY_SCHEMA",
    "MAPPER_MIN_VERSION",
    "ROUTE_RECEIPT_SCHEMA",
    "CapabilityReport",
    "LegacyLoopStoreAdapter",
    "MapperStoreAdapter",
    "StorageRoute",
    "StorageRouter",
    "StoreAdapterError",
    "probe_mapper",
    "storage_cli",
    "storage_doctor",
    "verify_route_receipt",
]
