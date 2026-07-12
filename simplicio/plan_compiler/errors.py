"""Structured errors for the plan-compiler contracts (issue #166)."""

from __future__ import annotations

from collections.abc import Iterable


class PlanCompilerError(ValueError):
    """Base class for every plan-compiler rejection."""


class SchemaMismatchError(PlanCompilerError):
    """Raised when a payload declares an unexpected or unsupported schema."""

    def __init__(self, schema: str, expected: str, got: str) -> None:
        self.schema = schema
        self.expected = expected
        self.got = got
        super().__init__(f"{schema}: expected schema {expected!r}, got {got!r}")


class PlanValidationError(PlanCompilerError):
    """Raised when a PlanDAG/EffectPlan/VerificationPlan set fails validation."""

    def __init__(self, diagnostics: Iterable[str]) -> None:
        self.diagnostics = list(diagnostics)
        super().__init__("; ".join(self.diagnostics))
