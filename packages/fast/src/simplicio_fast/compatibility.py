"""Deterministic compatibility decisions for the embeddable SDK contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


COMPATIBILITY_SCHEMA = "simplicio.fast.sdk-compatibility/v1"
SDK_CONTRACT = "simplicio.fast.sdk/v1"
SDK_CURRENT_VERSION = "1.0"

_VERSION_RE = re.compile(r"^v?(?P<major>[0-9]+)\.(?P<minor>[0-9]+)$")


class CompatibilityError(ValueError):
    """Raised when a version cannot participate in the compatibility contract."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class CompatibilityDecision:
    """The stable, machine-readable result of a version compatibility check."""

    producer_version: str
    consumer_version: str
    action: str
    reason_code: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPATIBILITY_SCHEMA,
            "contract": SDK_CONTRACT,
            "producer_version": self.producer_version,
            "consumer_version": self.consumer_version,
            "action": self.action,
            "reason_code": self.reason_code,
        }


def compatibility_manifest() -> dict[str, Any]:
    """Return the explicit upgrade, downgrade and future-major policy."""
    return {
        "schema": COMPATIBILITY_SCHEMA,
        "contract": SDK_CONTRACT,
        "current_version": SDK_CURRENT_VERSION,
        "rules": {
            "exact": "accept",
            "reader_upgrade_same_major": "accept_legacy_minor",
            "reader_downgrade_same_major": "reject_requires_migration",
            "future_major": "reject",
            "older_major": "reject",
        },
        "rollback": "reuse_only_a_previously_validated_contract_version",
        "reason_codes": [
            "compatibility_exact",
            "compatibility_upgrade_legacy_minor",
            "compatibility_downgrade_requires_migration",
            "compatibility_future_major",
            "compatibility_older_major",
            "compatibility_version_invalid",
        ],
    }


def evaluate_compatibility(
    producer_version: str,
    consumer_version: str = SDK_CURRENT_VERSION,
) -> CompatibilityDecision:
    """Evaluate an artifact version against a reader version.

    A reader may consume an older minor in the same major. A newer artifact
    minor requires an explicit migration and every major mismatch fails closed.
    """
    producer = _parse_version(producer_version)
    consumer = _parse_version(consumer_version)
    if producer is None or consumer is None:
        raise CompatibilityError("compatibility_version_invalid")

    if producer[0] > consumer[0]:
        return CompatibilityDecision(
            producer_version=producer_version,
            consumer_version=consumer_version,
            action="reject",
            reason_code="compatibility_future_major",
        )
    if producer[0] < consumer[0]:
        return CompatibilityDecision(
            producer_version=producer_version,
            consumer_version=consumer_version,
            action="reject",
            reason_code="compatibility_older_major",
        )
    if producer[1] == consumer[1]:
        return CompatibilityDecision(
            producer_version=producer_version,
            consumer_version=consumer_version,
            action="accept",
            reason_code="compatibility_exact",
        )
    if producer[1] < consumer[1]:
        return CompatibilityDecision(
            producer_version=producer_version,
            consumer_version=consumer_version,
            action="accept",
            reason_code="compatibility_upgrade_legacy_minor",
        )
    return CompatibilityDecision(
        producer_version=producer_version,
        consumer_version=consumer_version,
        action="reject",
        reason_code="compatibility_downgrade_requires_migration",
    )


def _parse_version(value: object) -> tuple[int, int] | None:
    if not isinstance(value, str):
        return None
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        return None
    return int(match.group("major")), int(match.group("minor"))


__all__ = [
    "COMPATIBILITY_SCHEMA",
    "SDK_CONTRACT",
    "SDK_CURRENT_VERSION",
    "CompatibilityDecision",
    "CompatibilityError",
    "compatibility_manifest",
    "evaluate_compatibility",
]
