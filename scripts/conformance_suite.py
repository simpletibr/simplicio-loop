#!/usr/bin/env python3
"""simplicio-loop — portable stage-agent contract validation (issue #432).

Validates the portable stage-agent contracts (the 12 roles declared in
``contracts/stage-agents/v1/stages.json``) in this Python process.  It does
not execute Claude, Codex, or any other external runtime.  A README describes
an adapter; it is not evidence that an agent binary, native bind, or queue
worker is installed and runnable.

For each runtime in ``adapters/MATRIX.md`` the suite records:

  * native agent API available?        (binário no PATH ou adapter marker)
  * command adapter available?         (adapter README with a public CLI path)
  * queue adapter available?           (adapter declares queue worker mode)
  * lifecycle hooks?                   (adapter promises Stop/afterAgent/tasks)
  * scheduler / self-paced?            (loop-drive column)
  * total slots                        (from the stage graph / coordinator)
  * isolation levels                   (per-adapter declaration)
  * cancellation                       (per-adapter declaration)
  * model/runtime observation          (per-adapter declaration)
  * limitations & expected BLOCKED     (per-adapter declaration)

The core validates one canonical fixture against the real
``simplicio_loop.stage_agents`` validator.  Runtime rows are an inventory of
declared adapter capabilities only.  Native, installed, and queue-worker
execution belongs to an external lane which must supply both a runtime binary
and a registered executable adapter command; this script deliberately has no
such command and reports that lane as unavailable.

Exit code 0 = portable contract validation passed. Exit 1 = the canonical
graph or portable receipt validation failed.  It is never evidence that the
listed runtimes executed.

Usage:
    python3 scripts/conformance_suite.py                 # all runtimes
    python3 scripts/conformance_suite.py claude codex    # subset
    python3 scripts/conformance_suite.py --json out.json # machine report
    python3 scripts/conformance_suite.py --md out.md     # markdown matrix
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field, asdict

# Make the repo root importable both as a script and as a module.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from simplicio_loop import stage_agents as sa  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ADAPTERS_DIR = os.path.join(_REPO_ROOT, "adapters")

# The 15 runtimes that have a stage-agent conformance profile: a subset of the harness catalog
# (simplicio_loop/_catalog/harnesses.json), which lists every host in adapters/MATRIX.md.
RUNTIMES = [
    "claude", "codex", "cursor", "vscode", "antigravity", "kiro", "opencode",
    "gemini", "aider", "simplicio_agent", "openclaw", "orca", "deepseek",
    "qwen", "kimi",
]

# Binary name required by a real external execution lane.  This core does not
# invoke these binaries, so their presence is recorded but never treated as
# runtime conformance.
RUNTIME_BINARIES = {
    "claude": "claude",
    "codex": "codex",
    "cursor": "cursor",
    "vscode": "code",
    "antigravity": None,
    "kiro": "kiro",
    "opencode": "opencode",
    "gemini": "gemini",
    "aider": "aider",
    "simplicio_agent": "simplicio",
    "openclaw": None,
    "orca": None,
    "deepseek": None,
    "qwen": None,
    "kimi": None,
}

# Capability matrix — static, verifiable facts extracted from each adapter
# README's MCP-config / loop-drive / hooks columns. ``True`` means the adapter
# *documents* the capability; the live ``detect_available`` check confirms the
# binary/adapter is actually present on this host.
CAPABILITIES = {
    "claude": dict(native_api=True, command_adapter=True, queue_adapter=False,
                   hooks="Stop hook (full)", scheduler="stop-hook", slots=4,
                   isolation="worktree", cancellation="abort", observation="hook+N3",
                   blocked=["queue worker mode (no queue adapter)"]),
    "codex": dict(native_api=True, command_adapter=True, queue_adapter=False,
                  hooks="self-paced (partial)", scheduler="self-paced", slots=4,
                  isolation="worktree", cancellation="abort", observation="N2+N3",
                  blocked=["hook-bound scenarios (partial hooks)"]),
    "cursor": dict(native_api=True, command_adapter=True, queue_adapter=False,
                   hooks="stop + afterAgentResponse (full)", scheduler="stop-hook",
                   slots=4, isolation="worktree", cancellation="abort",
                   observation="N1+N3",
                   blocked=["queue worker mode (no queue adapter)"]),
    "vscode": dict(native_api=False, command_adapter=True, queue_adapter=False,
                   hooks="tasks (partial)", scheduler="self-paced", slots=4,
                   isolation="workspace", cancellation="task cancel",
                   observation="N2+N3",
                   blocked=["native subagent mode (no native API)"]),
    "antigravity": dict(native_api=False, command_adapter=True, queue_adapter=False,
                        hooks="self-paced (partial)", scheduler="self-paced", slots=4,
                        isolation="unknown", cancellation="unknown",
                        observation="N2+N3",
                        blocked=["native subagent mode (no native API)"]),
    "kiro": dict(native_api=False, command_adapter=True, queue_adapter=False,
                 hooks="self-paced", scheduler="self-paced", slots=4,
                 isolation="unknown", cancellation="unknown", observation="N2+N3",
                 blocked=["native subagent mode (no native API)"]),
    "opencode": dict(native_api=True, command_adapter=True, queue_adapter=False,
                     hooks="stop hook", scheduler="stop-hook", slots=4,
                     isolation="worktree", cancellation="abort", observation="N1+N3",
                     blocked=["queue worker mode (no queue adapter)"]),
    "gemini": dict(native_api=False, command_adapter=True, queue_adapter=False,
                   hooks="self-paced", scheduler="self-paced", slots=4,
                   isolation="unknown", cancellation="unknown", observation="N2+N3",
                   blocked=["native subagent mode (no native API)"]),
    "aider": dict(native_api=False, command_adapter=True, queue_adapter=False,
                  hooks="none", scheduler="self-paced", slots=1,
                  isolation="none", cancellation="ctrl-c", observation="N2",
                  blocked=["native subagent", "hook-bound", "limited slots/waves"]),
    "simplicio_agent": dict(native_api=True, command_adapter=True, queue_adapter=True,
                            hooks="full (loop_stop/orient_clamp)", scheduler="both",
                            slots=64, isolation="worktree+process", cancellation="kill",
                            observation="N1+N2+N3",
                            blocked=[]),
    "openclaw": dict(native_api=True, command_adapter=True, queue_adapter=True,
                     hooks="full", scheduler="both", slots=32,
                     isolation="process", cancellation="kill", observation="N1+N3",
                     blocked=[]),
    "orca": dict(native_api=False, command_adapter=True, queue_adapter=False,
                 hooks="self-paced", scheduler="self-paced", slots=4, isolation="unknown",
                 cancellation="unknown", observation="N2+N3",
                 blocked=["native subagent mode (no native API)"]),
    "deepseek": dict(native_api=False, command_adapter=True, queue_adapter=False,
                     hooks="self-paced", scheduler="self-paced", slots=4,
                     isolation="unknown", cancellation="unknown", observation="N2+N3",
                     blocked=["native subagent mode (no native API)"]),
    "qwen": dict(native_api=False, command_adapter=True, queue_adapter=False,
                 hooks="self-paced", scheduler="self-paced", slots=4, isolation="unknown",
                 cancellation="unknown", observation="N2+N3",
                 blocked=["native subagent mode (no native API)"]),
    "kimi": dict(native_api=False, command_adapter=True, queue_adapter=False,
                 hooks="self-paced", scheduler="self-paced", slots=4, isolation="unknown",
                 cancellation="unknown", observation="N2+N3",
                 blocked=["native subagent mode (no native API)"]),
}


@dataclass
class RuntimeAdapterStatus:
    runtime: str
    available: bool = False
    installed: bool = False
    availability_reason: str = ""
    roles_expected: int = 0
    roles_supported: int = 0
    sandbox_passed: bool = False
    sandbox_detail: str = ""
    receipt_equivalent: bool = False
    capabilities: dict = field(default_factory=dict)
    blocked_scenarios: list = field(default_factory=list)
    error: str = ""
    external_lane: str = "unavailable"
    external_reason: str = ""


def expected_roles() -> list[str]:
    graph = sa.load_graph(sa.STAGES_FILE)
    return [r.get("role_id") for r in graph.get("roles", [])]


def validate_portable_contract() -> tuple[bool, str]:
    """Validate a canonical fixture, without attributing it to a runtime."""
    try:
        graph = sa.load_graph(sa.STAGES_FILE)
        ok_graph, graph_errors = sa.validate_graph(graph)
        if not ok_graph:
            return False, f"canonical graph invalid: {graph_errors}"

        # Shared run identity — every receipt/instance must bind to it.
        run_id = "conformance-run"
        task_id = "portable-contract-task"
        attempt_id = "attempt-1"
        fence = "fence-conformance"
        plan_revision = 1
        agent_instance_id = "portable-contract-instance"

        context_hash = "0" * 64
        manifest_hash = str(graph.get("manifest_hash") or "0" * 64)
        intake_stage = next((s for s in graph.get("stages", []) if s.get("stage_id") == "intake"), {})
        negotiated_capabilities = list(intake_stage.get("required_capabilities") or ["receipts"])
        instance = sa.make_agent_instance(
            agent_instance_id=agent_instance_id, role_id="intake_planner", stage_id="intake",
            run_id=run_id, task_id=task_id, attempt_id=attempt_id, attempt_ordinal=1,
            fence=fence, plan_revision=plan_revision, context_hash=context_hash,
            manifest_hash=manifest_hash, runtime="portable-validator", driver="in_process",
            negotiated_capabilities=negotiated_capabilities, terminal_status="completed",
        )
        receipt = sa.make_stage_receipt(
            receipt_id="portable-contract-receipt", agent_instance_id=agent_instance_id,
            role_id="intake_planner", stage_id="intake", run_id=run_id, task_id=task_id,
            attempt_id=attempt_id, attempt_ordinal=1, fence=fence, plan_revision=plan_revision,
            context_hash=context_hash, manifest_hash=manifest_hash, verdict="pass",
            evidence_refs=["mode=in_process", "runtime=portable-validator"],
            next_stage_recommendation="planning",
        )
        ok_inst, inst_errors = sa.validate_instance(instance, {
            "run_id": run_id, "task_id": task_id, "attempt_id": attempt_id,
            "attempt_ordinal": 1, "fence": fence, "plan_revision": plan_revision,
        })
        if not ok_inst:
            return False, f"instance rejected: {inst_errors}"

        ok_rec, rec_errors = sa.validate_receipt(receipt, instance, graph)
        if not ok_rec:
            return False, f"receipt rejected: {rec_errors}"

        return True, "portable fixture produced a valid StageReceipt"
    except Exception as exc:  # pragma: no cover — defensive
        return False, f"portable validation error: {exc}"


def adapter_status_for_runtime(runtime: str) -> RuntimeAdapterStatus:
    """Return declarations, never a claim that the runtime was executed."""
    rc = RuntimeAdapterStatus(runtime=runtime)
    rc.roles_expected = len(expected_roles())
    rc.capabilities = CAPABILITIES.get(runtime, {})
    rc.blocked_scenarios = rc.capabilities.get("blocked", [])

    rc.availability_reason = "README/capability declarations are not runtime availability"
    bin_name = RUNTIME_BINARIES.get(runtime)
    rc.installed = bool(bin_name and shutil.which(bin_name))
    if not rc.installed:
        rc.external_reason = ("requires a runtime binary and a registered executable adapter "
                              "command; neither is supplied by this portable validation")
    else:
        rc.external_reason = ("runtime binary is present, but no registered executable adapter "
                              "command was supplied; portable validation does not invoke it")
    rc.sandbox_detail = "BLOCKED: " + rc.external_reason
    return rc


def build_report(runtimes: list[str]) -> dict:
    portable_ok, portable_detail = validate_portable_contract()
    results = [asdict(adapter_status_for_runtime(r)) for r in runtimes]
    return {
        "schema": "simplicio.conformance/v1",
        "issue": 432,
        "total_runtimes": len(results),
        "available_runtimes": 0,
        "available_failed": 0,
        "portable_validation": {"passed": portable_ok, "detail": portable_detail},
        "exit_gate": "pass" if portable_ok else "fail",
        "roles_canonical": expected_roles(),
        "results": results,
    }


def render_md(report: dict) -> str:
    lines = ["# Portable Stage-Agent Contract Validation (issue #432)", ""]
    lines.append(f"- Total runtimes: **{report['total_runtimes']}**")
    lines.append("- External runtimes executed by this report: **0**")
    lines.append("- External execution lane: **UNAVAILABLE** (adapter command not registered here)")
    lines.append(f"- Portable fixture: **{'PASS' if report['portable_validation']['passed'] else 'FAIL'}**")
    lines.append(f"- Exit gate: **{report['exit_gate'].upper()}**")
    lines.append("")
    lines.append("| Runtime | Installed | External lane | Canonical roles | Runtime receipt | Blocked scenarios |")
    lines.append("|---|---|---|---|---|---|")
    for r in report["results"]:
        inst = "✅" if r["installed"] else "❌"
        avail = "UNAVAILABLE"
        sand = "not executed"
        blocked = ", ".join(r["blocked_scenarios"]) or "—"
        lines.append(
            f"| {r['runtime']} | {inst} | {avail} | {r['roles_expected']} "
            f"| {sand} | {blocked} |"
        )
    lines.append("")
    for r in report["results"]:
        if r["sandbox_detail"]:
            lines.append(f"- **{r['runtime']}**: {r['sandbox_detail']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="stage-agent conformance suite (#432)")
    parser.add_argument("runtimes", nargs="*", default=RUNTIMES,
                        help="subset of runtimes to check (default: all)")
    parser.add_argument("--json", metavar="PATH", help="write JSON report")
    parser.add_argument("--md", metavar="PATH", help="write markdown matrix")
    args = parser.parse_args(argv)

    # Validate requested runtimes exist in the matrix.
    unknown = [r for r in args.runtimes if r not in RUNTIMES]
    if unknown:
        print(f"unknown runtime(s): {unknown}", file=sys.stderr)
        return 2

    report = build_report(args.runtimes)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as fh:
            fh.write(render_md(report))

    # Always print a summary to stdout.
    print(f"portable conformance: 0/{report['total_runtimes']} runtimes executed; "
          f"gate={report['exit_gate']}")
    for r in report["results"]:
        flag = "BLK"
        print(f"  [{flag}] {r['runtime']}: {r['sandbox_detail'] or r['availability_reason']}")

    return 0 if report["exit_gate"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
