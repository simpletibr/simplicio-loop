#!/usr/bin/env python3
"""simplicio-loop — Portable Stage Agent Coordinator CLI (issue #424, epic #422).

Runtime-agnostic driver over ``simplicio_loop.stage_agent_coordinator``: runs
a manifest's stages to completion (or BLOCKED) via whatever adapters are
available on the host, resumes from a journal, reports status, and cancels a
run. Stdlib-only, deterministic given fixed inputs; a missing adapter/toolchain
BLOCKS with a stable reason_code rather than faking a pass.

Usage:
    python3 scripts/stage_coordinator.py run --run-id run-1 --task-id task-1 \
        --command "python3 fixtures/echo_agent.py {input} {output} {receipt}"
    python3 scripts/stage_coordinator.py status --run-id run-1 --task-id task-1 \
        --journal .simplicio-loop/orchestrator/stage-agents/run-1.jsonl
    python3 scripts/stage_coordinator.py probe --command "..."
    python3 scripts/stage_coordinator.py selftest
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simplicio_loop import stage_agent_coordinator as sc  # noqa: E402
from simplicio_loop import stage_agents as sa  # noqa: E402


def _emit(payload: dict, *, exit_code: int = 0) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return exit_code


def _default_journal_path(run_id: str) -> Path:
    return Path(".simplicio-loop/orchestrator") / "stage-agents" / f"{run_id}.jsonl"


def _build_adapters(opts) -> list:
    adapters: list = []
    if opts.command:
        adapters.append(sc.CommandAgentAdapter(command=opts.command.split()))
    adapters.append(sc.HumanGateAdapter())
    return adapters


def cmd_probe(opts) -> int:
    adapters = _build_adapters(opts)
    return _emit({"ok": True, "adapters": [{"kind": a.kind, "available": a.probe()} for a in adapters]})


def cmd_run(opts) -> int:
    try:
        journal_path = Path(opts.journal) if opts.journal else _default_journal_path(opts.run_id)
        journal = sc.StageCoordinatorJournal(journal_path)
        coordinator = sc.StageAgentCoordinator(
            run_id=opts.run_id, task_id=opts.task_id, adapters=_build_adapters(opts),
            journal=journal, host_total_slots=opts.host_slots, coordinator_slots=opts.coordinator_slots,
        )
        coordinator.run_all()
        return _emit({"ok": True, **coordinator.status_report()})
    except sc.StageCoordinatorError as exc:
        return _emit({"ok": False, "reason_code": exc.reason_code, "error": str(exc)}, exit_code=1)


def cmd_status(opts) -> int:
    journal_path = Path(opts.journal) if opts.journal else _default_journal_path(opts.run_id)
    journal = sc.StageCoordinatorJournal(journal_path)
    coordinator = sc.StageAgentCoordinator(
        run_id=opts.run_id, task_id=opts.task_id, adapters=[sc.HumanGateAdapter()], journal=journal,
    )
    return _emit({"ok": True, **coordinator.status_report()})


def cmd_selftest(_opts) -> int:
    checks: list[bool] = []

    def chk(name: str, value, expected) -> None:
        ok = value == expected
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    graph = sa.load_graph()
    waves = sc.plan_waves(graph)
    chk("waves.first_is_intake", waves[0], ["intake"])
    chk("waves.count", len(waves) >= 3, True)
    chk("slots.zero_coordinator_leaves_zero", sc.available_slots(host_total_slots=1, coordinator_slots=1), 0)
    chk("slots.four_total_minus_one_coordinator", sc.available_slots(host_total_slots=4, coordinator_slots=1), 3)

    registry = sc.AdapterRegistry([sc.HumanGateAdapter()])
    human_stage = {"isolation_level": "human"}
    non_human_stage = {"isolation_level": "process"}
    role = {"role_id": "intake_planner"}
    chk("registry.selects_human_for_human_stage", registry.select(role=role, stage=human_stage).kind, "human")
    try:
        registry.select(role=role, stage=non_human_stage)
        chk("registry.blocks_when_no_adapter", False, True)
    except sc.StageCoordinatorError as exc:
        chk("registry.blocks_when_no_adapter", exc.reason_code, sc.REASON_NO_COMPATIBLE_ADAPTER)

    ok = all(checks)
    print(f"selftest: {'PASS' if ok else 'FAIL'} ({sum(checks)}/{len(checks)})")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="stage_coordinator.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="report which adapters are available on this host")
    p_probe.add_argument("--command", default=None, help="SIMPLICIO_AGENT_COMMAND-style argv template")
    p_probe.set_defaults(func=cmd_probe)

    p_run = sub.add_parser("run", help="drive a manifest's stages to completion/BLOCKED")
    p_run.add_argument("--run-id", required=True)
    p_run.add_argument("--task-id", required=True)
    p_run.add_argument("--command", default=None, help="SIMPLICIO_AGENT_COMMAND-style argv template")
    p_run.add_argument("--journal", default=None)
    p_run.add_argument("--host-slots", type=int, default=4)
    p_run.add_argument("--coordinator-slots", type=int, default=1)
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="report reducer status from a journal")
    p_status.add_argument("--run-id", required=True)
    p_status.add_argument("--task-id", required=True)
    p_status.add_argument("--journal", default=None)
    p_status.set_defaults(func=cmd_status)

    p_selftest = sub.add_parser("selftest", help="deterministic self-check, no fixtures needed")
    p_selftest.set_defaults(func=cmd_selftest)

    opts = parser.parse_args()
    return opts.func(opts)


if __name__ == "__main__":
    raise SystemExit(main())
