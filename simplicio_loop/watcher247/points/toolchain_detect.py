"""toolchain_detect (intake): the test command of the clone, from verify.detect_test_command (no new logic).

The example point of the contract: no command found is still ok, and says so as UNVERIFIED|no_test_command.
"""
import asyncio

from .. import verify
from .registry import PointContext, PointResult, register

NAME = "toolchain_detect"


async def detect(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    command = await asyncio.to_thread(verify.detect_test_command, ctx.clone)
    if command is None:
        return PointResult(NAME, "ok", {"test_command": None, "label": verify.UNVERIFIED})
    return PointResult(NAME, "ok", {"test_command": command})


register(NAME, "intake", detect)
