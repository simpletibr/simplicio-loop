"""Deterministic, offline replay of Fast policy decisions.

This module consumes validated Fast-Local telemetry and invokes only
``SpeculationPolicy``.  It never imports Local, model, KV-cache, kernel, or
device-execution code.  The contract decision receipt is a projection of the
Fast result: the contract currently represents non-draft speculative choices
as ``tree``, while the replay metadata retains the exact Fast strategy.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contract_surface import (
    CONTRACT_SCHEMA,
    CONTRACT_VERSION,
    INVALIDATION_TRIGGERS,
    ContractSurfaceError,
    canonical_json,
    digest_for,
    validate_decision_receipt,
    validate_telemetry_snapshot,
)
from .speculation_policy import (
    SPECULATION_POLICY_SCHEMA,
    SpeculationCapabilities,
    SpeculationPolicy,
    SpeculationResult,
    SpeculationStrategy,
    StrategyCapability,
)

POLICY_REPLAY_SCHEMA = "simplicio.fast.policy-replay/v1"
CURRENT_POLICY_VERSION = SPECULATION_POLICY_SCHEMA
_CURRENT_POLICY_ALIASES = frozenset(("current", "v1", CURRENT_POLICY_VERSION))
_CONTRACT_STRATEGY_FOR_POLICY = {
    SpeculationStrategy.BASELINE.value: "disabled",
    SpeculationStrategy.DRAFT.value: "draft_verify",
    SpeculationStrategy.NGRAM.value: "tree",
    SpeculationStrategy.DFLASH.value: "tree",
    SpeculationStrategy.MTP.value: "tree",
}
_POLICY_STRATEGY_FOR_CONTRACT = {
    "disabled": SpeculationStrategy.BASELINE.value,
    "draft_verify": SpeculationStrategy.DRAFT.value,
    "tree": None,
}
_STRATEGY_ALIASES = {
    "ngram": "ngram",
    "n-gram": "ngram",
    "ngram_speculation": "ngram",
    "draft": "draft",
    "draft_verify": "draft",
    "draft-verify": "draft",
    "draftverify": "draft",
    "dflash": "dflash",
    "mtp": "mtp",
}


class PolicyReplayError(ValueError):
    """Stable fail-closed error raised by the replay boundary."""

    def __init__(self, reason_code: str, path: str = "") -> None:
        self.reason_code = reason_code
        self.path = path
        super().__init__(f"{reason_code}:{path}" if path else reason_code)


def _copy_json(value: Any) -> Any:
    try:
        return json.loads(canonical_json(value))
    except ContractSurfaceError as error:
        raise PolicyReplayError(error.reason_code, error.path) from error


def _validate_telemetry(value: object) -> dict[str, Any]:
    try:
        return validate_telemetry_snapshot(value)
    except ContractSurfaceError as error:
        raise PolicyReplayError(error.reason_code, error.path) from error


def _validate_historical(value: object) -> dict[str, Any]:
    try:
        return validate_decision_receipt(value)
    except ContractSurfaceError as error:
        raise PolicyReplayError(error.reason_code, error.path) from error


def _read_document(value: object) -> tuple[Any, str | None]:
    if isinstance(value, (Mapping, list)):
        return _copy_json(value), None

    if isinstance(value, Path):
        source = str(value)
        try:
            text = value.read_text(encoding="utf-8")
        except OSError as error:
            raise PolicyReplayError("snapshot_read_failed", source) from error
    elif isinstance(value, str):
        stripped = value.lstrip()
        if stripped.startswith(("{", "[")):
            text = value
            source = None
        else:
            candidate = Path(value)
            try:
                exists = candidate.is_file()
            except OSError as error:
                raise PolicyReplayError("snapshot_path_invalid", value) from error
            if not exists:
                raise PolicyReplayError("snapshot_path_not_found", value)
            source = str(candidate)
            try:
                text = candidate.read_text(encoding="utf-8")
            except OSError as error:
                raise PolicyReplayError("snapshot_read_failed", source) from error
    else:
        raise PolicyReplayError("snapshot_input_invalid")

    try:
        document = json.loads(text)
    except (TypeError, json.JSONDecodeError) as error:
        raise PolicyReplayError("snapshot_json_invalid", source or "input") from error
    if not isinstance(document, (Mapping, list)):
        raise PolicyReplayError("snapshot_document_invalid", source or "input")
    return _copy_json(document), source


def _record_parts(record: object) -> tuple[object, object | None]:
    if not isinstance(record, Mapping):
        raise PolicyReplayError("snapshot_record_invalid")
    if "telemetry_snapshot" in record:
        telemetry = record["telemetry_snapshot"]
        historical = record.get("historical_decision", record.get("decision_receipt"))
        return telemetry, historical
    if "snapshot" in record:
        telemetry = record["snapshot"]
        historical = record.get("historical_decision", record.get("decision_receipt"))
        return telemetry, historical
    return record, None


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    """A validated telemetry message and its optional historical receipt."""

    telemetry: dict[str, Any]
    historical_decision: dict[str, Any] | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        telemetry = _validate_telemetry(self.telemetry)
        historical = (
            None
            if self.historical_decision is None
            else _validate_historical(self.historical_decision)
        )
        if self.source is not None and (
            not isinstance(self.source, str) or not self.source.strip()
        ):
            raise PolicyReplayError("snapshot_source_invalid")
        object.__setattr__(self, "telemetry", telemetry)
        object.__setattr__(self, "historical_decision", historical)

    @property
    def sample_id(self) -> str:
        return self.telemetry["payload"]["sample_id"]

    @property
    def telemetry_digest(self) -> str:
        return self.telemetry["payload"]["telemetry_digest"]

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"telemetry_snapshot": _copy_json(self.telemetry)}
        if self.historical_decision is not None:
            value["historical_decision"] = _copy_json(self.historical_decision)
        return value


def _make_snapshot(record: object, source: str | None = None) -> ReplaySnapshot:
    telemetry, historical = _record_parts(record)
    return ReplaySnapshot(
        telemetry=_validate_telemetry(telemetry),
        historical_decision=(
            None if historical is None else _validate_historical(historical)
        ),
        source=source,
    )


def load_snapshot(
    value: ReplaySnapshot | Mapping[str, Any] | Path | str,
) -> ReplaySnapshot:
    """Load one contract telemetry snapshot from a mapping, JSON, or path.

    A record may be either the telemetry message itself or a wrapper with
    ``snapshot``/``telemetry_snapshot`` and an optional historical decision
    receipt.  The examples bundle in ``contracts/fast-local/v1/examples.json``
    is accepted as a convenience fixture.
    """

    if isinstance(value, ReplaySnapshot):
        return value
    document, source = _read_document(value)
    if isinstance(document, list):
        raise PolicyReplayError("snapshot_collection_for_single")
    if "snapshots" in document:
        raise PolicyReplayError("snapshot_collection_for_single")
    return _make_snapshot(document, source)


def load_snapshots(
    value: (
        ReplaySnapshot
        | Mapping[str, Any]
        | Path
        | str
        | Iterable[ReplaySnapshot | Mapping[str, Any] | Path | str]
    ),
) -> tuple[ReplaySnapshot, ...]:
    """Load one or many snapshots while preserving input order."""

    if isinstance(value, ReplaySnapshot):
        return (value,)
    if isinstance(value, (Mapping, Path, str)):
        document, source = _read_document(value)
        if isinstance(document, list):
            records = document
        elif "snapshots" in document:
            records = document["snapshots"]
            if not isinstance(records, list):
                raise PolicyReplayError("snapshot_collection_invalid")
        else:
            records = [document]
        return tuple(_make_snapshot(record, source) for record in records)
    try:
        records = tuple(value)
    except TypeError as error:
        raise PolicyReplayError("snapshot_collection_invalid") from error
    return tuple(load_snapshot(record) for record in records)


def capabilities_from_snapshot(
    snapshot: ReplaySnapshot | Mapping[str, Any] | Path | str,
) -> SpeculationCapabilities:
    """Project contract capability details into Fast policy inputs only."""

    loaded = load_snapshot(snapshot)
    capability = loaded.telemetry["payload"]["capabilities"]["speculation"]
    details = capability.get("details", [])
    if capability["status"] != "supported":
        details = []
    supported: dict[str, bool] = {
        name: False for name in ("ngram", "draft", "dflash", "mtp")
    }
    for detail in details:
        normalized = str(detail).strip().lower().replace(" ", "_")
        name = _STRATEGY_ALIASES.get(normalized)
        if name is not None:
            supported[name] = True
    return SpeculationCapabilities(
        ngram=StrategyCapability(supported["ngram"]),
        draft=StrategyCapability(supported["draft"]),
        dflash=StrategyCapability(supported["dflash"]),
        mtp=StrategyCapability(supported["mtp"]),
    )


@dataclass(frozen=True, slots=True)
class ReplaySelection:
    """Selection details with both exact Fast and contract-level names."""

    contract_strategy: str
    policy_strategy: str | None
    reason: str | None = None
    reason_codes: tuple[str, ...] = ()
    confidence: float | None = None

    @property
    def exact_policy_known(self) -> bool:
        return self.policy_strategy is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_strategy": self.contract_strategy,
            "policy_strategy": self.policy_strategy,
            "exact_policy_known": self.exact_policy_known,
            "reason": self.reason,
            "reason_codes": list(self.reason_codes),
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class PolicyReplayDiff:
    """Deterministic comparison of current and historical contract selections."""

    current: ReplaySelection
    historical: ReplaySelection | None
    selection_changed: bool | None
    changes: tuple[dict[str, Any], ...]

    @property
    def changed(self) -> bool | None:
        """Compatibility-friendly alias for selection_changed."""

        return self.selection_changed

    def to_dict(self) -> dict[str, Any]:
        if self.selection_changed is None:
            status = "not_recorded"
        elif self.selection_changed:
            status = "changed"
        else:
            status = "unchanged"
        return {
            "status": status,
            "selection_changed": self.selection_changed,
            "historical_recorded": self.historical is not None,
            "historical": (
                None if self.historical is None else self.historical.to_dict()
            ),
            "current": self.current.to_dict(),
            "changes": [_copy_json(change) for change in self.changes],
        }


@dataclass(frozen=True, slots=True)
class PolicyReplayResult:
    """One offline replay result and its contract-shaped decision receipt."""

    snapshot: ReplaySnapshot
    policy_version: str
    policy_result: SpeculationResult
    decision_receipt: dict[str, Any]
    diff: PolicyReplayDiff
    warnings: tuple[str, ...] = ()

    @property
    def current_selection(self) -> ReplaySelection:
        return self.diff.current

    @property
    def report(self) -> str:
        return format_report(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": POLICY_REPLAY_SCHEMA,
            "policy_version": self.policy_version,
            "snapshot": {
                "source": self.snapshot.source,
                "sample_id": self.snapshot.sample_id,
                "telemetry_digest": self.snapshot.telemetry_digest,
                "generation_id": self.snapshot.telemetry["generation"]["generation_id"],
            },
            "policy": self.policy_result.to_dict(),
            "decision_receipt": _copy_json(self.decision_receipt),
            "diff": self.diff.to_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class PolicyReplayBatch:
    """Ordered replay results plus deterministic regression-suite counts."""

    results: tuple[PolicyReplayResult, ...]
    policy_version: str

    @property
    def summary(self) -> dict[str, Any]:
        changed = sum(result.diff.selection_changed is True for result in self.results)
        unchanged = sum(
            result.diff.selection_changed is False for result in self.results
        )
        unrecorded = sum(
            result.diff.selection_changed is None for result in self.results
        )
        current = Counter(
            result.current_selection.contract_strategy for result in self.results
        )
        historical = Counter(
            result.diff.historical.contract_strategy
            for result in self.results
            if result.diff.historical is not None
        )
        return {
            "total": len(self.results),
            "historical_recorded": len(self.results) - unrecorded,
            "selection_changed": changed,
            "selection_unchanged": unchanged,
            "selection_unrecorded": unrecorded,
            "current_contract_strategies": dict(sorted(current.items())),
            "historical_contract_strategies": dict(sorted(historical.items())),
        }

    @property
    def report(self) -> str:
        return format_report(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": POLICY_REPLAY_SCHEMA,
            "policy_version": self.policy_version,
            "summary": self.summary,
            "results": [result.to_dict() for result in self.results],
        }


def _resolve_policy(
    policy: SpeculationPolicy | None, policy_version: str | None
) -> tuple[SpeculationPolicy, str]:
    version = CURRENT_POLICY_VERSION if policy_version is None else policy_version
    if not isinstance(version, str) or not version.strip():
        raise PolicyReplayError("policy_version_invalid")
    if policy is not None:
        if not isinstance(policy, SpeculationPolicy):
            raise PolicyReplayError("policy_invalid")
        return policy, version
    if version not in _CURRENT_POLICY_ALIASES:
        raise PolicyReplayError("policy_version_unavailable", version)
    return SpeculationPolicy(), CURRENT_POLICY_VERSION


def _selection_from_result(result: SpeculationResult) -> ReplaySelection:
    strategy = result.selected.value
    return ReplaySelection(
        contract_strategy=_CONTRACT_STRATEGY_FOR_POLICY[strategy],
        policy_strategy=strategy,
        reason=result.reason,
        reason_codes=(result.reason,),
        confidence=None,
    )


def _selection_from_historical(
    decision: Mapping[str, Any],
) -> ReplaySelection:
    payload = decision["payload"]
    policy = payload["speculation_policy"]
    contract_strategy = policy["strategy"]
    return ReplaySelection(
        contract_strategy=contract_strategy,
        policy_strategy=_POLICY_STRATEGY_FOR_CONTRACT[contract_strategy],
        reason_codes=tuple(payload["reason_codes"]),
        confidence=payload["confidence"],
    )


def _make_diff(
    current: ReplaySelection, historical: ReplaySelection | None
) -> PolicyReplayDiff:
    if historical is None:
        return PolicyReplayDiff(current, None, None, ())
    changed = historical.contract_strategy != current.contract_strategy
    changes: tuple[dict[str, Any], ...]
    if changed:
        changes = (
            {
                "field": "speculation_policy.strategy",
                "historical": historical.contract_strategy,
                "current": current.contract_strategy,
            },
        )
    else:
        changes = ()
    return PolicyReplayDiff(current, historical, changed, changes)


def _confidence(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise PolicyReplayError("confidence_invalid")
    return float(value)


def _decision_receipt(
    snapshot: ReplaySnapshot,
    policy_result: SpeculationResult,
    policy_version: str,
    confidence: float,
) -> dict[str, Any]:
    telemetry = snapshot.telemetry
    placement = telemetry["payload"]["capabilities"]["placement"]
    details = placement.get("details", [])
    if placement["status"] == "supported" and details:
        target = details[0]
        placement_reason = "capability_supported"
    elif placement["status"] == "supported":
        target = "unspecified"
        placement_reason = "capability_details_missing"
    else:
        target = "unspecified"
        placement_reason = "capability_unavailable"
    reason_codes = sorted(
        {"offline_replay", "policy_replay", policy_result.reason, placement_reason}
    )
    identity = hashlib.sha256(
        canonical_json(
            {
                "sample_id": snapshot.sample_id,
                "telemetry_digest": snapshot.telemetry_digest,
                "policy_version": policy_version,
            }
        )
    ).hexdigest()[:24]
    payload: dict[str, Any] = {
        "decision_id": f"policy-replay-{identity}",
        "source_telemetry_digest": snapshot.telemetry_digest,
        "speculation_policy": {
            "enabled": policy_result.selected is not SpeculationStrategy.BASELINE,
            "strategy": _CONTRACT_STRATEGY_FOR_POLICY[policy_result.selected.value],
        },
        "placement_recommendation": {
            "target": target,
            "reason_code": placement_reason,
        },
        "context_batch_policy": {"batch_size": 1, "ranking": "balanced"},
        "confidence": confidence,
        "reason_codes": reason_codes,
        "invalidation_triggers": list(INVALIDATION_TRIGGERS),
        "unavailable": {},
        "decision_digest": "",
    }
    message: dict[str, Any] = {
        "schema": CONTRACT_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "message_type": "decision_receipt",
        "generation": _copy_json(telemetry["generation"]),
        "payload": payload,
    }
    unsigned = _copy_json(message)
    unsigned["payload"].pop("decision_digest")
    payload["decision_digest"] = digest_for(unsigned)
    try:
        return validate_decision_receipt(message)
    except ContractSurfaceError as error:
        raise PolicyReplayError(error.reason_code, error.path) from error


def _replay_loaded(
    snapshot: ReplaySnapshot,
    policy: SpeculationPolicy,
    policy_version: str,
    confidence: float,
) -> PolicyReplayResult:
    capabilities = capabilities_from_snapshot(snapshot)
    policy_result = policy.decide(capabilities)
    receipt = _decision_receipt(snapshot, policy_result, policy_version, confidence)
    current = _selection_from_result(policy_result)
    historical = (
        None
        if snapshot.historical_decision is None
        else _selection_from_historical(snapshot.historical_decision)
    )
    warnings: list[str] = []
    if historical is not None:
        historical_digest = snapshot.historical_decision["payload"][
            "source_telemetry_digest"
        ]
        if historical_digest != snapshot.telemetry_digest:
            warnings.append("historical_source_digest_differs")
    return PolicyReplayResult(
        snapshot=snapshot,
        policy_version=policy_version,
        policy_result=policy_result,
        decision_receipt=receipt,
        diff=_make_diff(current, historical),
        warnings=tuple(warnings),
    )


def replay_snapshot(
    snapshot: ReplaySnapshot | Mapping[str, Any] | Path | str,
    *,
    policy: SpeculationPolicy | None = None,
    policy_version: str | None = None,
    confidence: float = 1.0,
) -> PolicyReplayResult:
    """Replay one snapshot using the current or explicitly supplied policy."""

    loaded = load_snapshot(snapshot)
    resolved, version = _resolve_policy(policy, policy_version)
    return _replay_loaded(loaded, resolved, version, _confidence(confidence))


def replay_snapshots(
    snapshots: (
        ReplaySnapshot
        | Mapping[str, Any]
        | Path
        | str
        | Iterable[ReplaySnapshot | Mapping[str, Any] | Path | str]
    ),
    *,
    policy: SpeculationPolicy | None = None,
    policy_version: str | None = None,
    confidence: float = 1.0,
) -> PolicyReplayBatch:
    """Replay a deterministic ordered batch of telemetry snapshots."""

    loaded = load_snapshots(snapshots)
    resolved, version = _resolve_policy(policy, policy_version)
    confidence_value = _confidence(confidence)
    return PolicyReplayBatch(
        results=tuple(
            _replay_loaded(item, resolved, version, confidence_value) for item in loaded
        ),
        policy_version=version,
    )


def format_report(value: PolicyReplayResult | PolicyReplayBatch) -> str:
    """Return a stable human-readable report for one replay or a batch."""

    if isinstance(value, PolicyReplayBatch):
        summary = value.summary
        lines = [
            "Policy replay batch",
            f"Policy version: {value.policy_version}",
            f"Snapshots: {summary['total']}",
            f"Selection changed: {summary['selection_changed']}",
            f"Selection unchanged: {summary['selection_unchanged']}",
            f"Historical selection unrecorded: {summary['selection_unrecorded']}",
            "Current contract strategies: "
            + _format_counts(summary["current_contract_strategies"]),
        ]
        changed_samples = [
            result.snapshot.sample_id
            for result in value.results
            if result.diff.selection_changed is True
        ]
        if changed_samples:
            lines.append("Changed samples: " + ", ".join(changed_samples))
        lines.append("No Local/model/KV/kernel execution performed.")
        return "\n".join(lines)

    if not isinstance(value, PolicyReplayResult):
        raise PolicyReplayError("report_input_invalid")
    current = value.diff.current
    historical = value.diff.historical
    if value.diff.selection_changed is None:
        changed = "not recorded"
        historical_line = "not recorded"
    else:
        changed = "yes" if value.diff.selection_changed else "no"
        historical_line = _format_selection(historical)
    lines = [
        "Policy replay",
        f"Sample: {value.snapshot.sample_id}",
        f"Policy version: {value.policy_version}",
        f"Historical selection: {historical_line}",
        f"Current selection: {_format_selection(current)}",
        f"Selection changed: {changed}",
        f"Reason: {value.policy_result.reason}",
        f"Confidence: {value.decision_receipt['payload']['confidence']:.3f}",
        f"Decision digest: {value.decision_receipt['payload']['decision_digest']}",
    ]
    if value.warnings:
        lines.append("Warnings: " + ", ".join(value.warnings))
    lines.append("No Local/model/KV/kernel execution performed.")
    return "\n".join(lines)


def _format_selection(selection: ReplaySelection | None) -> str:
    if selection is None:
        return "not recorded"
    exact = selection.policy_strategy or "unknown Fast strategy"
    return f"{exact} (contract: {selection.contract_strategy})"


def _format_counts(values: Mapping[str, int]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={values[key]}" for key in sorted(values))


# Short aliases keep the public API convenient without adding a CLI surface.
replay = replay_snapshot
replay_batch = replay_snapshots


__all__ = [
    "CURRENT_POLICY_VERSION",
    "POLICY_REPLAY_SCHEMA",
    "PolicyReplayBatch",
    "PolicyReplayDiff",
    "PolicyReplayError",
    "PolicyReplayResult",
    "ReplaySelection",
    "ReplaySnapshot",
    "capabilities_from_snapshot",
    "format_report",
    "load_snapshot",
    "load_snapshots",
    "replay",
    "replay_batch",
    "replay_snapshot",
    "replay_snapshots",
]
