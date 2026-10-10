"""Contract of the review gate: one CheckResult per check, one GateReport per PR."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

SCHEMA = "simplicio.review-gate/v1"
PASS, FAIL, ERROR, SKIPPED = "pass", "fail", "error", "skipped"
STATUSES = (PASS, FAIL, ERROR, SKIPPED)


class Level(str, Enum):
    """T0 small docs/tests, T1 ordinary code, T2 security (needs an independent reviewer, never only the gate)."""
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"

    @property
    def number(self) -> int:
        return int(self.value[1])


@dataclass(frozen=True)
class CheckResult:
    """`error` is a check that could not run (its cause is in `reasons`); it blocks like `fail`. `skipped` is a
    check that does not apply (say why in `reasons`), and it never blocks."""
    name: str
    status: str
    reasons: tuple[str, ...] = ()
    measured: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown check status {self.status!r}")
        if self.status in (FAIL, ERROR) and not self.reasons:
            raise ValueError(f"check {self.name} {self.status} without a reason")

    @property
    def blocking(self) -> bool:
        return self.status in (FAIL, ERROR)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "reasons": list(self.reasons), "measured": dict(self.measured)}


@dataclass(frozen=True)
class GateReport:
    pr: int
    issue: int | None
    head: str
    level: Level
    checks: tuple[CheckResult, ...]
    partial: bool = False  # criteria of the issue left uncovered: the PR may say "Parte de #N", never close it
    elapsed_s: float = 0.0

    @property
    def blockers(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if c.blocking)

    @property
    def approved(self) -> bool:
        return bool(self.checks) and not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "pr": self.pr, "issue": self.issue, "head": self.head, "level": self.level.value,
                "approved": self.approved, "partial": self.partial, "elapsed_s": round(self.elapsed_s, 3),
                "checks": [c.to_dict() for c in self.checks]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
