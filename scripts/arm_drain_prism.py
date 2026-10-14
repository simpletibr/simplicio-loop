#!/usr/bin/env python3
"""Arm a Prism-style drain scratchpad + recommended strict env.

Does not start agents — freezes loop state so Claude/Codex/Grok/Cursor/etc.
self-pace or hook-drive the same contract.

Usage:
  python3 scripts/arm_drain_prism.py --repo . --slots 4 --max-iterations 200 --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROMISE = "all open issues drained with honest ACs and merged PRs"


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _open_issue_count(repo: Path) -> int | None:
    out = _run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "500",
            "--json",
            "number",
            "--jq",
            "length",
        ],
        repo,
    )
    return int(out) if out.isdigit() else None


def _versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for dist in ("simplicio-loop", "simplicio-mapper", "simplicio-cli"):
        try:
            import importlib.metadata as md

            versions[dist] = md.version(dist)
        except Exception:
            versions[dist] = "unknown"
    return versions


def arm(
    repo: Path,
    *,
    slots: int,
    batch_size: int = 10,
    max_iterations: int = 200,
    promise: str = PROMISE,
) -> dict:
    repo = repo.resolve()
    from simplicio_loop.economy_profile import (
        prism_is_eligible,
        recommend_prism_slots,
        resolve_prism_batch_size,
    )
    requested_slots = int(slots)
    if requested_slots < 0:
        raise ValueError("Prism slots must be non-negative")
    slots = requested_slots or int(recommend_prism_slots())
    slots = max(1, slots)
    loop_dir = repo / ".simplicio-loop" / "orchestrator" / "loop"
    loop_dir.mkdir(parents=True, exist_ok=True)
    open_n = _open_issue_count(repo)
    versions = _versions()
    batch_size = resolve_prism_batch_size(batch_size)
    eligibility = prism_is_eligible(open_n or 0)
    if open_n is None:
        eligibility = {"eligible": False, "reason_code": "source_unavailable"}
    capacity = slots * 10
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = f"""---
iteration: 1
max_iterations: {max_iterations}
completion_promise: "{promise}"
evidence_required: true
mode: drain
route_mode: drain
prism_slots: {slots}
prism_batch_size: {batch_size}
prism_wave_barrier: reconcile-before-next
prism_min_tasks_per_slot: 10
prism_logical_capacity: {capacity}
started_at: "{now}"
operator_versions: {json.dumps(versions, sort_keys=True)}
strict: true
forbid_hand_edit: true
fast_mode: required
client_integrations: []
---

Prism drain armed for `{repo.name}`.

Hard rules (all LLMs / all hosts):
1. `simplicio-loop preflight --strict --json` before work.
2. Survey via `simplicio-mapper`.
3. Mutate via `simplicio-dev-cli` / `simplicio-py task` (STRICT forbids host hand-edit primary path).
4. Prism eligibility: {eligibility["eligible"]} ({eligibility["reason_code"]});
   wave width **{batch_size}**; the next wave starts only after lease/result reconciliation.
   Capacity is **{slots}** logical slots with no upper slot ceiling; each slot has a minimum of 10 tasks;
   one agent ownership per transition; reducer before merge pile-up. Physical overlap remains resource-governed.
5. PR to main with `Parte de #N` (never a closing word; a human closes the issue once the criteria are proven); no theater AC stubs.
6. Host integrations (Orca, etc.) only if client requested (`CLIENT_INTEGRATIONS`).
7. When open stays empty across dry≥2 re-queries → promise only with MEASURED evidence.

Open issues at arm: {open_n if open_n is not None else "unknown (gh unavailable)"}
"""
    scratch = loop_dir / "scratchpad.md"
    scratch.write_text(body, encoding="utf-8", newline="\n")
    try:
        from simplicio_loop.economy_profile import economy_parallel_env

        env_hint = economy_parallel_env(prism_slots=slots)
    except Exception:
        env_hint = {
            "SIMPLICIO_LOOP": "1",
            "SIMPLICIO_LOOP_STRICT": "1",
            "SIMPLICIO_REQUIRE_MUTATION_AUTHORITY": "1",
            "SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT": "1",
            "SIMPLICIO_LOOP_FORBID_HAND_EDIT": "1",
            "SIMPLICIO_EXECUTION_PROFILE": "standalone",
            "SIMPLICIO_LOOP_AUTO_FAN_OUT": "1",
            "SIMPLICIO_PRISM_SLOTS": str(slots),
            "SIMPLICIO_OPERATOR_ALWAYS_LATEST": "1",
        }
    return {
        "schema": "simplicio.arm-drain-prism/v1",
        "ok": True,
        "repo": str(repo),
        "scratchpad": str(scratch),
        "open_issues_at_arm": open_n,
        "prism_slots": slots,
        "prism_batch_size": batch_size,
        "prism_wave_barrier": "reconcile-before-next",
        "prism_eligibility": eligibility,
        "prism_min_tasks_per_slot": 10,
        "prism_logical_capacity": capacity,
        "max_iterations": max_iterations,
        "completion_promise": promise,
        "operator_versions": versions,
        "recommended_env": env_hint,
        "next_steps": [
            "source ~/.simplicio-loop/loop-env.sh (or set recommended_env)",
            "simplicio-loop preflight --strict --json",
            "simplicio-mapper scan . --json",
            "claim the next Prism wave (default 10; --batch-size N); reconcile leases/results; PR+merge",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=".")
    p.add_argument(
        "--slots",
        type=int,
        default=0,
        help="Prism slots (0 = auto: maximum this machine can sustain from CPU+RAM)",
    )
    p.add_argument("--max-iterations", type=int, default=200)
    p.add_argument(
        "--batch-size", type=int, default=10,
        help="independent issues/tasks per Prism wave (default: 10; explicit user override allowed)",
    )
    p.add_argument("--promise", default=PROMISE)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    slots = int(args.slots)
    if slots < 0:
        p.error("--slots must be non-negative")
    receipt = arm(
        Path(args.repo),
        slots=slots,
        batch_size=args.batch_size,
        max_iterations=args.max_iterations,
        promise=args.promise,
    )
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(f"armed Prism drain -> {receipt['scratchpad']}")
        print(
            f"  open={receipt['open_issues_at_arm']} "
            f"slots={receipt['prism_slots']} "
            f"capacity={receipt['prism_logical_capacity']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
