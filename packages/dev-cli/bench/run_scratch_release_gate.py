"""Preflight the scratch-mode v0.5 release-gate benchmark.

The RFC gate is live and credentialed: 15 real goals across 5 pilot stacks,
planner validity, clean scaffolds, green end-to-end runs, median wall-clock,
average cost, and SkillOpt approval. This script does not fake those metrics.
It gives the gate a concrete runnable entrypoint and reports whether the local
environment is ready to run the live matrix.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio.providers import planner_cfg  # noqa: E402
from simplicio.scratch.stack_registry import StackRegistry  # noqa: E402


RESULTS_JSON = ROOT / "bench" / "results_scratch_release_gate.json"
RESULTS_MD = ROOT / "bench" / "results_scratch_release_gate.md"

PILOT_STACKS = ("py-fastapi", "ts-nextjs", "go-gin", "rust-axum", "php-laravel")

RELEASE_GOALS = (
    "CRUD app for condo units with owner contact search",
    "CRUD app for invoices with paid and overdue filters",
    "CRUD app for maintenance tickets with assignee status",
    "CRUD app for visitors with check-in and check-out timestamps",
    "CRUD app for amenity bookings with date conflict checks",
    "CRUD app for announcements with publish and archive state",
    "CRUD app for documents with category filtering",
    "CRUD app for vendors with active contract tracking",
    "CRUD app for inventory items with low-stock flag",
    "CRUD app for package deliveries with resident pickup",
    "CRUD app for parking spaces with vehicle assignment",
    "CRUD app for board meetings with minutes status",
    "CRUD app for access devices with revocation state",
    "CRUD app for payments with receipt reference",
    "CRUD app for service requests with priority queue",
)

STACK_TOOLCHAINS = {
    "py-fastapi": ("python",),
    "ts-nextjs": ("node", "npm", "pnpm"),
    "go-gin": ("go",),
    "rust-axum": ("cargo",),
    "php-laravel": ("php", "composer"),
}


def run_preflight() -> dict[str, Any]:
    registry = StackRegistry()
    stacks = {stack.slug: stack for stack in registry.list()}
    missing_stacks = [slug for slug in PILOT_STACKS if slug not in stacks]
    stack_rows = [_stack_row(slug, slug in stacks) for slug in PILOT_STACKS]
    planner = _planner_readiness()
    doer = _doer_readiness()
    blockers = []
    if missing_stacks:
        blockers.append("missing pilot stacks: " + ", ".join(sorted(missing_stacks)))
    if not planner["ready"]:
        blockers.append(planner["blocker"])
    if not doer["ready"]:
        blockers.append(doer["blocker"])
    for row in stack_rows:
        if row["missing_tools"]:
            blockers.append(
                f"{row['stack']} missing tools: {', '.join(row['missing_tools'])}"
            )

    planned_runs = len(RELEASE_GOALS) * len(PILOT_STACKS)
    return {
        "benchmark": "scratch-release-gate",
        "scope": (
            "preflight for the live scratch v0.5 release gate; does not "
            "replace credentialed planner/doer execution"
        ),
        "date": time.strftime("%Y-%m-%d"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "gate": {
            "goals": len(RELEASE_GOALS),
            "pilot_stacks": len(PILOT_STACKS),
            "planned_runs": planned_runs,
            "planner_valid_min": 0.90,
            "scaffold_clean_min": 0.95,
            "e2e_green_min": 0.80,
            "median_wall_clock_max_minutes": 8,
            "average_cost_max_usd": 1.00,
            "skillopt_human_approval_min": 0.80,
        },
        "planner": planner,
        "doer": doer,
        "stacks": stack_rows,
        "goals": list(RELEASE_GOALS),
        "summary": {
            "ready_for_live_gate": not blockers,
            "blocker_count": len(blockers),
            "blockers": blockers,
        },
    }


def _stack_row(slug: str, present: bool) -> dict[str, Any]:
    tools = STACK_TOOLCHAINS[slug]
    found = {tool: _which(tool) for tool in tools}
    return {
        "stack": slug,
        "present": present,
        "required_tools": list(tools),
        "found_tools": found,
        "missing_tools": [tool for tool, path in found.items() if path is None],
    }


def _planner_readiness() -> dict[str, Any]:
    cfg = planner_cfg(require_key=False)
    model = str(cfg.get("model") or "")
    env_key = _planner_env_key(model)
    return {
        "model": model,
        "kind": "disabled",
        "ready": False,
        "credential": "disabled",
        "env_key": env_key,
        "blocker": "llm_execution_disabled",
    }


def _doer_readiness() -> dict[str, Any]:
    raw = os.environ.get("SIMPLICIO_MODEL", "").strip()
    env_key = _doer_env_key(raw)
    return {
        "model": raw,
        "kind": "disabled",
        "ready": False,
        "credential": "disabled",
        "env_key": env_key,
        "blocker": "llm_execution_disabled",
    }


def _planner_env_key(model: str) -> str:
    raw = os.environ.get("SIMPLICIO_PLANNER", "deepseek-hf/" + model)
    prefix = raw.split("/", 1)[0]
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "deepseek-hf": "HF_TOKEN",
        "hf": "HF_TOKEN",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(prefix, "SIMPLICIO_API_KEY")


def _doer_env_key(model: str) -> str:
    prefix = model.split("/", 1)[0]
    return {
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "deepseek-hf": "HF_TOKEN",
        "hf": "HF_TOKEN",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(prefix, "SIMPLICIO_API_KEY")


def _shell_out_command(model: str) -> str:
    prefix = model.split("/", 1)[0]
    return {
        "claude-cli": "claude",
        "codex-cli": "codex",
    }.get(prefix, prefix)


def _which(command: str) -> str | None:
    override = os.environ.get(_tool_env_var(command), "").strip()
    if override:
        return override if _tool_command_ok(command, override) else None

    candidates = [command]
    if os.name == "nt":
        candidates.extend([f"{command}.cmd", f"{command}.exe", f"{command}.bat"])
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found

    if command == "pnpm":
        corepack = shutil.which("corepack")
        if corepack and _tool_command_ok("pnpm", f'"{corepack}" pnpm'):
            return f"{corepack} pnpm"
    return None


def _tool_env_var(command: str) -> str:
    return "SIMPLICIO_TOOL_" + command.upper().replace("-", "_")


def _tool_command_ok(command: str, executable: str) -> bool:
    version_arg = {
        "go": "version",
    }.get(command, "--version")
    try:
        proc = subprocess.run(
            f"{executable} {version_arg}",
            capture_output=True,
            shell=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def write_reports(result: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_to_markdown(result), encoding="utf-8")


def _to_markdown(result: dict[str, Any]) -> str:
    gate = result["gate"]
    summary = result["summary"]
    lines = [
        "# Scratch Release Gate Preflight",
        "",
        result["scope"],
        "",
        "## Gate",
        "",
        f"- goals: {gate['goals']}",
        f"- pilot stacks: {gate['pilot_stacks']}",
        f"- planned runs: {gate['planned_runs']}",
        f"- planner valid minimum: {gate['planner_valid_min']:.0%}",
        f"- scaffold clean minimum: {gate['scaffold_clean_min']:.0%}",
        f"- e2e green minimum: {gate['e2e_green_min']:.0%}",
        f"- median wall-clock maximum: {gate['median_wall_clock_max_minutes']} min",
        f"- average cost maximum: ${gate['average_cost_max_usd']:.2f}",
        "",
        "## Readiness",
        "",
        f"- ready for live gate: {summary['ready_for_live_gate']}",
        f"- blocker count: {summary['blocker_count']}",
    ]
    for blocker in summary["blockers"]:
        lines.append(f"- blocker: {blocker}")
    lines.extend(
        [
            "",
            "## Stacks",
            "",
            "| stack | present | missing tools |",
            "| --- | --- | --- |",
        ]
    )
    for row in result["stacks"]:
        missing = ", ".join(row["missing_tools"]) or "-"
        lines.append(f"| {row['stack']} | {row['present']} | {missing} |")
    lines.extend(
        [
            "",
            "## Goals",
            "",
        ]
    )
    for goal in result["goals"]:
        lines.append(f"- {goal}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_preflight()
    write_reports(result, args.json_output, args.md_output)
    if not args.quiet:
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        print(f"wrote {args.json_output}")
        print(f"wrote {args.md_output}")
    return 0 if result["summary"]["ready_for_live_gate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
