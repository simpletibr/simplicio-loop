"""toolchain_detect (intake): reports the test command the run will verify with. It detects nothing.

The command is `verify` of the repo's loop.toml on the default branch (verify.configured_command); the tick hands it over
in ctx.test_command and never runs without one, so a missing command is `skipped`, not a guess.
"""
from .registry import PointContext, PointResult, register

NAME = "toolchain_detect"


async def report(ctx: PointContext) -> PointResult:
    if not ctx.test_command:
        return PointResult(NAME, "skipped", {}, "verify_not_configured")
    return PointResult(NAME, "ok", {"test_command": ctx.test_command})


register(NAME, "intake", report)
