#!/usr/bin/env python3
"""Raw conformance/performance evidence for the integrated Loop flow."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import statistics
import subprocess
import sys
import time
from typing import Any, Callable, Mapping

from simplicio_loop.agent_fabric import (
    AddressRegistry, FabricAddress, FabricCapability, FabricController,
    FabricError, HookwallAdapter, build_envelope,
)
from simplicio_loop.coverage_custodian_host import proceed_decision

SCHEMA = "simplicio.integrated-conformance-benchmark/v1"
REPETITIONS_MIN = 10


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(__import__("math").ceil(len(ordered) * fraction)) - 1))]


def summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    values = [item["total_seconds"] for item in samples]
    return {
        "count": len(values), "p50_seconds": statistics.median(values),
        "p95_seconds": percentile(values, .95),
        "mean_seconds": statistics.mean(values),
        "stdev_seconds": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min_seconds": min(values), "max_seconds": max(values),
        "quality_pass_rate": statistics.mean(item["quality_pass"] for item in samples),
        "tokens": None, "tokens_null_reason": "NO_LLM_OR_PROVIDER_USED",
    }


def workload(payload: bytes) -> str:
    # Same deterministic task and input in baseline/integrated lanes.
    return hashlib.sha256(payload).hexdigest()


def fabric_fixture(workspace: Path, attempt: int = 1):
    registry = AddressRegistry()
    sender = FabricAddress(
        "simplicio-loop", "router", FabricCapability("route", "1", "DEFAULT", "c"), 1, "loop://router",
    )
    recipient = FabricAddress(
        "simplicio-mapper", "executor", FabricCapability("execute", "1", "MEASURED", "c"), 1,
        "mapper://executor",
    )
    registry.register(sender); registry.register(recipient)
    adapter = HookwallAdapter(
        str(workspace),
        lambda value: proceed_decision(value, phase="pre"),
        lambda value, receipt: proceed_decision(
            value, phase="post", receipt_hash=receipt["receipt_hash"],
        ),
    )
    envelope = build_envelope(
        run_id="benchmark-816", task_id="same-task", work_item_id="same-work-item",
        stage="execution", attempt=attempt, fence="f1", plan_revision="1",
        sender=sender, recipient=recipient, payload_handle="mapper://page/same",
        payload_hash=sha(b"same-input"), causal_parent="root", sequence=attempt,
        scope="cross-repo", repo="wesleysimplicio/simplicio-loop", commit="a7bef68170f871af3acd89c92a4757aa0db0b5d8",
        worktree=str(workspace), policy_hash="policy-v1", ttl_seconds=120,
        expected_receipt="fabric-dispatch-receipt/v1",
        evidence_handles=["mapper://atlas", "quality://mandatory"],
        reply_handle="loop://ledger", priority=1, resource_class="write",
    )
    return registry, adapter, envelope


def measure_lane(lane: str, payload: bytes, expected: str, workspace: Path,
                 repetitions: int) -> dict[str, Any]:
    def once(measured: bool) -> dict[str, Any]:
        before_cpu = time.process_time()
        before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        started = time.perf_counter()
        execute_seconds = 0.0
        if lane == "baseline":
            execute_started = time.perf_counter()
            result = workload(payload)
            execute_seconds = time.perf_counter() - execute_started
            workers = 1
            hookwall = False
        else:
            registry, adapter, envelope = fabric_fixture(workspace)
            controller = FabricController(registry, max_attempts=2, max_inflight=20)

            def execute(_):
                nonlocal execute_seconds
                execute_started = time.perf_counter()
                value = workload(payload)
                execute_seconds = time.perf_counter() - execute_started
                return {"status": "FIXED", "result": value, "completion": None}

            receipt = controller.fire(
                envelope, current_fence="f1", hookwall=adapter, execute=execute,
            )
            result = receipt["effect_receipt"]["effect"]["result"]
            workers = registry.workers_materialized
            hookwall = receipt["effect_receipt"]["hookwall_evidence"]["verdict"] == "verified"
        total = time.perf_counter() - started
        return {
            "total_seconds": total, "execute_seconds": execute_seconds,
            "control_overhead_seconds": max(0, total - execute_seconds),
            "cpu_seconds": time.process_time() - before_cpu,
            "rss_kib_delta": max(0, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before_rss),
            "result_sha256": result, "quality_pass": result == expected,
            "workers_materialized": workers, "hookwall_verified": hookwall,
            "measured": measured,
        }

    warmup = [once(False) for _ in range(2)]
    samples = [once(True) for _ in range(repetitions)]
    return {"warmup": warmup, "samples": samples, "summary": summary(samples)}


def expect_failure(name: str, action: Callable[[], None], reason: str) -> dict[str, Any]:
    try:
        action()
    except BaseException as exc:
        actual = getattr(exc, "reason_code", type(exc).__name__)
        return {"name": name, "blocked": True, "reason_code": actual,
                "expected_reason": reason, "matches": actual == reason}
    return {"name": name, "blocked": False, "reason_code": None,
            "expected_reason": reason, "matches": False}


def fault_injection(workspace: Path, payload: bytes) -> dict[str, Any]:
    registry, adapter, envelope = fabric_fixture(workspace)
    controller = FabricController(registry, max_attempts=2)
    effects = {"committed": 0}

    crash = expect_failure(
        "crash",
        lambda: controller.fire(
            envelope, current_fence="f1", hookwall=adapter,
            execute=lambda _: (_ for _ in ()).throw(RuntimeError("injected crash")),
        ),
        "RuntimeError",
    )
    # Recovery uses a fresh, causally distinct attempt; replaying it cannot duplicate the effect.
    _, adapter2, recovery = fabric_fixture(workspace, attempt=2)

    def recover(_):
        effects["committed"] += 1
        return {"status": "FIXED", "result": workload(payload), "completion": None}

    recovered = controller.fire(recovery, current_fence="f1", hookwall=adapter2, execute=recover)
    duplicate = controller.fire(recovery, current_fence="f1", hookwall=adapter2, execute=recover)

    stale_registry, _, stale = fabric_fixture(workspace)
    stale["deadline_ns"] = 1
    stale_unsigned = dict(stale); stale_unsigned.pop("checksum")
    stale["checksum"] = sha(stale_unsigned)
    stale_controller = FabricController(stale_registry)
    stale_case = expect_failure(
        "timeout_stale", lambda: stale_controller.fire(
            stale, current_fence="f1", hookwall=adapter, execute=lambda _: {},
        ), "envelope_stale",
    )
    async def timeout_run() -> None:
        from simplicio_loop.fabric_scheduler import AsyncFabricScheduler, FabricJob

        async def slow() -> None:
            await asyncio.sleep(.05)

        async with AsyncFabricScheduler(max_running=1, queue_capacity=1) as scheduler:
            future = await scheduler.submit(FabricJob(
                "timeout-injected", slow, timeout_seconds=.001,
            ))
            await future

    timeout_case = expect_failure(
        "timeout", lambda: asyncio.run(timeout_run()), "TimeoutError",
    )
    conflict_case = expect_failure(
        "cross_fence_conflict", lambda: stale_controller.fire(
            envelope, current_fence="other", hookwall=adapter, execute=lambda _: {},
        ), "envelope_cross_fence",
    )
    tampered = dict(envelope, payload_hash="tampered")
    tamper_case = expect_failure(
        "tamper", lambda: stale_controller.fire(
            tampered, current_fence="f1", hookwall=adapter, execute=lambda _: {},
        ), "envelope_checksum_invalid",
    )
    return {
        "cases": [crash, timeout_case, stale_case, conflict_case, tamper_case],
        "recovery_receipt_digest": recovered["receipt_digest"],
        "duplicate_same_receipt": duplicate == recovered,
        "committed_effects": effects["committed"],
        "attempts": controller.replay()["attempts"],
        "addenda": controller.replay()["addenda"],
        "all_faults_blocked_as_expected": all(
            item["blocked"] and item["matches"]
            for item in (crash, timeout_case, stale_case, conflict_case, tamper_case)
        ),
        "recovery_no_duplicate": effects["committed"] == 1 and duplicate == recovered,
    }


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def environment_receipt(installed_root: Path, wheel_hashes: Mapping[str, str]) -> dict[str, Any]:
    rust = subprocess.run(["rustc", "--version"], capture_output=True, text=True, check=False) \
        if __import__("shutil").which("rustc") else None
    cpu_model = None
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        cpu_model = next((
            line.split(":", 1)[1].strip() for line in cpuinfo.read_text(errors="replace").splitlines()
            if line.lower().startswith("model name")
        ), None)
    modules = {}
    for name in ("simplicio_loop", "simplicio_mapper"):
        path = Path(__import__(name).__file__).resolve()
        modules[name] = {"path": str(path), "sha256": file_sha(path)}
    return {
        "hardware": {"cpu_model": cpu_model, "cpu_count": os.cpu_count(),
                     "machine": platform.machine()},
        "os": {"system": platform.system(), "release": platform.release(),
               "platform": platform.platform()},
        "python": sys.version,
        "rust": rust.stdout.strip() if rust else None,
        "rust_null_reason": None if rust else "RUST_TOOLCHAIN_UNAVAILABLE",
        "provider": None, "provider_null_reason": "NO_PROVIDER_USED",
        "model": None, "model_null_reason": "NO_LLM_USED",
        "config": {
            "max_attempts": 2, "max_inflight": 20, "warmup": 2,
            "repetitions_min": REPETITIONS_MIN, "config_sha256": sha({
                "max_attempts": 2, "max_inflight": 20, "warmup": 2,
                "repetitions_min": REPETITIONS_MIN,
            }),
        },
        "versions": {name: importlib.metadata.version(name) for name in (
            "simplicio-loop", "simplicio-mapper",
        )},
        "commits": {
            "simplicio-loop": "a7bef68170f871af3acd89c92a4757aa0db0b5d8",
            "simplicio-mapper": "0387c3c5cf391c4cbfc1aaa4f2005db283ceb534",
        },
        "installed_root": str(installed_root), "installed_modules": modules,
        "wheel_sha256": dict(wheel_hashes),
        "platform_conformance": {
            "linux": "MEASURED" if platform.system() == "Linux" else "NOT_THIS_HOST",
            "windows": None, "windows_null_reason": "WINDOWS_RUNNER_UNAVAILABLE",
            "macos": None, "macos_null_reason": "MACOS_RUNNER_UNAVAILABLE",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--loop-wheel-sha256", required=True)
    parser.add_argument("--mapper-wheel-sha256", required=True)
    args = parser.parse_args()
    if args.repetitions < REPETITIONS_MIN:
        parser.error("at least 10 repetitions required")
    root = Path(args.root).resolve(); root.mkdir(parents=True, exist_ok=True)
    payload = b"same-input"; expected = workload(payload)
    result = {
        "schema": SCHEMA, "classification": "MEASURED_CLEAN_INSTALL",
        "task": {"name": "sha256-same-input", "input_sha256": sha(payload),
                 "expected_result": expected},
        "environment": environment_receipt(
            Path(__import__("simplicio_loop").__file__).resolve().parent.parent,
            {
                "simplicio-loop": args.loop_wheel_sha256,
                "simplicio-mapper": args.mapper_wheel_sha256,
            },
        ),
        "lanes": {
            "baseline": measure_lane("baseline", payload, expected, root, args.repetitions),
            "integrated": measure_lane("integrated", payload, expected, root, args.repetitions),
        },
        "fault_injection": fault_injection(root, payload),
        "tokens": None, "tokens_null_reason": "NO_LLM_OR_PROVIDER_USED",
        "quality": {"baseline_expected": expected, "integrated_expected": expected,
                    "regression": False},
        "commands": [
            "pip install --no-deps --no-build-isolation --target <clean-target> <wheels>",
            "PYTHONPATH=<clean-target> python scripts/conformance_benchmark_816.py "
            "--root <run> --output raw.json --repetitions 10",
        ],
        "limitations": [
            "Linux measured locally; Windows/macOS runners unavailable and not claimed",
            "Rust/provider/model were not required and were not started",
        ],
        "rollback": "revert the conformance PR; evidence remains non-authoritative audit data",
        "local_llm": False,
    }
    result["raw_data_sha256"] = sha(result)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if not result["fault_injection"]["all_faults_blocked_as_expected"]:
        raise SystemExit(1)
    if not result["fault_injection"]["recovery_no_duplicate"]:
        raise SystemExit(1)
    if any(lane["summary"]["quality_pass_rate"] != 1 for lane in result["lanes"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
