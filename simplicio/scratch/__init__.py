"""simplicio.scratch — from-scratch project creation pipeline.

Two-phase flow (planner + executor) that complements simplicio.task
(single-file edit pipeline). See bench/SCRATCH_MODE_RFC.md.
"""

from .executor import ExecutorReport, execute_plan
from .plan_schema import Plan, PlanValidationError, validate_plan
from .planner import PlannerError, generate_plan
from .stack_registry import Stack, StackRegistry

__all__ = [
    "StackRegistry",
    "Stack",
    "Plan",
    "validate_plan",
    "PlanValidationError",
    "generate_plan",
    "PlannerError",
    "execute_plan",
    "ExecutorReport",
]
