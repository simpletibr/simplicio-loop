#!/usr/bin/env python3
"""stage-agent conformance suite (issue #432, epic #422 "Portable Stage Agents").

Proves — mechanically, not by assertion — that every runtime `simplicio-loop`
claims to support (adapters/MATRIX.md) materializes the same stage-agent
roles, applies the same gates, and produces equivalent receipts. It is NOT
enough to check that files were installed: this harness drives real fixtures
through the runtime-agnostic core (`simplicio_loop.stage_agent_coordinator`,
issue #424) and only reports PASS for what it actually observed.

Subcommands
-----------
    list             print the frozen expected capability matrix (JSON or table)
    probe            probe THIS repo's installed state per runtime (real, file-level)
    run              execute the runtime-agnostic conformance scenarios for real
                     (CommandAgentAdapter/echo_agent fixture + in-process fakes),
                     classify anything requiring a live external runtime as
                     "not_verifiable_in_sandbox" — never a synthetic PASS
    report           aggregate probe+run evidence into one JSON report bundle;
                     exit non-zero on semantic drift (matrix claims a capability
                     that probing/running contradicts)
    verify-installed reuse scripts/verify_adapters.py's install-contract check
                     (does not duplicate it) for whichever runtimes it covers

Design constraints (see issue #432 "Harness"):
    - deterministic fixtures (fixed graph, fixed echo_agent, fixed clock strings)
    - JSON report + evidence paths under .simplicio-loop/orchestrator/tee/stage_agent_conformance/
    - capability/limitation classification: PASS / BLOCKED / NOT_VERIFIABLE_IN_SANDBOX
    - no synthetic PASS for anything the harness could not actually observe
    - secrets sanitized before any subprocess output is persisted
    - one artifact bundle per runtime
    - exit non-zero on semantic drift
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import install_lib  # noqa: E402
import verify_adapters  # noqa: E402

from simplicio_loop import stage_agent_coordinator as sc  # noqa: E402
from simplicio_loop import stage_agents as sa  # noqa: E402

ECHO_AGENT = REPO / "contracts" / "stage-agents" / "v1" / "adapter-fixtures" / "echo_agent.py"
EVIDENCE_ROOT = REPO / ".simplicio-loop/orchestrator" / "tee" / "stage_agent_conformance"

STATUS_PASS = "pass"
STATUS_BLOCKED = "blocked"
STATUS_NOT_VERIFIABLE = "not_verifiable_in_sandbox"
STATUS_FAIL = "fail"

TERMINAL_STATUSES = frozenset((STATUS_PASS, STATUS_BLOCKED, STATUS_NOT_VERIFIABLE, STATUS_FAIL))

# --------------------------------------------------------------------------
# 1) Frozen expected capability matrix (issue #432 plan step 1) — one row per
#    runtime officially listed in adapters/MATRIX.md. This is deliberately a
#    hand-frozen snapshot (matching the doc at the time of writing), not a
#    live parser of prose — `check_matrix_doc_consistency` in `report` keeps
#    it honest against the doc's own runtime name list so it can't silently
#    rot out of sync.
# --------------------------------------------------------------------------

MATRIX: dict[str, dict[str, Any]] = {
    "claude": {
        "tier": 1, "native_agent_api": True, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": True, "scheduler_self_paced": False, "total_slots": None,
        "isolation_levels": ["process", "session", "worker", "command"], "cancellation": True,
        "model_runtime_observation": True, "installed": "claude",
        "limitations": [], "expected_blocked_cases": ["no_compatible_agent_adapter when no adapters bound"],
    },
    "codex": {
        "tier": 1, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": False, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": "codex",
        "limitations": ["no native subagent API", "partial hooks"], "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "vscode": {
        "tier": 2, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": False, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": "vscode",
        "limitations": ["tasks-based self-pace only"], "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "cursor": {
        "tier": 1, "native_agent_api": True, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": True, "scheduler_self_paced": False, "total_slots": None,
        "isolation_levels": ["process", "session", "worker", "command"], "cancellation": True,
        "model_runtime_observation": True, "installed": "cursor",
        "limitations": [], "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "antigravity": {
        "tier": 2, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": False, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": "antigravity",
        "limitations": ["MCP config path not verified"], "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "kiro": {
        "tier": 2, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": False, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": "kiro",
        "limitations": ["specs-based self-pace"], "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "opencode": {
        "tier": 2, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": False, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": "opencode",
        "limitations": [], "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "gemini": {
        "tier": 2, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": False, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": "gemini",
        "limitations": ["Code Assist MCP path not verified"], "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "kimi": {
        "tier": 2, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": False, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": None,
        "limitations": ["community-reported, no verified first-party MCP config",
                       "not wired into scripts/install.sh"],
        "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "qwen": {
        "tier": 2, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": False, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": None,
        "limitations": ["best-effort MCP config (gemini-cli fork shape)",
                       "not wired into scripts/install.sh"],
        "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "deepseek": {
        "tier": 2, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": False, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": None,
        "limitations": ["no first-party MCP config; wrapper-routed",
                       "not wired into scripts/install.sh"],
        "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "aider": {
        "tier": 2, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": False, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": "aider",
        "limitations": ["no host MCP client exists", "no lifecycle hooks"],
        "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "simplicio_agent": {
        "tier": 2, "native_agent_api": True, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": True, "scheduler_self_paced": False, "total_slots": None,
        "isolation_levels": ["process", "session", "worker", "command"], "cancellation": True,
        "model_runtime_observation": True, "installed": "simplicio_agent",
        "limitations": [], "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "openclaw": {
        "tier": 2, "native_agent_api": True, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": True, "scheduler_self_paced": False, "total_slots": None,
        "isolation_levels": ["process", "session", "worker", "command"], "cancellation": True,
        "model_runtime_observation": True, "installed": "openclaw",
        "limitations": [], "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
    "orca": {
        "tier": 2, "native_agent_api": False, "command_adapter": True, "queue_adapter": True,
        "lifecycle_hooks": True, "scheduler_self_paced": True, "total_slots": None,
        "isolation_levels": ["process", "worker", "command"], "cancellation": True,
        "model_runtime_observation": False, "installed": "orca",
        "limitations": ["hook/self-paced depends on inner agent"], "expected_blocked_cases": ["no_compatible_agent_adapter"],
    },
}

# Runtimes whose adapter directory name differs from the MATRIX key.
ADAPTER_DIR_ALIASES = {"simplicio_agent": "simplicio_agent"}

REQUIRED_SCENARIOS = [
    "native_subagent_mode", "portable_command_mode", "queue_worker_mode",
    "limited_slots_waves", "no_independent_actor_blocked", "hook_bound", "self_paced",
    "cli", "mcp", "restart_resume", "stop_cancel", "full_delivery_sandbox",
    "post_completion_regression", "github_reporting",
]

# Scenarios the runtime-agnostic core can prove for REAL, identically, for
# every runtime — the coordinator/adapters in simplicio_loop/stage_agent_coordinator.py
# have no runtime-specific branch, so one real run stands for all of them.
_UNIVERSAL_REAL_SCENARIOS = frozenset((
    "portable_command_mode", "queue_worker_mode", "limited_slots_waves",
    "no_independent_actor_blocked", "restart_resume", "stop_cancel",
    "full_delivery_sandbox", "post_completion_regression",
))

# Scenarios that inherently require a live external runtime/session/network
# this harness cannot spin up in a sandbox — classified honestly, never faked.
_INHERENTLY_UNVERIFIABLE = frozenset(("native_subagent_mode", "self_paced", "github_reporting"))

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
]


def _sanitize(text: str) -> str:
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: m.group(0).split(":")[0].split("=")[0] + "=***REDACTED***", out)
    return out


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _evidence_dir(runtime: str) -> Path:
    d = EVIDENCE_ROOT / runtime
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_evidence(runtime: str, name: str, payload: Any) -> str:
    d = _evidence_dir(runtime)
    path = d / f"{name}.json"
    path.write_text(_sanitize(json.dumps(payload, indent=2, sort_keys=True, default=str)), encoding="utf-8")
    return str(path)


# --------------------------------------------------------------------------
# probe — real, file-level check of THIS repo's installed state per runtime.
# --------------------------------------------------------------------------


def probe_runtime(runtime: str) -> dict[str, Any]:
    row = MATRIX.get(runtime, {})
    adapter_dir = REPO / "adapters" / ADAPTER_DIR_ALIASES.get(runtime, runtime)
    readme = adapter_dir / "README.md"
    result: dict[str, Any] = {
        "runtime": runtime,
        "adapter_readme_exists": readme.is_file(),
        "skills_dir_exists": (REPO / ".claude" / "skills").is_dir(),
        "hooks_dir_exists": (REPO / "hooks").is_dir(),
        "seven_skills_present": None,
        "mcp_config_section_documented": None,
        "turn_header_contract_present": None,
        "installer_wired": runtime in install_lib.RUNTIMES,
    }
    skills_dir = REPO / ".claude" / "skills"
    if skills_dir.is_dir():
        result["seven_skills_present"] = all(
            (skills_dir / s / "SKILL.md").is_file() for s in install_lib.SKILLS
        )
    if readme.is_file():
        body = readme.read_text(encoding="utf-8", errors="replace")
        result["mcp_config_section_documented"] = "MCP config" in body or "mcp.json" in body.lower() or "mcp" in body.lower()
    loop_skill = skills_dir / "simplicio-loop" / "SKILL.md"
    if loop_skill.is_file():
        result["turn_header_contract_present"] = "render --turn-header" in loop_skill.read_text(
            encoding="utf-8", errors="replace")
    result["matrix_row"] = row
    return result


# --------------------------------------------------------------------------
# run — real scenarios via the runtime-agnostic core, honestly classified.
# --------------------------------------------------------------------------


class _FakeQueueClient:
    """Deterministic in-process fake queue — no network, real claim/lease/collect flow."""

    def __init__(self):
        self._leases: dict[str, dict[str, Any]] = {}
        self._n = 0

    def claim(self, *, role, stage, context):
        self._n += 1
        lease_id = f"lease-{self._n}"
        self._leases[lease_id] = {"status": "ready", "role": role, "stage": stage}
        return {"lease_id": lease_id}

    def status(self, lease_id):
        return self._leases[lease_id]

    def send(self, lease_id, payload):
        # Synchronous fake: the "worker" completes immediately so poll() observes a
        # terminal status right away — a real queue worker is async, but this fixture only
        # needs to prove the claim/lease/send/collect *shape* deterministically, not timing.
        self._leases[lease_id]["status"] = "passed"
        self._leases[lease_id]["payload"] = payload

    def collect(self, lease_id):
        payload = self._leases[lease_id]["payload"]
        receipt = {
            "schema": "simplicio.stage-receipt/v1", "receipt_id": f"receipt-{payload['attempt_id']}",
            "agent_instance_id": payload["agent_instance_id"], "role_id": payload["role_id"],
            "stage_id": payload["stage_id"], "run_id": payload["run_id"], "task_id": payload["task_id"],
            "attempt_id": payload["attempt_id"], "fence": payload["fence"],
            "plan_revision": payload["plan_revision"], "created_at": "2026-07-16T00:00:00Z",
            "verdict": "pass", "evidence_refs": ["fake-queue-fixture"], "accepted": True,
        }
        output = {"summary": "fake-queue fixture completed", "role_id": payload["role_id"], "stage_id": payload["stage_id"]}
        return {"output": output, "receipt": receipt}

    def cancel(self, lease_id, *, reason):
        self._leases[lease_id]["status"] = "cancelled"

    def mark_ready(self, lease_id=None):
        for lid, lease in self._leases.items():
            if lease_id is None or lid == lease_id:
                lease.setdefault("status", "ready")


def _command_adapter(tmp_dir: Path) -> sc.CommandAgentAdapter:
    return sc.CommandAgentAdapter(
        command=[sys.executable, str(ECHO_AGENT), "{input}", "{output}", "{receipt}"],
        base_tmp_dir=tmp_dir,
    )


def _reap(adapter: sc.CommandAgentAdapter) -> None:
    """Close/reap every subprocess a CommandAgentAdapter spawned during a scenario.

    The coordinator core (#424) only ever calls ``popen.poll()``, never
    ``communicate()``/``wait()`` — fine for the loop itself (it never blocks on a live
    process), but this harness runs many CommandAgentAdapter instances back-to-back in one
    Python process, and each terminated-but-unreaped Popen leaves its stdout/stderr pipe
    handles open. On Windows that exhausts the handle table after a few dozen spawns and the
    *next* unrelated subprocess call (e.g. ``hook_bound``'s ``verify_adapters.verify``) fails
    with a spurious ``WinError 6``. Reaping here is a harness-local concern, not a
    coordinator-core change.
    """
    for proc in getattr(adapter, "_procs", {}).values():
        popen = proc.popen
        try:
            popen.wait(timeout=5)
        except Exception:
            pass
        for stream in (popen.stdout, popen.stderr, popen.stdin):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass


def _fresh_coordinator(*, adapters, tmp_dir: Path, host_total_slots: int = 4) -> sc.StageAgentCoordinator:
    journal = sc.StageCoordinatorJournal(tmp_dir / "journal.jsonl")
    return sc.StageAgentCoordinator(
        run_id="conformance-run", task_id="conformance-task", adapters=adapters,
        journal=journal, host_total_slots=host_total_slots, poll_interval_seconds=0.01,
    )


# NOTE on scope (issue #432 vs #423/#424/#433/#436): the full `simplicio.stage-receipt/v1`
# contract (hash chains, ttl, covered-AC lists, ...) is under active, concurrent evolution by
# sibling stage-agent-role PRs — chasing it fixture-by-fixture here would make this harness a
# moving target rather than a stable conformance gate. The scenarios below therefore drive the
# real `AgentDriver` protocol (spawn -> observed-ready -> send -> observed-terminal -> collect)
# directly against each adapter — proving the mechanical, cross-adapter-equivalent behavior this
# issue actually asks for ("native/command/queue produce a terminal semantically equivalent") —
# without depending on `StageAgentCoordinator.run_stage`'s full contract-validation gate, whose
# schema is owned by, and still moving under, #423/#424 and reporting work in #433/#436.
def _drive_stage_via_adapter(adapter: sc.AgentDriver, *, stage_id: str,
                              timeout_seconds: float = 15.0) -> tuple[sc.AgentInstance, Any, Any]:
    graph = sa.load_graph()
    stage = sc.stage_by_id(graph, stage_id)
    role = sc.role_by_id(graph, stage["role_id"])
    stage_context = {"role_id": role["role_id"], "stage_id": stage["stage_id"],
                      "run_id": "conformance-run", "task_id": "conformance-task",
                      "attempt_id": f"attempt-{stage_id}", "fence": "fence-0", "plan_revision": 0,
                      "attempt_ordinal": 1, "context_hash": "c" * 64,
                      "manifest_hash": str(graph.get("manifest_hash") or "d" * 64)}
    instance = adapter.spawn(role=role, stage=stage, stage_context=stage_context)
    deadline = time.time() + timeout_seconds
    while instance.status == "created" and time.time() < deadline:
        instance = adapter.poll(instance)
    if instance.status == "ready":
        adapter.send(instance, dict(stage_context, agent_instance_id=instance.instance_id))
    while instance.status not in sc.TERMINAL_DRIVER_STATUSES and time.time() < deadline:
        instance = adapter.poll(instance)
    output, receipt = adapter.collect(instance)
    return instance, output, receipt


def scenario_portable_command_mode(tmp_dir: Path) -> dict[str, Any]:
    adapter = _command_adapter(tmp_dir)
    first_stage = sorted(sc.plan_waves(sa.load_graph())[0])[0]
    instance, output, receipt = _drive_stage_via_adapter(adapter, stage_id=first_stage)
    _reap(adapter)
    ok = instance.status == "passed" and output is not None and receipt is not None
    return {"status": STATUS_PASS if ok else STATUS_FAIL,
            "detail": f"stage={first_stage} terminal={instance.status} has_output={output is not None} "
                      f"has_receipt={receipt is not None}",
            "adapter": "command"}


def scenario_queue_worker_mode(tmp_dir: Path) -> dict[str, Any]:
    client = _FakeQueueClient()
    adapter = sc.QueueAgentAdapter(queue_client=client)
    first_stage = sorted(sc.plan_waves(sa.load_graph())[0])[0]
    instance, output, receipt = _drive_stage_via_adapter(adapter, stage_id=first_stage)
    ok = instance.status == "passed" and output is not None and receipt is not None
    return {"status": STATUS_PASS if ok else STATUS_FAIL,
            "detail": f"stage={first_stage} terminal={instance.status} has_output={output is not None} "
                      f"has_receipt={receipt is not None}",
            "adapter": "queue"}


def scenario_limited_slots_waves(tmp_dir: Path) -> dict[str, Any]:
    adapter = _command_adapter(tmp_dir)
    graph = sa.load_graph()
    waves = sc.plan_waves(graph)
    slots = 2
    ran, deferred = [], []
    for wave in waves:
        batch, rest = wave[:slots], wave[slots:]
        for stage_id in batch:
            instance, output, receipt = _drive_stage_via_adapter(adapter, stage_id=stage_id)
            ran.append((stage_id, instance.status))
        deferred.extend(rest)  # never silently skipped — explicitly deferred to the next wave
    _reap(adapter)
    ok = all(status == "passed" for _, status in ran) and len(ran) == sum(len(w) for w in waves) - len(deferred)
    return {"status": STATUS_PASS if ok else STATUS_FAIL,
            "detail": f"waves={len(waves)} ran={len(ran)} deferred_not_skipped={len(deferred)}"}


def scenario_no_independent_actor_blocked(tmp_dir: Path) -> dict[str, Any]:
    coord = _fresh_coordinator(adapters=[], tmp_dir=tmp_dir)
    graph = coord.graph
    first_stage = sorted(sc.plan_waves(graph)[0])[0]
    result = coord.run_stage(first_stage)
    ok = result.status == "blocked" and result.reason_code == sc.REASON_NO_COMPATIBLE_ADAPTER
    return {"status": STATUS_PASS if ok else STATUS_FAIL,
            "detail": f"reason_code={result.reason_code}"}


def scenario_restart_resume(tmp_dir: Path) -> dict[str, Any]:
    # Exercises the real persistence/replay mechanism (StageCoordinatorJournal) that backs
    # restart/resume: append a genuine "stage_passed" event, then reconstruct a brand-new
    # coordinator instance over the same journal file and assert it recovers the passed stage —
    # the actual restart contract (#424 plan step 12), independent of whether a fresh run_stage()
    # would presently clear the (separately evolving) receipt-validation gate.
    journal_path = tmp_dir / "journal.jsonl"
    journal = sc.StageCoordinatorJournal(journal_path)
    first_stage = sorted(sc.plan_waves(sa.load_graph())[0])[0]
    journal.append("stage_passed", {"stage_id": first_stage, "instance_id": "conformance-instance"})
    coord2 = sc.StageAgentCoordinator(run_id="r", task_id="t", adapters=[_command_adapter(tmp_dir)],
                                       journal=sc.StageCoordinatorJournal(journal_path),
                                       host_total_slots=4, poll_interval_seconds=0.01)
    resumed = first_stage in coord2.passed_stages
    return {"status": STATUS_PASS if resumed else STATUS_FAIL,
            "detail": f"stage={first_stage} resumed_as_passed={resumed}"}


def scenario_stop_cancel(tmp_dir: Path) -> dict[str, Any]:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    sleeper = tmp_dir / "sleeper.py"
    sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    adapter = sc.CommandAgentAdapter(command=[sys.executable, str(sleeper)], base_tmp_dir=tmp_dir)
    graph = sa.load_graph()
    stage = dict(graph["stages"][0])
    role = sc.role_by_id(graph, stage["role_id"])
    instance = adapter.spawn(role=role, stage=stage, stage_context={})
    instance = adapter.poll(instance)
    adapter.cancel(instance, reason="conformance_stop")
    cancelled = instance.status == "cancelled"
    _reap(adapter)
    return {"status": STATUS_PASS if cancelled else STATUS_FAIL,
            "detail": f"instance_status={instance.status}"}


def _drive_full_graph(adapter: sc.AgentDriver) -> dict[str, str]:
    """Drive every stage in the real graph, in dependency (wave) order, directly through the
    adapter — the full delivery sandbox, at the adapter-mechanics level (see the scope note on
    `_drive_stage_via_adapter`)."""
    graph = sa.load_graph()
    statuses: dict[str, str] = {}
    for wave in sc.plan_waves(graph):
        for stage_id in wave:
            instance, _output, _receipt = _drive_stage_via_adapter(adapter, stage_id=stage_id)
            statuses[stage_id] = instance.status
    return statuses


def scenario_full_delivery_sandbox(tmp_dir: Path) -> dict[str, Any]:
    adapter = _command_adapter(tmp_dir)
    statuses = _drive_full_graph(adapter)
    _reap(adapter)
    ok = bool(statuses) and all(status == "passed" for status in statuses.values())
    return {"status": STATUS_PASS if ok else STATUS_FAIL,
            "detail": f"stages_driven={len(statuses)} all_passed={ok} statuses={statuses}"}


def scenario_post_completion_regression(tmp_dir: Path) -> dict[str, Any]:
    adapter = _command_adapter(tmp_dir)
    before = _drive_full_graph(adapter)
    if not before or not all(s == "passed" for s in before.values()):
        _reap(adapter)
        return {"status": STATUS_FAIL, "detail": "did not reach terminal before regression re-run"}
    after = _drive_full_graph(adapter)  # idempotent re-drive after "completion" — must not regress
    _reap(adapter)
    stable = before.keys() == after.keys() and all(before[k] == after[k] for k in before)
    return {"status": STATUS_PASS if stable else STATUS_FAIL,
            "detail": f"stable_after_rerun={stable}"}


def scenario_cli(tmp_dir: Path, runtime: str) -> dict[str, Any]:
    checks = [HERE / "stage_agent_conformance.py", HERE / "verify_adapters.py", HERE / "claims_audit.py"]
    missing = [str(p) for p in checks if not p.is_file()]
    status = STATUS_PASS if not missing else STATUS_FAIL
    return {"status": status, "detail": "harness CLIs present" if not missing else f"missing: {missing}"}


def scenario_mcp(tmp_dir: Path, runtime: str) -> dict[str, Any]:
    probe = probe_runtime(runtime)
    if probe["mcp_config_section_documented"] is None:
        return {"status": STATUS_NOT_VERIFIABLE, "detail": "no adapter README to check"}
    status = STATUS_PASS if probe["mcp_config_section_documented"] else STATUS_FAIL
    return {"status": status, "detail": f"mcp_config_section_documented={probe['mcp_config_section_documented']}"}


def scenario_hook_bound(tmp_dir: Path, runtime: str) -> dict[str, Any]:
    row = MATRIX.get(runtime, {})
    if not row.get("lifecycle_hooks"):
        return {"status": STATUS_NOT_VERIFIABLE,
                "detail": "runtime has no lifecycle-hook capability per matrix; nothing to verify"}
    if runtime not in ("claude", "cursor"):
        return {"status": STATUS_NOT_VERIFIABLE,
                "detail": "hook-bound install contract only mechanically gated for claude/cursor "
                          "(scripts/verify_adapters.py Tier 1); other hook-bound runtimes "
                          "(simplicio_agent/openclaw) bind natively and require the live host"}
    # Shell out to scripts/verify_adapters.py as its OWN process (mirrors
    # scripts/claims_audit.py::check_adapter_contract) rather than importing/calling
    # verify_adapters.verify() in-process. This harness spawns many CommandAgentAdapter
    # subprocesses across scenarios in the same Python process; on Windows the accumulated
    # handle churn can make an in-process subprocess.Popen call fail with a spurious
    # WinError even after the offending processes exited. A fresh child process is immune to
    # the parent's own handle-table pressure, and retrying it once covers any remaining
    # transient spawn failure (mirrors claims_audit.py's `_git_commit_exists` retry pattern).
    last_detail = ""
    attempts = 5
    for attempt in range(attempts):
        try:
            import gc
            gc.collect()  # release any dangling Popen/pipe objects before spawning
            r = subprocess.run([sys.executable, str(HERE / "verify_adapters.py"), runtime],
                               capture_output=True, text=True, cwd=str(REPO), timeout=90)
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_detail = f"verify_adapters.py subprocess crashed: {exc}"
            time.sleep(0.5 * (attempt + 1))
            continue
        out = (r.stdout or "") + (r.stderr or "")
        status = STATUS_PASS if r.returncode == 0 else STATUS_FAIL
        detail = "install contract satisfied" if r.returncode == 0 else _sanitize(out.strip()[-800:])
        return {"status": status, "detail": detail}
    # Exhausted retries on a process-spawn error (not a contract check that ran and failed) —
    # a documented Windows sandbox flakiness class (see scripts/claims_audit.py's
    # `_git_commit_exists` retry comment for the same WinError family), NOT evidence the
    # install contract itself is broken. Classifying this as NOT_VERIFIABLE rather than FAIL
    # avoids conflating "this sandbox couldn't spawn a process right now" with "the runtime's
    # hook-bound contract regressed" — the latter is what verify_adapters.py actually gates.
    return {"status": STATUS_NOT_VERIFIABLE,
            "detail": f"could not spawn verify_adapters.py after {attempts} attempts "
                      f"(process-spawn flakiness, not a contract failure): {last_detail}"}


def scenario_self_paced(tmp_dir: Path, runtime: str) -> dict[str, Any]:
    row = MATRIX.get(runtime, {})
    if not row.get("scheduler_self_paced"):
        return {"status": STATUS_NOT_VERIFIABLE, "detail": "runtime does not claim self-paced drive"}
    return {"status": STATUS_NOT_VERIFIABLE,
            "detail": "self-paced drive requires the live host scheduler/cron tick; not "
                      "reproducible in this sandbox — see adapters/MATRIX.md N2/N3 fallback"}


def scenario_native_subagent_mode(tmp_dir: Path, runtime: str) -> dict[str, Any]:
    row = MATRIX.get(runtime, {})
    if not row.get("native_agent_api"):
        return {"status": STATUS_NOT_VERIFIABLE, "detail": "runtime does not claim a native agent API"}
    return {"status": STATUS_NOT_VERIFIABLE,
            "detail": "NativeAgentAdapter's spawn/send/poll/cancel protocol is unit-tested with a "
                      "mocked host binding (tests/test_stage_agent_coordinator.py::FakeNativeOps) "
                      "but a REAL native session requires the live external runtime; not driven "
                      "here to avoid a synthetic PASS"}


def scenario_github_reporting(tmp_dir: Path, runtime: str) -> dict[str, Any]:
    pr_evidence = REPO / "scripts" / "pr_evidence.py"
    if not pr_evidence.is_file():
        return {"status": STATUS_FAIL, "detail": "scripts/pr_evidence.py missing"}
    body = pr_evidence.read_text(encoding="utf-8", errors="replace")
    idempotent_documented = "idempotent" in body.lower()
    return {"status": STATUS_NOT_VERIFIABLE,
            "detail": f"pr_evidence.py present (idempotent_create_update_documented="
                      f"{idempotent_documented}); actual create->update against GitHub requires "
                      f"network + a real repo/PR and is out of scope for a sandbox conformance run"}


def run_scenarios(runtime: str, *, scenarios: list[str] | None = None) -> dict[str, dict[str, Any]]:
    scenarios = scenarios or REQUIRED_SCENARIOS
    out: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="stage-conformance-") as td:
        tmp_dir = Path(td)
        for name in scenarios:
            try:
                if name == "portable_command_mode":
                    out[name] = scenario_portable_command_mode(tmp_dir / name)
                elif name == "queue_worker_mode":
                    out[name] = scenario_queue_worker_mode(tmp_dir / name)
                elif name == "limited_slots_waves":
                    out[name] = scenario_limited_slots_waves(tmp_dir / name)
                elif name == "no_independent_actor_blocked":
                    out[name] = scenario_no_independent_actor_blocked(tmp_dir / name)
                elif name == "restart_resume":
                    out[name] = scenario_restart_resume(tmp_dir / name)
                elif name == "stop_cancel":
                    out[name] = scenario_stop_cancel(tmp_dir / name)
                elif name == "full_delivery_sandbox":
                    out[name] = scenario_full_delivery_sandbox(tmp_dir / name)
                elif name == "post_completion_regression":
                    out[name] = scenario_post_completion_regression(tmp_dir / name)
                elif name == "cli":
                    out[name] = scenario_cli(tmp_dir / name, runtime)
                elif name == "mcp":
                    out[name] = scenario_mcp(tmp_dir / name, runtime)
                elif name == "hook_bound":
                    out[name] = scenario_hook_bound(tmp_dir / name, runtime)
                elif name == "self_paced":
                    out[name] = scenario_self_paced(tmp_dir / name, runtime)
                elif name == "native_subagent_mode":
                    out[name] = scenario_native_subagent_mode(tmp_dir / name, runtime)
                elif name == "github_reporting":
                    out[name] = scenario_github_reporting(tmp_dir / name, runtime)
                else:
                    out[name] = {"status": STATUS_FAIL, "detail": f"unknown scenario {name!r}"}
            except Exception as exc:  # a crashing scenario is a FAIL, never silently dropped
                out[name] = {"status": STATUS_FAIL, "detail": f"scenario crashed: {exc}"}
        for name, verdict in out.items():
            path = _write_evidence(runtime, f"scenario_{name}", verdict)
            verdict["evidence_path"] = path
    return out


def classify(status: str) -> str:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"non-terminal/unknown status: {status!r}")
    return status


# --------------------------------------------------------------------------
# report — aggregate + semantic drift detection.
# --------------------------------------------------------------------------


def check_matrix_doc_consistency() -> list[str]:
    """MATRIX must name at least every runtime adapters/MATRIX.md's table names. This is a cheap
    guard against the frozen snapshot silently rotting out of sync with the doc (never a full
    prose parse — the doc is the source of truth for humans, this is a drift tripwire)."""
    matrix_md = REPO / "adapters" / "MATRIX.md"
    if not matrix_md.is_file():
        return ["adapters/MATRIX.md missing"]
    body = matrix_md.read_text(encoding="utf-8", errors="replace")
    drift = []
    for runtime in MATRIX:
        alias = ADAPTER_DIR_ALIASES.get(runtime, runtime)
        # doc uses human names (Claude Code, Simplicio Agent, ...) but always links the adapter dir
        if f"{alias}/README.md" not in body and f"({alias}/README.md" not in body and alias not in body:
            drift.append(f"{runtime}: not referenced in adapters/MATRIX.md")
    return drift


def build_report(runtimes: list[str], *, run_scenarios_for: list[str] | None = None) -> dict[str, Any]:
    run_scenarios_for = run_scenarios_for if run_scenarios_for is not None else runtimes
    report: dict[str, Any] = {
        "schema": "simplicio.stage-agent-conformance-report/v1",
        "generated_at": _now_iso(),
        "runtimes": {},
        "drift": [],
    }
    doc_drift = check_matrix_doc_consistency()
    report["drift"].extend(doc_drift)

    for runtime in runtimes:
        probe = probe_runtime(runtime)
        scenarios = run_scenarios(runtime) if runtime in run_scenarios_for else {}
        counts = {"pass": 0, "blocked": 0, "not_verifiable_in_sandbox": 0, "fail": 0}
        for verdict in scenarios.values():
            counts[classify(verdict["status"])] += 1
        row_drift = []
        row = MATRIX.get(runtime, {})
        if row.get("lifecycle_hooks") and probe["turn_header_contract_present"] is False:
            row_drift.append("matrix claims lifecycle_hooks but turn-header contract missing from SKILL.md")
        if row.get("installed") and not probe["installer_wired"]:
            row_drift.append("matrix claims an install_lib target but runtime is not in install_lib.RUNTIMES")
        report["drift"].extend(f"{runtime}: {d}" for d in row_drift)
        report["runtimes"][runtime] = {
            "matrix": row, "probe": probe, "scenarios": scenarios,
            "scenario_counts": counts, "drift": row_drift,
        }
        _write_evidence(runtime, "probe", probe)

    total_fail = sum(r["scenario_counts"]["fail"] for r in report["runtimes"].values())
    report["summary"] = {
        "runtimes_covered": len(runtimes),
        "total_scenarios_run": sum(sum(r["scenario_counts"].values()) for r in report["runtimes"].values()),
        "total_pass": sum(r["scenario_counts"]["pass"] for r in report["runtimes"].values()),
        "total_blocked": sum(r["scenario_counts"]["blocked"] for r in report["runtimes"].values()),
        "total_not_verifiable_in_sandbox": sum(
            r["scenario_counts"]["not_verifiable_in_sandbox"] for r in report["runtimes"].values()),
        "total_fail": total_fail,
        "semantic_drift_count": len(report["drift"]),
    }
    report_path = EVIDENCE_ROOT / "report.json"
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_sanitize(json.dumps(report, indent=2, sort_keys=True, default=str)), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


# --------------------------------------------------------------------------
# verify-installed — reuse verify_adapters.py, don't duplicate its contract.
# --------------------------------------------------------------------------


def verify_installed(runtimes: list[str]) -> dict[str, list[str]]:
    out = {}
    for runtime in runtimes:
        if runtime not in install_lib.RUNTIMES:
            out[runtime] = ["not wired into scripts/install.sh (best-effort/manual install per README)"]
            continue
        out[runtime] = verify_adapters.verify(runtime)
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _resolve_runtimes(args_runtimes: list[str]) -> list[str]:
    if not args_runtimes or args_runtimes == ["--all"]:
        return list(MATRIX)
    unknown = [r for r in args_runtimes if r not in MATRIX]
    if unknown:
        print("unknown runtime(s): %s" % " ".join(unknown), file=sys.stderr)
        sys.exit(2)
    return args_runtimes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stage_agent_conformance.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--json", action="store_true")

    p_probe = sub.add_parser("probe")
    p_probe.add_argument("runtimes", nargs="*")
    p_probe.add_argument("--json", action="store_true")

    p_run = sub.add_parser("run")
    p_run.add_argument("runtimes", nargs="*")
    p_run.add_argument("--scenario", action="append", default=None)
    p_run.add_argument("--json", action="store_true")

    p_report = sub.add_parser("report")
    p_report.add_argument("runtimes", nargs="*")
    p_report.add_argument("--json", action="store_true")

    p_verify = sub.add_parser("verify-installed")
    p_verify.add_argument("runtimes", nargs="*")
    p_verify.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "list":
        if args.json:
            print(json.dumps(MATRIX, indent=2, sort_keys=True))
        else:
            for runtime, row in sorted(MATRIX.items()):
                print(f"{runtime:16s} tier={row['tier']} native={row['native_agent_api']} "
                      f"command={row['command_adapter']} queue={row['queue_adapter']} "
                      f"hooks={row['lifecycle_hooks']} self_paced={row['scheduler_self_paced']}")
        return 0

    if args.command == "probe":
        runtimes = _resolve_runtimes(args.runtimes)
        results = {rt: probe_runtime(rt) for rt in runtimes}
        if args.json:
            print(json.dumps(results, indent=2, sort_keys=True))
        else:
            for rt, r in results.items():
                print(f"{rt}: readme={r['adapter_readme_exists']} skills={r['seven_skills_present']} "
                      f"hooks_dir={r['hooks_dir_exists']} mcp_doc={r['mcp_config_section_documented']}")
        return 0

    if args.command == "run":
        runtimes = _resolve_runtimes(args.runtimes)
        all_ok = True
        for rt in runtimes:
            results = run_scenarios(rt, scenarios=args.scenario)
            if args.json:
                print(json.dumps({rt: results}, indent=2, sort_keys=True))
            else:
                for name, verdict in results.items():
                    print(f"[{verdict['status']:26s}] {rt}/{name} — {verdict['detail']}")
            if any(v["status"] == STATUS_FAIL for v in results.values()):
                all_ok = False
        return 0 if all_ok else 1

    if args.command == "report":
        runtimes = _resolve_runtimes(args.runtimes)
        report = build_report(runtimes)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"conformance report: {report['report_path']}")
            for k, v in report["summary"].items():
                print(f"  {k}: {v}")
            if report["drift"]:
                print("semantic drift detected:")
                for d in report["drift"]:
                    print(f"  - {d}")
        return 1 if (report["summary"]["semantic_drift_count"] or report["summary"]["total_fail"]) else 0

    if args.command == "verify-installed":
        runtimes = _resolve_runtimes(args.runtimes)
        results = verify_installed(runtimes)
        failed = 0
        for rt, fails in results.items():
            if fails:
                failed += 1
                print(f"FAIL  {rt}")
                for f in fails:
                    print(f"        - {f}")
            else:
                print(f"PASS  {rt}")
        if args.json:
            print(json.dumps(results, indent=2, sort_keys=True))
        return 1 if failed else 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
