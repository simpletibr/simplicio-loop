"""Explicit memory accounting primitives for bounded Mapper stages."""

from __future__ import annotations

from dataclasses import dataclass


class MemoryBudgetExceeded(RuntimeError):
    """Raised before a stage can exceed its configured hard byte limit."""


@dataclass
class MemoryBudget:
    """Track a stage's live-set budget without pretending to measure RSS."""

    soft_limit_bytes: int
    hard_limit_bytes: int
    current_bytes: int = 0
    peak_bytes: int = 0
    spills: int = 0

    def __post_init__(self) -> None:
        if self.soft_limit_bytes < 0 or self.hard_limit_bytes <= 0:
            raise ValueError("memory limits must be non-negative and hard limit positive")
        if self.soft_limit_bytes > self.hard_limit_bytes:
            raise ValueError("soft limit cannot exceed hard limit")

    def reserve(self, size_bytes: int) -> bool:
        if size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        requested = self.current_bytes + size_bytes
        if requested > self.hard_limit_bytes:
            raise MemoryBudgetExceeded(
                f"memory_budget_exceeded: requested={requested} hard={self.hard_limit_bytes}"
            )
        self.current_bytes = requested
        self.peak_bytes = max(self.peak_bytes, requested)
        return requested <= self.soft_limit_bytes

    def release(self, size_bytes: int) -> None:
        if size_bytes < 0 or size_bytes > self.current_bytes:
            raise ValueError("release exceeds current budget")
        self.current_bytes -= size_bytes

    def record_spill(self) -> None:
        self.spills += 1

    def receipt(self) -> dict[str, int]:
        return {
            "soft_limit_bytes": self.soft_limit_bytes,
            "hard_limit_bytes": self.hard_limit_bytes,
            "current_bytes": self.current_bytes,
            "peak_bytes": self.peak_bytes,
            "spills": self.spills,
        }
