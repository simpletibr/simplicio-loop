"""sibling_search (plan): other call sites of the planned files and functions, as 'check these too'.

The files and functions come from the plan when the tick has one, else from the task text (paths that exist in the
clone, `backticked` identifiers). Call sites are ``git grep -w`` hits outside the planned files; the sibling tests
of each file are cli_impl's ``_orient_sibling_test_paths`` (the orient verb's own helper). Never blocks.
"""
import re
from pathlib import Path

from .. import proc, state
from . import _plan
from .registry import PointContext, PointResult, register

NAME = "sibling_search"
MAX_SITES = 30
MAX_SYMBOLS = 10
_STATE_DIRS = (".simplicio-loop/", ".simplicio/")
_DEF = re.compile(r"\b(?:def|function|fn|func|class)\s+([A-Za-z_]\w*)")
_TICKED = re.compile(r"`([A-Za-z_]\w*)(?:\(\))?`")
_PATH = re.compile(r"(?<![\w./-])(\w[\w./-]*\.[A-Za-z0-9]{1,5})(?!\w)")
_TEXT_CAP = 160


def _targets(ctx: PointContext) -> tuple[list[str], list[str]]:
    ops = _plan.operations(ctx.plan)
    files = _plan.plan_paths(ctx.plan, ctx.turbo_json)
    symbols = [name for op in ops for key in ("find", "replace") if isinstance(op.get(key), str)
               for name in _DEF.findall(op[key])]
    if not ops:
        text = ctx.task_text or ""
        found = [_plan.normalize(token) for token in _PATH.findall(text)]
        files += [path for path in found if path and (ctx.clone / path).is_file()]
        symbols += _TICKED.findall(text)
    files = [path for path in dict.fromkeys(files) if (ctx.clone / path).is_file()]
    return files, list(dict.fromkeys(symbols))[:MAX_SYMBOLS]


async def _call_sites(clone: Path, symbol: str, planned: list[str]) -> list[dict]:
    result = await proc.run(["git", "grep", "-n", "-w", "-F", "-I", "--no-color", "-e", symbol], cwd=clone)
    if result.returncode != 0:  # 1 is no match; anything else (not a repo) finds nothing, it does not fail the plan
        return []
    sites = []
    for line in result.stdout.splitlines():
        path, _, rest = line.partition(":")
        number, _, text = rest.partition(":")
        if path in planned or path.startswith(_STATE_DIRS) or not number.isdigit():
            continue
        sites.append({"symbol": symbol, "path": path, "line": int(number), "text": text.strip()[:_TEXT_CAP]})
    return sites


def _sibling_tests(clone: Path, files: list[str]) -> dict[str, list[str]]:
    try:
        from ...cli_impl import _orient_sibling_test_paths
        found = {path: _orient_sibling_test_paths(clone, clone / path) for path in files}
    except Exception as exc:  # fail open: the call sites are still worth reporting
        state.log(f"sibling tests failed: {exc}")
        return {}
    return {path: tests for path, tests in found.items() if tests}


async def search(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    files, symbols = _targets(ctx)
    if not files and not symbols:
        return PointResult(NAME, "skipped", {}, "no_targets")
    sites: list[dict] = []
    for symbol in symbols:
        sites += await _call_sites(ctx.clone, symbol, files)
    return PointResult(NAME, "ok", {
        "files": files, "symbols": symbols, "check_these_too": sites[:MAX_SITES], "truncated": len(sites) > MAX_SITES,
        "sibling_tests": _sibling_tests(ctx.clone, files)})


register(NAME, "plan", search)
